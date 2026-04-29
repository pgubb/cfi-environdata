"""Block-level Indicator 1: Elevation zonal statistics from SRTM 30m."""

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

INDICATOR_NAME = "elevation_blocks"


def extract_elevation_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute elevation zonal stats (mean, min, max, std) over each block.

    Returns DataFrame with columns: block_id, elev_mean_m, elev_min_m,
    elev_max_m, elev_std_m, elev_range_m.
    """
    elev_cfg = config["elevation"]
    blocks_cfg = config["blocks"]
    srtm = ee.Image(elev_cfg["dataset"]).select(elev_cfg["band"])

    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.min(), sharedInputs=True)
        .combine(ee.Reducer.max(), sharedInputs=True)
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
    )

    # Checkpoint / resume
    checkpoint_df = load_checkpoint(INDICATOR_NAME, config)
    remaining = filter_remaining_blocks(blocks_gdf, checkpoint_df,
                                        blocks_cfg["block_id_field"])

    total = len(blocks_gdf)
    processed = total - len(remaining)
    t0 = time.time()

    for batch in batch_blocks(remaining, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = srtm.reduceRegions(
            collection=fc,
            reducer=reducer,
            scale=config["gee"]["default_scale_m"],
        )

        info = safe_getinfo(sampled)
        batch_rows = []
        for f in info["features"]:
            props = f["properties"]
            elev_min = props.get("min")
            elev_max = props.get("max")
            elev_range = (
                elev_max - elev_min
                if elev_min is not None and elev_max is not None
                else None
            )
            batch_rows.append({
                "block_id": props["block_id"],
                "elev_mean_m": props.get("mean"),
                "elev_min_m": elev_min,
                "elev_max_m": elev_max,
                "elev_std_m": props.get("stdDev"),
                "elev_range_m": elev_range,
            })

        append_checkpoint(batch_rows, INDICATOR_NAME, config)

        processed += len(batch)
        elapsed = time.time() - t0
        rate = (processed - (total - len(remaining))) / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate / 60 if rate > 0 else 0
        print(f"    {processed}/{total} blocks | "
              f"{rate:.0f} blocks/s | ETA {eta:.1f} min")

    # Combine checkpoint + any prior results
    final_df = load_checkpoint(INDICATOR_NAME, config)
    clear_checkpoint(INDICATOR_NAME, config)
    return final_df


def main():
    config = load_config()
    init_gee(config)

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    print("Extracting elevation (SRTM 30m) — block level...")
    result = extract_elevation_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
