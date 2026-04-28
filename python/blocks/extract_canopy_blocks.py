"""Block-level Indicator 4: Tree canopy cover from ESA WorldCover 10m."""

import ee
import pandas as pd

from utils_blocks import (
    load_blocks, blocks_to_fc, batch_blocks, save_block_output,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee


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

    all_results = []
    total = len(blocks_gdf)
    processed = 0

    for batch in batch_blocks(blocks_gdf, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = tree_mask.reduceRegions(
            collection=fc,
            reducer=reducer,
            scale=canopy_cfg["scale_m"],
        )

        for f in sampled.getInfo()["features"]:
            props = f["properties"]
            all_results.append({
                "block_id": props["block_id"],
                "canopy_fraction": props.get("mean"),
                "canopy_pixel_count": props.get("count"),
                "canopy_tree_pixels": props.get("sum"),
            })

        processed += len(batch)
        print(f"    {processed}/{total} blocks processed")

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    print("Extracting tree canopy cover (ESA WorldCover 10m) — block level...")
    result = extract_canopy_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, "canopy_blocks", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
