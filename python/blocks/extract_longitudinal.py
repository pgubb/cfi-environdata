"""Longitudinal block indicators: each metric over successive 45-day periods.

The static block table answers "where"; this answers "when". Same blocks, same
two-year window, but each indicator computed over successive fixed-length
periods so seasonal variation is visible.

The reason it is affordable: rather than one run per period, each indicator is
assembled into a SINGLE multi-band image whose bands are (metric x period), and
one reduceRegions per block batch returns every period at once. Total
server-side work is roughly unchanged — summing 730 days costs about what
summing 16 chunks of 45 days costs — so this runs in the same order of time as
the static pipeline rather than 16x it.

    cd python/blocks && python3 extract_longitudinal.py
    python3 extract_longitudinal.py --only rainfall,airquality
"""

import argparse
import sys
from pathlib import Path

import ee
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import load_config, init_gee                             # noqa: E402
from utils_blocks import (                                          # noqa: E402
    load_blocks, batch_blocks, save_block_output, safe_getinfo,
    load_checkpoint, append_checkpoint, clear_checkpoint,
)
from longitudinal_indicators import LONGITUDINAL_INDICATORS         # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def build_periods(config):
    """Successive fixed-length periods spanning the shared analysis window.

    Only WHOLE periods are emitted. 730 days at 45 gives 16 periods covering 720
    days; the 10-day remainder is dropped rather than kept as a short period
    whose sums and counts would not be comparable with the others.
    """
    tw = config["time_window"]["analysis_end_date"]
    days = config["blocks_longitudinal"]["period_days"]
    trailing = config["heat"]["trailing_years"]
    end = pd.Timestamp(tw)
    start = end - pd.DateOffset(years=trailing)

    periods, cursor = [], start
    while cursor + pd.Timedelta(days=days) <= end:
        periods.append((cursor, cursor + pd.Timedelta(days=days)))
        cursor += pd.Timedelta(days=days)
    return periods


def extract_indicator(name, blocks_gdf, periods, config):
    """All periods of one indicator, as one long-format frame."""
    builder, metrics, native_scale = LONGITUDINAL_INDICATORS[name]
    # CAP THE REDUCTION SCALE AT THE BLOCK SIZE. reduceRegions evaluates at the
    # requested scale, so when that scale is coarser than the polygon no pixel
    # centre falls inside and EVERY block returns null. Blocks are ~149m across
    # while CHIRPS is 5,566m and ERA5-Land 11,132m — 37x and 74x wider — so both
    # came back entirely empty before this cap. Reducing finer also handles
    # blocks straddling a pixel boundary, which the containing-pixel value
    # misses. Safe here because every metric is a MEAN or a per-pixel temporal
    # statistic, never a pixelArea-derived density (which would be distorted by
    # changing scale).
    scale = min(native_scale, config["blocks_longitudinal"].get(
        "max_reduce_scale_m", 100))
    blk = config["blocks"]
    lon = config["blocks_longitudinal"]
    id_field = blk["block_id_field"]
    batch_size = (lon.get("batch_size_overrides") or {}).get(
        name, blk["batch_size"])
    timeout = (lon.get("getinfo_timeout_overrides") or {}).get(name)
    checkpoint = f"long_{name}_blocks"

    done = load_checkpoint(checkpoint, config)
    remaining = blocks_gdf
    if done is not None and not done.empty:
        seen = set(done["block_id"].astype(str))
        remaining = blocks_gdf[~blocks_gdf[id_field].astype(str).isin(seen)]
        print(f"  resuming: {len(remaining):,} of {len(blocks_gdf):,} blocks left")

    processed, total = 0, len(remaining)
    for city, city_blocks in remaining.groupby("city"):
        bounds = ee.Geometry.Rectangle(list(city_blocks.total_bounds))
        # (metric x period) bands in one image, built ONCE per city.
        layers, names = [], []
        for i, (s, e) in enumerate(periods):
            img = builder(config, bounds,
                          s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"))
            period_names = [f"{m}__p{i:02d}" for m in metrics]
            layers.append(img.rename(period_names))
            names.extend(period_names)
        stacked = ee.Image.cat(layers)
        print(f"  {city}: {len(city_blocks):,} blocks x {len(periods)} periods "
              f"({len(names)} bands)", flush=True)

        for batch in batch_blocks(city_blocks, batch_size):
            fc = ee.FeatureCollection([
                ee.Feature(ee.Geometry(row.geometry.__geo_interface__),
                           {"block_id": str(row[id_field])})
                for _, row in batch.iterrows()])
            sampled = stacked.reduceRegions(
                collection=fc, reducer=ee.Reducer.mean(), scale=scale)
            got = (safe_getinfo(sampled, timeout=timeout) if timeout
                   else safe_getinfo(sampled))

            rows = []
            for f in got["features"]:
                props = f["properties"]
                for i in range(len(periods)):
                    row = {"block_id": props["block_id"], "period_index": i}
                    for m in metrics:
                        row[m] = props.get(f"{m}__p{i:02d}")
                    rows.append(row)
            append_checkpoint(rows, checkpoint, config)
            processed += len(batch)
            if processed % (batch_size * 5) == 0 or processed == total:
                print(f"    {processed:,}/{total:,} "
                      f"({100*processed/total:.1f}%)", flush=True)

    result = load_checkpoint(checkpoint, config, verbose=False)
    return (result if result is not None else pd.DataFrame()), checkpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Comma-separated indicators to run.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config = load_config()
    init_gee(config)
    lon = config["blocks_longitudinal"]

    wanted = ([s.strip() for s in args.only.split(",")] if args.only
              else lon["indicators"])
    unknown = [w for w in wanted if w not in LONGITUDINAL_INDICATORS]
    if unknown:
        raise SystemExit(f"Unknown indicator(s): {unknown}. "
                         f"Known: {sorted(LONGITUDINAL_INDICATORS)}")

    periods = build_periods(config)
    days = lon["period_days"]
    print(f"{len(periods)} periods of {days} days: "
          f"{periods[0][0].date()} to {periods[-1][1].date()}")
    covered = len(periods) * days
    window = (periods[-1][1] - periods[0][0]).days
    total_window = (pd.Timestamp(config["time_window"]["analysis_end_date"])
                    - periods[0][0]).days
    if total_window > covered:
        print(f"  ({total_window - covered}-day tail dropped: only whole "
              f"periods are emitted)")

    blocks = load_blocks(config)
    out_dir = REPO_ROOT / config["blocks"]["output_dir"]

    frames, checkpoints = {}, {}
    for i, name in enumerate(wanted, 1):
        print(f"\n=== Longitudinal {i}/{len(wanted)}: {name} ===")
        path = out_dir / f"long_{name}_blocks.csv"
        expected = len(blocks) * len(periods)
        if path.exists() and not args.force:
            cached = pd.read_csv(path, dtype={"block_id": str})
            if len(cached) == expected:
                print(f"  Skipping: already has all {expected:,} "
                      f"block-periods (--force to recompute)")
                frames[name] = cached
                continue
        if args.force:
            clear_checkpoint(f"long_{name}_blocks", config)
        frames[name], checkpoints[name] = extract_indicator(
            name, blocks, periods, config)
        save_block_output(frames[name], f"long_{name}_blocks", config)
        clear_checkpoint(checkpoints[name], config)   # only once safely saved

    if set(frames) != set(lon["indicators"]):
        print(f"\nRan {len(frames)} of {len(lon['indicators'])} indicators; "
              f"skipping the merge so the combined file is not overwritten "
              f"with a partial set.")
        return

    print("\n=== Merging longitudinal indicators ===")
    period_lookup = pd.DataFrame({
        "period_index": range(len(periods)),
        "period_start": [s.strftime("%Y-%m-%d") for s, _ in periods],
        "period_end": [e.strftime("%Y-%m-%d") for _, e in periods],
    })
    id_field = config["blocks"]["block_id_field"]
    spine = blocks[[id_field, "block_id_raw", "city"]].rename(
        columns={id_field: "block_uid", "block_id_raw": "block_id"})
    spine["block_uid"] = spine["block_uid"].astype(str)
    merged = spine.merge(period_lookup, how="cross")

    for name, df in frames.items():
        df = df.copy().rename(columns={"block_id": "block_uid"})
        df["block_uid"] = df["block_uid"].astype(str)
        df = df.drop_duplicates(subset=["block_uid", "period_index"], keep="last")
        before = len(merged)
        merged = merged.merge(df, on=["block_uid", "period_index"], how="left")
        if len(merged) != before:
            raise RuntimeError(
                f"Merging '{name}' changed the row count {before:,} -> "
                f"{len(merged):,}; its (block, period) keys are not unique.")

    lead = ["block_id", "block_uid", "city", "period_index",
            "period_start", "period_end"]
    merged = merged[lead + [c for c in merged.columns if c not in lead]]
    merged = merged.sort_values(["city", "block_uid", "period_index"])

    save_block_output(merged, lon["output_file"].replace(".csv", ""), config)
    print(f"\nFinal longitudinal dataset: {merged.shape[0]:,} rows x "
          f"{merged.shape[1]} columns "
          f"({len(blocks):,} blocks x {len(periods)} periods)")
    missing = merged.isna().sum()
    missing = missing[missing > 0]
    if len(missing):
        print("Columns with missing values:")
        print(missing.to_string())
    print("\nAll done.")


if __name__ == "__main__":
    main()
