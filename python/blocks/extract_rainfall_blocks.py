"""Block-level Indicator 5: Heavy rainfall days from CHIRPS Daily."""

import ee
import pandas as pd

from utils_blocks import (
    load_blocks, blocks_to_fc, batch_blocks,
    get_analysis_window, save_block_output,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee


def extract_rainfall_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute rainfall indicators via zonal reduction over each block.

    Returns DataFrame with columns: block_id, rain_days_gt{X}mm,
    rain_total_mm, rain_max_day_mm, rain_mean_daily_mm, rain_valid_obs,
    rain_window_start, rain_window_end.
    """
    rain_cfg = config["rainfall"]
    blocks_cfg = config["blocks"]
    thresholds = rain_cfg["thresholds_mm"]

    start_date, end_date = get_analysis_window(
        config, rain_cfg["trailing_years"]
    )
    print(f"  Analysis window: {start_date} to {end_date}")

    chirps = (
        ee.ImageCollection(rain_cfg["dataset"])
        .filterDate(start_date, end_date)
        .select(rain_cfg["band"])
    )

    bands = []
    band_names = []

    for t in thresholds:
        count_img = chirps.map(lambda img, t=t: img.gt(t)).sum()
        bands.append(count_img)
        band_names.append(f"rain_days_gt{t}mm")

    bands.append(chirps.sum())
    band_names.append("rain_total_mm")
    bands.append(chirps.max())
    band_names.append("rain_max_day_mm")
    bands.append(chirps.mean())
    band_names.append("rain_mean_daily_mm")
    bands.append(chirps.count())
    band_names.append("rain_valid_obs")

    stacked = ee.Image.cat(bands).rename(band_names)

    all_results = []
    total = len(blocks_gdf)
    processed = 0

    for batch in batch_blocks(blocks_gdf, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = stacked.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=rain_cfg.get("scale_m", 5566),
        )

        for f in sampled.getInfo()["features"]:
            props = f["properties"]
            row = {"block_id": props["block_id"]}
            for bn in band_names:
                row[bn] = props.get(bn)
            row["rain_window_start"] = start_date
            row["rain_window_end"] = end_date
            all_results.append(row)

        processed += len(batch)
        print(f"    {processed}/{total} blocks processed")

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    print("Extracting rainfall (CHIRPS Daily) — block level...")
    result = extract_rainfall_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, "rainfall_blocks", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
