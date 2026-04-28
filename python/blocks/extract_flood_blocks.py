"""Block-level Indicator 3: Flood vulnerability from HAND + JRC Global Surface Water."""

import ee
import pandas as pd

from utils_blocks import (
    load_blocks, blocks_to_fc, batch_blocks, save_block_output,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee


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

    # Binary flood-vulnerable mask: HAND <= threshold → 1
    hand_binary = hand_img.lte(hand_threshold).rename("hand_flood")

    # JRC Global Surface Water
    jrc = ee.Image(flood_cfg["jrc"]["dataset"])
    jrc_max = jrc.select("max_extent")
    jrc_rec = jrc.select("recurrence")

    # Elevation for coastal flag
    elev = ee.Image(elev_cfg["dataset"]).select(elev_cfg["band"])

    # Stack HAND bands
    hand_reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.min(), sharedInputs=True)
    )

    all_results = []
    total = len(blocks_gdf)
    processed = 0

    for batch in batch_blocks(blocks_gdf, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        # HAND continuous stats
        hand_sampled = hand_img.reduceRegions(
            collection=fc, reducer=hand_reducer, scale=30,
        )

        # HAND flood fraction (mean of binary mask)
        hand_frac_sampled = hand_binary.reduceRegions(
            collection=fc, reducer=ee.Reducer.mean(), scale=30,
        )

        # JRC max extent fraction (mean of binary)
        jrc_max_sampled = jrc_max.reduceRegions(
            collection=fc, reducer=ee.Reducer.mean(), scale=30,
        )

        # JRC recurrence mean
        jrc_rec_sampled = jrc_rec.reduceRegions(
            collection=fc, reducer=ee.Reducer.mean(), scale=30,
        )

        # Elevation mean (for coastal flag)
        elev_sampled = elev.reduceRegions(
            collection=fc, reducer=ee.Reducer.mean(), scale=30,
        )

        # Collect results from all reductions
        hand_feats = {f["properties"]["block_id"]: f["properties"]
                      for f in hand_sampled.getInfo()["features"]}
        hand_frac_feats = {f["properties"]["block_id"]: f["properties"]
                           for f in hand_frac_sampled.getInfo()["features"]}
        jrc_max_feats = {f["properties"]["block_id"]: f["properties"]
                         for f in jrc_max_sampled.getInfo()["features"]}
        jrc_rec_feats = {f["properties"]["block_id"]: f["properties"]
                         for f in jrc_rec_sampled.getInfo()["features"]}
        elev_feats = {f["properties"]["block_id"]: f["properties"]
                      for f in elev_sampled.getInfo()["features"]}

        coastal_cities = flood_cfg.get("coastal_cities", [])
        coastal_threshold = flood_cfg.get("coastal_threshold_m", 10)

        # Look up city for each block in this batch
        city_map = batch.set_index(blocks_cfg["block_id_field"])["city"].to_dict()

        for bid in hand_feats:
            city = city_map.get(bid, "")
            mean_elev = elev_feats.get(bid, {}).get("mean")
            coastal_flag = (
                1 if (city in coastal_cities
                      and mean_elev is not None
                      and mean_elev < coastal_threshold)
                else 0
            )

            all_results.append({
                "block_id": bid,
                "hand_mean_m": hand_feats[bid].get("mean"),
                "hand_min_m": hand_feats[bid].get("min"),
                "hand_flood_frac": hand_frac_feats.get(bid, {}).get("mean"),
                "jrc_max_extent_frac": jrc_max_feats.get(bid, {}).get("mean"),
                "jrc_recurrence_mean": jrc_rec_feats.get(bid, {}).get("mean"),
                "coastal_lowland": coastal_flag,
            })

        processed += len(batch)
        print(f"    {processed}/{total} blocks processed")

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    print("Extracting flood vulnerability (HAND + JRC) — block level...")
    result = extract_flood_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, "flood_blocks", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
