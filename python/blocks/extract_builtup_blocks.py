"""Block-level Indicator 8: Built-up surface fraction from JRC GHSL."""

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

INDICATOR_NAME = "builtup_blocks"


def extract_builtup_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute mean built-up surface fraction over each block polygon.

    Returns DataFrame with columns: block_id, builtup_fraction,
    builtup_pixel_count.
    """
    bu_cfg = config["builtup"]
    blocks_cfg = config["blocks"]

    ghsl = ee.Image(bu_cfg["dataset"]).select(bu_cfg["band"])
    ghsl_frac = ghsl.divide(100)

    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.count(), sharedInputs=True)
    )

    checkpoint_df = load_checkpoint(INDICATOR_NAME, config)
    remaining = filter_remaining_blocks(blocks_gdf, checkpoint_df,
                                        blocks_cfg["block_id_field"])

    total = len(blocks_gdf)
    processed = total - len(remaining)
    t0 = time.time()

    for batch in batch_blocks(remaining, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = ghsl_frac.reduceRegions(
            collection=fc,
            reducer=reducer,
            scale=bu_cfg.get("scale_m", 10),
        )

        info = safe_getinfo(sampled)
        batch_rows = []
        for f in info["features"]:
            props = f["properties"]
            batch_rows.append({
                "block_id": props["block_id"],
                "builtup_fraction": props.get("mean"),
                "builtup_pixel_count": props.get("count"),
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

    print("Extracting built-up surface fraction (GHSL) — block level...")
    result = extract_builtup_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
