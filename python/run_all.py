"""Orchestrator: run all extraction steps and merge into a single output CSV.

Resumable at two levels:
  - Each indicator checkpoints every completed batch (see utils.safe_getinfo and
    the checkpoint helpers), so an interrupted indicator resumes mid-way.
  - This orchestrator skips any indicator whose output CSV already exists, so a
    rerun after a late failure does not redo the indicators that finished.
Pass --force to recompute everything from scratch.
"""

import argparse
from pathlib import Path

import pandas as pd

from utils import (
    load_config, init_gee, load_business_points, save_output,
    indicator_fingerprint, load_manifest, save_manifest, clear_checkpoint,
)

# Indicator name -> (banner, module, function). Order is the run order.
INDICATORS = [
    ("elevation",   "Indicator 1: Elevation (SRTM 30m)",
     "extract_elevation", "extract_elevation"),
    ("heat",        "Indicator 2: Extreme Heat Days (MODIS LST)",
     "extract_heat", "extract_heat"),
    ("flood",       "Indicator 3: Flood Vulnerability (HAND + JRC)",
     "extract_flood", "extract_flood"),
    ("canopy",      "Indicator 4: Tree Canopy Cover (ESA WorldCover 10m)",
     "extract_canopy", "extract_canopy"),
    ("rainfall",    "Indicator 5: Heavy Rainfall Days (CHIRPS Daily)",
     "extract_rainfall", "extract_rainfall"),
    ("airquality",  "Indicator 6: Air Quality (MODIS MAIAC AOD)",
     "extract_airquality", "extract_airquality"),
    ("nightlights", "Indicator 7: Nighttime Lights (VIIRS)",
     "extract_nightlights", "extract_nightlights"),
    ("builtup",     "Indicator 8: Built-up Surface Fraction (GHSL)",
     "extract_builtup", "extract_builtup"),
    ("population",  "Indicator 9: Population Density (WorldPop 100m)",
     "extract_population", "extract_population"),
    ("hrsl",        "Indicator 10: Population Density (Meta HRSL 31m)",
     "extract_hrsl", "extract_hrsl"),
]

# Carried into all_indicators.csv when present, beside the required five.
# cfi-map2r2-data joins on country + enterprise_id, not enterprise_id alone.
PASSTHROUGH_COLUMNS = ["country", "enterprise_id"]


def run_indicator(name, banner, module_name, func_name, df, config, force):
    """Run one indicator, reusing any still-valid cached rows.

    Three cases:
      - cache valid and complete        -> skip entirely
      - cache valid but missing rows    -> extract ONLY the missing businesses
                                           and append to the cached rows
      - cache stale (config changed) or -> recompute in full
        --force
    """
    print(f"\n=== {banner} ===")
    out_path = Path(__file__).parent.parent / config["output_dir"] / f"{name}.csv"

    fingerprint = indicator_fingerprint(name, config, df)
    manifest = load_manifest(config)
    entry = manifest.get(name) or {}

    cached = None
    if force:
        print("  --force: recomputing from scratch")
    elif not out_path.exists():
        pass
    elif entry.get("fingerprint") != fingerprint:
        # Settings that affect this indicator's VALUES changed, so cached rows
        # were produced under different semantics and cannot be mixed with new
        # ones. Drop the checkpoint too — its rows are stale for the same reason.
        why = ("no fingerprint recorded" if not entry
               else "config affecting this indicator changed")
        print(f"  Cache invalid ({why}) — recomputing all {len(df):,} rows")
    else:
        cached = pd.read_csv(out_path)
        cached["business_id"] = cached["business_id"].astype(str)
        # Drop cached rows for businesses no longer in the input.
        keep = cached["business_id"].isin(set(df["business_id"]))
        if (~keep).any():
            print(f"  Dropping {int((~keep).sum()):,} cached rows no longer in input")
            cached = cached[keep]

    if cached is None:
        clear_checkpoint(name, config)
        for radius in (config.get(name, {}) or {}).get("buffer_radii_m", []):
            clear_checkpoint(f"{name}_{radius}m", config)
        result = _extract(module_name, func_name, df, config)
    else:
        todo = df[~df["business_id"].isin(set(cached["business_id"]))]
        if todo.empty:
            print(f"  Skipping: all {len(df):,} businesses already extracted")
            return _ordered(cached, df)
        print(f"  Incremental: {len(todo):,} new of {len(df):,} "
              f"({len(cached):,} reused)")
        fresh = _extract(module_name, func_name, todo, config)
        result = pd.concat([cached, fresh], ignore_index=True)

    # A checkpoint left by an interrupted run over a different subset can carry
    # ids that are no longer in the input; never let those reach the output.
    result["business_id"] = result["business_id"].astype(str)
    result = result[result["business_id"].isin(set(df["business_id"]))]
    result = result.drop_duplicates(subset="business_id", keep="last")
    result = _ordered(result, df)

    save_output(result, name, config)
    manifest[name] = {"fingerprint": fingerprint, "rows": int(len(result))}
    save_manifest(manifest, config)
    return result


def _extract(module_name, func_name, frame, config):
    module = __import__(module_name)
    return getattr(module, func_name)(frame, config)


def _ordered(result, df):
    """Return result rows in the input's business_id order."""
    order = {b: i for i, b in enumerate(df["business_id"])}
    return (result.assign(_o=result["business_id"].map(order))
                  .sort_values("_o").drop(columns="_o").reset_index(drop=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Recompute every indicator, ignoring existing "
                             "output CSVs.")
    parser.add_argument("--only", help="Comma-separated indicator names to run "
                                       "(e.g. 'heat,rainfall').")
    args = parser.parse_args()

    config = load_config()
    init_gee(config)
    df = load_business_points(config)

    wanted = ([s.strip() for s in args.only.split(",")] if args.only
              else [name for name, *_ in INDICATORS])
    unknown = [w for w in wanted if w not in {n for n, *_ in INDICATORS}]
    if unknown:
        raise SystemExit(f"Unknown indicator(s): {unknown}")

    results = {}
    for name, banner, module_name, func_name in INDICATORS:
        if name not in wanted:
            continue
        results[name] = run_indicator(
            name, banner, module_name, func_name, df, config, args.force)

    if len(results) < len(INDICATORS):
        print(f"\nRan {len(results)} of {len(INDICATORS)} indicators; "
              f"skipping the merge.")
        return

    # --- Merge all indicators ---
    print("\n=== Merging all indicators ===")
    keep = ["business_id", "latitude", "longitude", "fieldwork_date", "city"]
    keep += [c for c in PASSTHROUGH_COLUMNS if c in df.columns]
    merged = df[keep].copy()
    merged["fieldwork_date"] = merged["fieldwork_date"].dt.strftime("%Y-%m-%d")

    for name, *_ in INDICATORS:
        indicator_df = results[name]
        before = len(merged)
        merged = merged.merge(indicator_df, on="business_id", how="left")
        if len(merged) != before:
            raise RuntimeError(
                f"Merging '{name}' changed the row count {before:,} -> "
                f"{len(merged):,}; its business_id values are not unique.")

    save_output(merged, "all_indicators", config)

    print(f"\nFinal dataset: {merged.shape[0]:,} rows x {merged.shape[1]} columns")
    missing = merged.isna().sum()
    missing = missing[missing > 0]
    if len(missing):
        print("Columns with missing values:")
        print(missing.to_string())
    print("\nAll done.")


if __name__ == "__main__":
    main()
