"""Block-level orchestrator: zonal statistics over the sampling-grid polygons.

One module replaces the eight `extract_*_blocks.py` files it supersedes. Each
indicator is a spec in block_indicators.py that returns a GEE image; this loop
reduces that image with a zonal mean over every block, checkpointing per batch.

Design notes that matter for cost:
  - The image is built ONCE PER CITY, not once per batch. Rebuilding a
    collection reduction per batch was what made the point pipeline's heat
    indicator ~40x slower than it needed to be.
  - filterBounds is applied per city before any mosaic, for the same reason the
    point pipeline needs it: without it, tiled collections mosaic globally.
  - Each indicator reduces at its own NATIVE scale (BLOCK_SCALES); reducing
    finer inflates any pixelArea-based density.

    cd python/blocks && python3 run_all_blocks.py
    python3 run_all_blocks.py --only canopy,buildings   # subset
    python3 run_all_blocks.py --force                   # ignore caches
"""

import argparse
import sys
from pathlib import Path

import ee
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import load_config, init_gee                          # noqa: E402
from utils import indicator_fingerprint, load_manifest, save_manifest  # noqa: E402
from utils_blocks import (                                       # noqa: E402
    load_blocks, batch_blocks, save_block_output, safe_getinfo,
    load_checkpoint, append_checkpoint, clear_checkpoint,
)
from block_indicators import (                                   # noqa: E402
    BLOCK_INDICATORS, BLOCK_CONFIG_KEYS, block_scale,
)


def _block_features(batch, block_id_field):
    return ee.FeatureCollection([
        ee.Feature(ee.Geometry(row.geometry.__geo_interface__),
                   {"block_id": str(row[block_id_field])})
        for _, row in batch.iterrows()])


def extract_indicator(name, blocks_gdf, config, force=False):
    """Zonal-mean one indicator over every block, resuming from checkpoint."""
    builder, columns = BLOCK_INDICATORS[name]
    scale = block_scale(name, config)
    block_id_field = config["blocks"]["block_id_field"]
    # Indicators whose cost is dominated by the collection reduction want far
    # fewer, much larger requests - see the config comment.
    batch_size = (config["blocks"].get("batch_size_overrides") or {}).get(
        name, config["blocks"]["batch_size"])
    timeout = (config["blocks"].get("getinfo_timeout_overrides") or {}).get(name)
    checkpoint_name = f"{name}_blocks"

    if force:
        # Without this, --force after a config change keeps the stale rows
        # already in the checkpoint and merges them with newly-computed ones.
        clear_checkpoint(checkpoint_name, config)
    done = load_checkpoint(checkpoint_name, config)
    remaining = blocks_gdf
    if done is not None and not done.empty:
        remaining = blocks_gdf[~blocks_gdf[block_id_field]
                               .astype(str).isin(set(done["block_id"].astype(str)))]
        print(f"  resuming: {len(remaining):,} of {len(blocks_gdf):,} blocks left")

    total = len(remaining)
    processed = 0
    for city, city_blocks in remaining.groupby("city"):
        bounds = ee.Geometry.Rectangle(list(city_blocks.total_bounds))
        image = builder(config, bounds)          # built ONCE per city
        print(f"  {city}: {len(city_blocks):,} blocks", flush=True)

        for batch in batch_blocks(city_blocks, batch_size):
            fc = _block_features(batch, block_id_field)
            sampled = image.reduceRegions(
                collection=fc, reducer=ee.Reducer.mean(), scale=scale)

            rows = []
            got = (safe_getinfo(sampled, timeout=timeout) if timeout
                   else safe_getinfo(sampled))
            for f in got["features"]:
                props = f["properties"]
                row = {"block_id": props["block_id"]}
                for col in columns:
                    # A single-band image names the reduced property "mean";
                    # multi-band images use the band names.
                    row[col] = props.get(col if len(columns) > 1 else "mean")
                rows.append(row)

            append_checkpoint(rows, checkpoint_name, config)
            processed += len(batch)
            if processed % (batch_size * 10) == 0 or processed == total:
                print(f"    {processed:,}/{total:,} "
                      f"({100*processed/total:.1f}%)", flush=True)

    result = load_checkpoint(checkpoint_name, config, verbose=False)
    # NB: the checkpoint is deliberately NOT cleared here. main() clears it only
    # after save_block_output succeeds, so a failed write after a multi-hour run
    # does not destroy the work.
    return result if result is not None else pd.DataFrame()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Comma-separated indicators to run.")
    parser.add_argument("--force", action="store_true",
                        help="Ignore existing per-indicator outputs.")
    args = parser.parse_args()

    config = load_config()
    init_gee(config)

    wanted = ([s.strip() for s in args.only.split(",")] if args.only
              else config["blocks"]["indicators"])
    unknown = [w for w in wanted if w not in BLOCK_INDICATORS]
    if unknown:
        raise SystemExit(f"Unknown indicator(s): {unknown}. "
                         f"Known: {sorted(BLOCK_INDICATORS)}")

    blocks = load_blocks(config)
    out_dir = Path(__file__).resolve().parent.parent.parent / config["blocks"]["output_dir"]
    id_field = config["blocks"]["block_id_field"]

    # Cached per-indicator CSVs are reused only while the config that produced
    # them is unchanged — a row-count check alone would happily reuse output
    # computed under a different analysis window or dataset.
    block_config = dict(config)
    block_config["output_dir"] = config["blocks"]["output_dir"]
    fingerprints = {n: indicator_fingerprint(n, config, keys=BLOCK_CONFIG_KEYS[n])
                    for n in BLOCK_INDICATORS}
    manifest = load_manifest(block_config)

    results = {}
    for i, name in enumerate(wanted, 1):
        print(f"\n=== Block indicator {i}/{len(wanted)}: {name} ===")
        path = out_dir / f"{name}_blocks.csv"
        stale = manifest.get(name, {}).get("fingerprint") != fingerprints[name]
        if path.exists() and not args.force and stale:
            print(f"  Cache invalid (config affecting this indicator changed) "
                  f"— recomputing")
        if path.exists() and not args.force and not stale:
            cached = pd.read_csv(path, dtype={"block_id": str})
            if len(cached) == len(blocks):
                print(f"  Skipping: {path.name} already has all "
                      f"{len(cached):,} blocks (--force to recompute)")
                results[name] = cached
                continue
            print(f"  {path.name} has {len(cached):,} of {len(blocks):,} "
                  f"blocks — recomputing")
        results[name] = extract_indicator(name, blocks, config, args.force)
        save_block_output(results[name], f"{name}_blocks", config)
        clear_checkpoint(f"{name}_blocks", config)   # only once safely on disk
        manifest[name] = {"fingerprint": fingerprints[name],
                          "rows": int(len(results[name]))}
        save_manifest(manifest, config)

    if set(results) != set(config["blocks"]["indicators"]):
        # A partial --only run must not rewrite all_block_indicators.csv: doing
        # so silently drops every column it did not just compute.
        print(f"\nRan {len(results)} of "
              f"{len(config['blocks']['indicators'])} configured indicators; "
              f"skipping the merge so all_block_indicators.csv is not "
              f"overwritten with a partial set.")
        return

    print("\n=== Merging block indicators ===")
    # Output BOTH ids. `block_id` is the RAW grid id so the file merges directly
    # onto final_sampling_grid_2026.geojson and enum_data's BlockID; `block_uid`
    # is the city-prefixed key that is unique on its own.
    #
    # MERGE ON city + block_id, NOT block_id alone: raw grid ids restart at 1 in
    # every city, so a bare join fans rows out — the same trap as the business
    # frame's country + enterprise_id.
    merged = blocks[[id_field, "block_id_raw", "city"]].rename(
        columns={id_field: "block_uid", "block_id_raw": "block_id"})
    merged["block_uid"] = merged["block_uid"].astype(str)
    merged["block_id"] = merged["block_id"].astype(str)
    for name, df in results.items():
        if df.empty or "block_id" not in df.columns:
            raise RuntimeError(
                f"Indicator '{name}' produced no rows; cannot merge. Check the "
                f"run log above for its failure.")
        df = df.copy()
        # Per-indicator CSVs carry the prefixed id; join on that, then present
        # the raw id to the caller.
        df = df.rename(columns={"block_id": "block_uid"})
        df["block_uid"] = df["block_uid"].astype(str)
        df = df.drop_duplicates(subset="block_uid", keep="last")
        before = len(merged)
        merged = merged.merge(df, on="block_uid", how="left")
        if len(merged) != before:
            raise RuntimeError(
                f"Merging '{name}' changed the row count {before:,} -> "
                f"{len(merged):,}; its block_id values are not unique.")

    merged = add_block_heat_index(merged, config)
    lead = ["block_id", "block_uid", "city"]
    merged = merged[lead + [c for c in merged.columns if c not in lead]]
    save_block_output(merged, "all_block_indicators", config)
    print(f"\nFinal block dataset: {merged.shape[0]:,} rows x "
          f"{merged.shape[1]} columns")
    missing = merged.isna().sum()
    missing = missing[missing > 0]
    if len(missing):
        print("Columns with missing values:")
        print(missing.to_string())
    print("\nAll done.")


def add_block_heat_index(merged, config):
    """Within-city heat exposure index, the block analogue of the business one.

    ALL THREE components are required. If any is absent the column is not
    written at all, rather than being built from whatever is present: an index
    missing its heat term is not the same quantity as one that has it, and
    emitting both under one name would be worse than emitting neither. This
    mirrors utils.add_heat_exposure_index, which NaNs rows with any missing
    component for the same reason.

    NOT numerically identical to the business-level index: blocks extract
    lst_max_c but not lst_mean_c, so this is a three-component analogue.
    """
    components = {"lst_max_c": 1, "builtup_fraction": 1, "canopy_fraction": -1}
    missing = [c for c in components if c not in merged.columns]
    if missing:
        print(f"  heat_exposure_index not written; missing components: {missing}")
        return merged

    out = merged.copy()
    complete = out[list(components)].notna().all(axis=1)
    zs = []
    for col, sign in components.items():
        values = out[col].where(complete)
        grouped = values.groupby(out["city"])
        spread = grouped.transform("std")
        zs.append(sign * ((values - grouped.transform("mean"))
                          / spread.where(spread > 0)))
    out["heat_exposure_index"] = pd.concat(zs, axis=1).mean(axis=1).where(complete)
    return out


if __name__ == "__main__":
    main()
