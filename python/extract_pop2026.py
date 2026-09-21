"""Indicator 14: Population density from WorldPop R2025A (Global2), year 2026.

A second, independent population estimate beside indicator 9 (WorldPop Global1
2020) and indicator 10 (Meta HRSL). See the `pop2026` block in config.yaml for
why all three exist and why this one is not a newer version of indicator 9.

Unlike every other extractor here this one does NOT call Google Earth Engine:
R2025A is published only as per-country downloads. The zonal maths lives in
`worldpop2026.py`, shared with the block pipeline.
"""

import pandas as pd

from utils import (
    load_config, load_business_points, save_output,
    load_checkpoint, append_checkpoint, filter_remaining_points,
    finish_indicator, BatchProgress,
)
from worldpop2026 import density_for_points

INDICATOR_NAME = "pop2026"

# Points per checkpointed chunk. There is no GEE request to batch here, so this
# is purely about how much work an interrupted run has to redo.
CHUNK = 2000


def _extract_at_radius(df: pd.DataFrame, radius: int, config: dict) -> pd.DataFrame:
    suffix = f"{radius}m"
    indicator_name = f"{INDICATOR_NAME}_{suffix}"
    col = f"pop2026_density_{suffix}"

    remaining = filter_remaining_points(
        df, load_checkpoint(indicator_name, config))
    progress = BatchProgress(len(remaining), label=f"{suffix} ")

    # Group by city first: each city opens one national raster and reads only
    # the window covering its points.
    for city, city_df in remaining.groupby("city"):
        for start in range(0, len(city_df), CHUNK):
            chunk = city_df.iloc[start:start + CHUNK]
            values = density_for_points(chunk, radius, config)
            append_checkpoint(
                [{"business_id": bid, col: None if pd.isna(v) else float(v)}
                 for bid, v in zip(chunk["business_id"], values)],
                indicator_name, config)
            progress.update(len(chunk))

    return finish_indicator(indicator_name, config)


def extract_pop2026(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Population density at each configured buffer radius."""
    result = df[["business_id"]].copy()
    for radius in config["pop2026"]["buffer_radii_m"]:
        part = _extract_at_radius(df, radius, config)
        result = result.merge(part, on="business_id", how="left")
    return result


def main():
    config = load_config()
    df = load_business_points(config)
    out = extract_pop2026(df, config)
    save_output(out, INDICATOR_NAME, config)
    print(out.describe().to_string())


if __name__ == "__main__":
    main()
