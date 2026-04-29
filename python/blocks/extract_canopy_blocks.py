"""Block-level Indicator 4: Tree canopy cover from ESA WorldCover 10m."""

import time

import ee
import pandas as pd

from utils_blocks import (
    load_blocks, blocks_to_fc, batch_blocks, save_block_output,
    safe_getinfo, load_checkpoint, append_checkpoint,
    clear_checkpoint, filter_remaining_blocks,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee

INDICATOR_NAME = "canopy_blocks"


def extract_canopy_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute tree canopy fraction over each block polygon.

    Returns DataFrame with columns: block_id, canopy_fraction,
    canopy_pixel_count, canopy_tree_pixels.
    """
    canopy_cfg = config["canopy"]
    blocks_cfg = config["blocks"]

    worldcover = (
        ee.ImageCollection(canopy_cfg["dataset"])
        .mosaic()
        .select(canopy_cfg["band"])
    )
    tree_mask = worldcover.eq(canopy_cfg["tree_class_value"]).rename("is_tree")

    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.count(), sharedInputs=True)
        .combine(ee.Reducer.sum(), sharedInputs=True)
    )

    checkpoint_df = load_checkpoint(INDICATOR_NAME, config)
    remaining = filter_remaining_blocks(blocks_gdf, checkpoint_df,
                                        blocks_cfg["block_id_field"])

    total = len(blocks_gdf)
    processed = total - len(remaining)
    t0 = time.time()

    for batch in batch_blocks(remaining, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = tree_mask.reduceRegions(
            collection=fc,
            reducer=reducer,
            scale=canopy_cfg["scale_m"],
        )

        info = safe_getinfo(sampled)
        batch_rows = []
        for f in info["features"]:
            props = f["properties"]
            batch_rows.append({
                "block_id": props["block_id"],
                "canopy_fraction": props.get("mean"),
                "canopy_pixel_count": props.get("count"),
                "canopy_tree_pixels": props.get("sum"),
            })

        append_checkpoint(batch_rows, INDICATOR_NAME, config)

        processed += len(batch)
        elapsed = time.time() - t0
        rate = (processed - (total - len(remaining))) / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate / 60 if rate > 0 else 0
        print(f"    {processed}/{total} blocks | "
              f"{rate:.0f} blocks/s | ETA {eta:.1f} min")

    final_df = load_checkpoint(INDICATOR_NAME, config)
    clear_checkpoint(INDICATOR_NAME, config)
    return final_df


def main():
    config = load_config()
    init_gee(config)

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    print("Extracting tree canopy cover (ESA WorldCover 10m) — block level...")
    result = extract_canopy_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
