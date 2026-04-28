"""Block-level Indicator 7: Nighttime lights from VIIRS monthly composites."""

import ee
import pandas as pd

from utils_blocks import (
    load_blocks, blocks_to_fc, batch_blocks,
    get_analysis_window_months, save_block_output,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee


def extract_nightlights_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute nighttime radiance zonal stats over each block.

    Returns DataFrame with columns: block_id, ntl_mean_radiance,
    ntl_max_radiance.
    """
    ntl_cfg = config["nightlights"]
    blocks_cfg = config["blocks"]

    start_date, end_date = get_analysis_window_months(
        config, ntl_cfg["trailing_months"]
    )
    print(f"  Analysis window: {start_date} to {end_date}")

    viirs = (
        ee.ImageCollection(ntl_cfg["dataset"])
        .filterDate(start_date, end_date)
        .select(ntl_cfg["band"])
    )

    # Temporal composites
    stacked = ee.Image.cat([
        viirs.mean().rename("ntl_mean_radiance"),
        viirs.max().rename("ntl_max_radiance"),
    ])

    all_results = []
    total = len(blocks_gdf)
    processed = 0

    for batch in batch_blocks(blocks_gdf, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = stacked.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=ntl_cfg.get("scale_m", 500),
        )

        for f in sampled.getInfo()["features"]:
            props = f["properties"]
            all_results.append({
                "block_id": props["block_id"],
                "ntl_mean_radiance": props.get("ntl_mean_radiance"),
                "ntl_max_radiance": props.get("ntl_max_radiance"),
            })

        processed += len(batch)
        print(f"    {processed}/{total} blocks processed")

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    print("Extracting nighttime lights (VIIRS) — block level...")
    result = extract_nightlights_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, "nightlights_blocks", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
