"""Block-level Indicator 8: Built-up surface fraction from JRC GHSL."""

import ee
import pandas as pd

from utils_blocks import (
    load_blocks, blocks_to_fc, batch_blocks, save_block_output,
)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, init_gee


def extract_builtup_blocks(blocks_gdf, config: dict) -> pd.DataFrame:
    """Compute mean built-up surface fraction over each block polygon.

    Returns DataFrame with columns: block_id, builtup_fraction,
    builtup_pixel_count.
    """
    bu_cfg = config["builtup"]
    blocks_cfg = config["blocks"]

    ghsl = ee.Image(bu_cfg["dataset"]).select(bu_cfg["band"])
    # GHSL built_surface is 0-100 percentage; normalise to 0-1
    ghsl_frac = ghsl.divide(100)

    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.count(), sharedInputs=True)
    )

    all_results = []
    total = len(blocks_gdf)
    processed = 0

    for batch in batch_blocks(blocks_gdf, blocks_cfg["batch_size"]):
        fc = blocks_to_fc(batch, blocks_cfg["block_id_field"])

        sampled = ghsl_frac.reduceRegions(
            collection=fc,
            reducer=reducer,
            scale=bu_cfg.get("scale_m", 10),
        )

        for f in sampled.getInfo()["features"]:
            props = f["properties"]
            all_results.append({
                "block_id": props["block_id"],
                "builtup_fraction": props.get("mean"),
                "builtup_pixel_count": props.get("count"),
            })

        processed += len(batch)
        print(f"    {processed}/{total} blocks processed")

    return pd.DataFrame(all_results)


def main():
    config = load_config()
    init_gee(config)

    print("Loading block polygons...")
    blocks_gdf = load_blocks(config)

    print("Extracting built-up surface fraction (GHSL) — block level...")
    result = extract_builtup_blocks(blocks_gdf, config)

    city_lookup = blocks_gdf.set_index(config["blocks"]["block_id_field"])["city"]
    result["city"] = result["block_id"].map(city_lookup)

    save_block_output(result, "builtup_blocks", config)
    print("Done.")
    return result


if __name__ == "__main__":
    main()
