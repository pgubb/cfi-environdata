"""Block-level Indicator 2: Extreme heat days from MODIS Land Surface Temperature."""

import time

import ee
import pandas as pd

from utils_blocks import (
    load_blocks, blocks_to_fc, batch_blocks,
    get_analysis_window, save_block_output,
    safe_getinfo, load_checkpoint, append_checkpoint,
    clear_checkpoint, filter_remaining_blocks,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee

INDICATOR_NAME = "heat_blocks"


def extract_heat_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute heat indicators via zonal reduction over each block.

    Uses a fixed analysis window (from config) rather than per-record
    fieldwork dates. Returns DataFrame with columns: block_id,
    heat_days_gt{X}c_mean, lst_mean_c, lst_max_c, lst_valid_obs_mean,
    heat_window_start, heat_window_end.
    """
    heat_cfg = config["heat"]
    blocks_cfg = config["blocks"]
    thresholds = heat_cfg["thresholds_celsius"]
    scale_factor = heat_cfg["scale_factor"]
    offset = heat_cfg["offset_kelvin_to_celsius"]

    start_date, end_date = get_analysis_window(
        config, heat_cfg["trailing_years"]
    )
    print(f"  Analysis window: {start_date} to {end_date}")

    modis = (
        ee.ImageCollection(heat_cfg["dataset"])
        .filterDate(start_date, end_date)
        .select(heat_cfg["band"])
    )

    def to_celsius(img):
        return (
            img.multiply(scale_factor)
            .add(offset)
            .copyProperties(img, ["system:time_start"])
        )

    modis_c = modis.map(to_celsius)

    bands = []
    band_names = []

    for t in thresholds:
        count_img = modis_c.map(lambda img, t=t: img.gt(t)).sum()
        bands.append(count_img)
        band_names.append(f"heat_days_gt{t}c_mean")

    if heat_cfg.get("compute_continuous", True):
        bands.append(modis_c.mean())
        band_names.append("lst_mean_c")
        bands.append(modis_c.max())
        band_names.append("lst_max_c")

    bands.append(modis_c.count())
    band_names.append("lst_valid_obs_mean")

    stacked = ee.Image.cat(bands).rename(band_names)

    checkpoint_df = load_checkpoint(INDICATOR_NAME, config)
    remaining = filter_remaining_blocks(blocks_gdf, checkpoint_df,
                                        blocks_cfg["block_id_field"])

    total = len(blocks_gdf)
    processed = total - len(remaining)
    t0 = time.time()

    for batch in batch_blocks(remaining, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = stacked.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=1000,
        )

        info = safe_getinfo(sampled)
        batch_rows = []
        for f in info["features"]:
            props = f["properties"]
            row = {"block_id": props["block_id"]}
            for bn in band_names:
                row[bn] = props.get(bn)
            row["heat_window_start"] = start_date
            row["heat_window_end"] = end_date
            batch_rows.append(row)

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

    print("Extracting extreme heat days (MODIS LST) — block level...")
    result = extract_heat_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
