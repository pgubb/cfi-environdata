"""Block-level Indicator 1: Elevation zonal statistics from SRTM 30m."""

import ee
import pandas as pd

from utils_blocks import (
    load_blocks, blocks_to_fc, batch_blocks, save_block_output,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee


def extract_elevation_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute elevation zonal stats (mean, min, max, std) over each block.

    Returns DataFrame with columns: block_id, city, elev_mean_m, elev_min_m,
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

    all_results = []
    total = len(blocks_gdf)
    processed = 0

    for batch in batch_blocks(blocks_gdf, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = srtm.reduceRegions(
            collection=fc,
            reducer=reducer,
            scale=config["gee"]["default_scale_m"],
        )

        for f in sampled.getInfo()["features"]:
            props = f["properties"]
            elev_min = props.get("min")
            elev_max = props.get("max")
            elev_range = (
                elev_max - elev_min
                if elev_min is not None and elev_max is not None
                else None
            )
            all_results.append({
                "block_id": props["block_id"],
                "elev_mean_m": props.get("mean"),
                "elev_min_m": elev_min,
                "elev_max_m": elev_max,
                "elev_std_m": props.get("stdDev"),
                "elev_range_m": elev_range,
            })

        processed += len(batch)
        print(f"    {processed}/{total} blocks processed")

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    print("Extracting elevation (SRTM 30m) — block level...")
    result = extract_elevation_blocks(blocks_gdf, config)

    # Add city back from the blocks GeoDataFrame
    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, "elevation_blocks", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
