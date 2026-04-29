"""Block-level Indicator 3: Flood vulnerability from HAND + JRC Global Surface Water."""

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

INDICATOR_NAME = "flood_blocks"


def extract_flood_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute flood vulnerability zonal stats over each block polygon.

    Returns DataFrame with columns: block_id, hand_mean_m, hand_min_m,
    hand_flood_frac, jrc_max_extent_frac, jrc_recurrence_mean, coastal_lowland.
    """
    flood_cfg = config["flood"]
    blocks_cfg = config["blocks"]
    elev_cfg = config["elevation"]

    # HAND from MERIT Hydro
    hand_img = ee.Image(flood_cfg["hand"]["dataset"]).select(flood_cfg["hand"]["band"])
    hand_threshold = flood_cfg["hand"]["threshold_m"]
    hand_binary = hand_img.lte(hand_threshold).rename("hand_flood")

    # JRC Global Surface Water
    jrc = ee.Image(flood_cfg["jrc"]["dataset"])
    jrc_max = jrc.select("max_extent")
    jrc_rec = jrc.select("recurrence")

    # Elevation for coastal flag
    elev = ee.Image(elev_cfg["dataset"]).select(elev_cfg["band"])

    # Stack all bands that need a mean reducer into one image (1 getInfo call)
    stacked_mean = ee.Image.cat([
        hand_img.rename("hand_mean"),
        hand_binary.rename("hand_flood_frac"),
        jrc_max.rename("jrc_max_extent_frac"),
        jrc_rec.rename("jrc_recurrence_mean"),
        elev.rename("elev_for_coastal"),
    ])

    # HAND min needs a separate reducer (1 more getInfo call) = 2 total
    # vs 5 in the old version

    checkpoint_df = load_checkpoint(INDICATOR_NAME, config)
    remaining = filter_remaining_blocks(blocks_gdf, checkpoint_df,
                                        blocks_cfg["block_id_field"])

    coastal_cities = flood_cfg.get("coastal_cities", [])
    coastal_threshold = flood_cfg.get("coastal_threshold_m", 10)

    total = len(blocks_gdf)
    processed = total - len(remaining)
    t0 = time.time()

    for batch in batch_blocks(remaining, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        # Call 1: mean of all stacked bands
        mean_sampled = stacked_mean.reduceRegions(
            collection=fc, reducer=ee.Reducer.mean(), scale=30,
        )
        # Call 2: min of HAND only
        min_sampled = hand_img.reduceRegions(
            collection=fc, reducer=ee.Reducer.min(), scale=30,
        )

        mean_info = safe_getinfo(mean_sampled)
        min_info = safe_getinfo(min_sampled)

        mean_by_id = {f["properties"]["block_id"]: f["properties"]
                      for f in mean_info["features"]}
        min_by_id = {f["properties"]["block_id"]: f["properties"]
                     for f in min_info["features"]}

        city_map = batch.set_index(blocks_cfg["block_id_field"])["city"].to_dict()

        batch_rows = []
        for bid, mprops in mean_by_id.items():
            city = city_map.get(bid, "")
            mean_elev = mprops.get("elev_for_coastal")
            coastal_flag = (
                1 if (city in coastal_cities
                      and mean_elev is not None
                      and mean_elev < coastal_threshold)
                else 0
            )

            batch_rows.append({
                "block_id": bid,
                "hand_mean_m": mprops.get("hand_mean"),
                "hand_min_m": min_by_id.get(bid, {}).get("min"),
                "hand_flood_frac": mprops.get("hand_flood_frac"),
                "jrc_max_extent_frac": mprops.get("jrc_max_extent_frac"),
                "jrc_recurrence_mean": mprops.get("jrc_recurrence_mean"),
                "coastal_lowland": coastal_flag,
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

    print("Extracting flood vulnerability (HAND + JRC) — block level...")
    result = extract_flood_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, INDICATOR_NAME, config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
