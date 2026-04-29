"""Block-level Indicator 6: Air quality from MODIS MAIAC AOD."""

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

INDICATOR_NAME = "airquality_blocks"


def extract_airquality_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute AOD indicators via zonal reduction over each block.

    Returns DataFrame with columns: block_id, aod_days_gt{X},
    aod_mean, aod_max, aod_valid_obs, aod_window_start, aod_window_end.
    """
    aq_cfg = config["airquality"]
    blocks_cfg = config["blocks"]
    thresholds = aq_cfg["thresholds_aod"]
    scale_factor = aq_cfg["scale_factor"]

    start_date, end_date = get_analysis_window(
        config, aq_cfg["trailing_years"]
    )
    print(f"  Analysis window: {start_date} to {end_date}")

    maiac = (
        ee.ImageCollection(aq_cfg["dataset"])
        .filterDate(start_date, end_date)
        .select(aq_cfg["band"])
    )

    def to_aod(img):
        return img.multiply(scale_factor).copyProperties(img, ["system:time_start"])

    maiac_scaled = maiac.map(to_aod)

    bands = []
    band_names = []

    for t in thresholds:
        count_img = maiac_scaled.map(lambda img, t=t: img.gt(t)).sum()
        bands.append(count_img)
        band_names.append(f"aod_days_gt{str(t).replace('.', 'p')}")

    bands.append(maiac_scaled.mean())
    band_names.append("aod_mean")
    bands.append(maiac_scaled.max())
    band_names.append("aod_max")
    bands.append(maiac_scaled.count())
    band_names.append("aod_valid_obs")

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
            row["aod_window_start"] = start_date
            row["aod_window_end"] = end_date
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

    print("Extracting air quality (MODIS MAIAC AOD) — block level...")
    result = extract_airquality_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
