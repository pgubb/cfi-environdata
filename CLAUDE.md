# CLAUDE.md

## Project overview

`cfi-environdata` is a Python utility that extracts remote-sensing environmental indicators from Google Earth Engine (GEE) for business GPS locations across five emerging market cities (Sao Paulo, Addis Ababa, Delhi, Jakarta, Lagos) as part of the CFI MAP2 Round 2 study of micro and small enterprises.

The utility has two pipelines:
1. **Point-level**: Extracts indicators at individual business GPS coordinates → `data/output/all_indicators.csv` (consumed by `cfi-map2r2-data`)
2. **Block-level**: Computes zonal statistics over sampling frame block polygons → `data/output/blocks/all_block_indicators.csv` (for study-area-level spatial analysis)

## Architecture

- **Language**: Python 3.12 (miniconda base environment at `/opt/miniconda3/bin/python`)
- **GEE project**: `ee-geogrids`
- **Config**: All parameters (thresholds, buffer radii, dataset IDs, batch sizes) are in `config.yaml`
- **Input**: CSV with columns `business_id`, `latitude`, `longitude`, `fieldwork_date`, `city`
- **Output**: Per-indicator CSVs + merged `all_indicators.csv` in `data/output/`

## File structure

```
config.yaml                  # All configurable parameters
requirements.txt             # earthengine-api, pandas, geopandas, pyyaml
python/
  utils.py                   # GEE auth, coordinate loading, batching, export
  prepare_gsmm_input.py      # Ingest: GSMM listing exports -> data/input/gsmm_listings.csv
  extract_elevation.py       # Indicator 1: SRTM 30m
  extract_heat.py            # Indicator 2: MODIS LST (per fieldwork_date)
  extract_flood.py           # Indicator 3: MERIT Hydro HAND + JRC surface water
  extract_canopy.py          # Indicator 4: ESA WorldCover 10m (50m + 150m buffers)
  extract_rainfall.py        # Indicator 5: CHIRPS daily (per city)
  extract_airquality.py      # Indicator 6: MODIS MAIAC AOD (per city)
  extract_nightlights.py     # Indicator 7: VIIRS monthly (per fieldwork_date)
  extract_builtup.py         # Indicator 8: JRC GHSL 10m (50m + 150m buffers)
  extract_population.py      # Indicator 9: WorldPop 100m density (50m + 150m buffers)
  extract_hrsl.py            # Indicator 10: Meta HRSL 31m density (50m + 150m buffers)
  run_all.py                 # Orchestrator: runs all 10 + merges
  blocks/                    # Block-level aggregation pipeline
    utils_blocks.py          # Block polygon loading, GeoJSON→FC, batching
    extract_*_blocks.py      # Per-indicator zonal extraction (the first 8 indicators)
    run_all_blocks.py        # Block pipeline orchestrator
data/
  input/                     # Business coordinate CSVs
  input/blocks/              # Sampling frame GeoJSON files (from blockexplorer repo)
  output/                    # Point-level indicator CSVs + data_dictionary.md
  output/blocks/             # Block-level indicator CSVs + block_data_dictionary.md
inspect_indicators.ipynb     # Jupyter notebook for visual inspection (geemap)
plan.md                      # Implementation plan with design decisions
```

## Running the pipelines

**Point-level** (business GPS coordinates). Refresh the input from the latest
GSMM listing exports first, then extract:
```bash
cd python
python3 prepare_gsmm_input.py   # rebuilds data/input/gsmm_listings.csv
python3 run_all.py
```

`run_all.py` is **incremental**: a rerun extracts only businesses not already in
each indicator's output CSV, reusing the rest. Adding a city (or a newer GSMM
extract with more listings) costs only the new businesses, not the whole frame.

Reuse is gated on a **config fingerprint** per indicator, recorded in
`data/output/extraction_manifest.json`. When settings that affect an indicator's
*values* change, its cache and checkpoint are discarded and it recomputes in
full — so a file can never end up holding rows computed under two different
definitions. Performance-only keys (`batch_size`, `getinfo_timeout_sec`) are
excluded from the fingerprint, so tuning them does not force a rerun.

Within an indicator, each completed batch is checkpointed, so an interrupted run
also resumes mid-way. Useful flags:

```bash
python3 run_all.py --force              # ignore all caches, recompute everything
python3 run_all.py --only heat,rainfall # run a subset (skips the merge)
```

**Block-level** (sampling frame polygons):
```bash
cd python/blocks
python3 run_all_blocks.py
```

Each `extract_*.py` can also be run standalone. The working directory must be `python/` (or `python/blocks/` for block scripts) for relative imports to resolve.

## Key patterns

- **Batching**: All extraction scripts batch GEE API calls via `utils.batch_points()` (default 50 points per call) to avoid GEE memory limits.
- **GEE resilience**: Never call `.getInfo()` directly — use `utils.safe_getinfo()`, which adds a 300s client-side timeout (a stalled GEE `getInfo()` otherwise blocks forever) and 3 retries with exponential backoff. Every indicator appends each completed batch to `data/output/.checkpoint_{indicator}.csv` via `append_checkpoint()` and filters already-done points with `filter_remaining_points()`, then calls `finish_indicator()` to read the results back and delete the checkpoint. Buffer-based indicators (canopy, built-up) checkpoint per radius, e.g. `canopy_50m`. The same helpers exist in `blocks/utils_blocks.py` for the block pipeline; the two copies should stay in step.
- **Grouping strategy**: Time-series indicators (heat, nightlights) group by `fieldwork_date` to reuse the same image collection. Coarse-resolution indicators (rainfall at 5.5km, AOD at 1km) group by `city` instead for efficiency.
- **Buffer-based indicators**: Canopy and built-up compute zonal stats within circular buffers (50m, 150m). Nightlights use a 150m buffer. All others are point samples.
- **Column naming**: Buffer-dependent columns include the radius suffix (e.g., `canopy_fraction_50m`, `builtup_fraction_150m`).
- **GSMM ingestion**: `prepare_gsmm_input.py` reads the "Business Data" sheet of the latest export per country from `../cfi-map2r2-data/data/gsmm/`. File choice is by kind first, then date — a country team's cleaned `GSMM_Analysis_*` export beats the vendor's daily `GSMM_Report_*` even when the Report is newer (ported from `gsmm_snapshot_path()` in that repo's `R/prep_cto.R`). Enterprise IDs are unique only *within* a country, so `business_id` is emitted as `<Country>_<Enterprise ID>`, with `country` and `enterprise_id` kept as columns for the join back onto `enum_data`. `fieldwork_date` is the listing date, which arrives either as an Excel serial (Analysis workbooks) or an ISO datetime (vendor exports).
- **Population sources**: indicators 9 (WorldPop) and 10 (Meta HRSL) measure the same construct by different methods. They rank neighbourhoods similarly *within* a city (r = 0.73–0.95) but disagree sharply on level (Addis Ababa 12,326 vs 26,486 people/km²), so neither supports absolute or cross-city density claims. Both are extracted deliberately as a sensitivity check. **HRSL is the better default**: it has no missing values (WorldPop has 101 gaps on the North Jakarta coast that HRSL shows are densely populated) and is uncorrelated with `builtup_fraction` (r = -0.05 vs WorldPop's 0.41). Never put both in one model. HRSL is a **community-catalog** asset (`projects/sat-io/...`), the pipeline's only third-party dependency.
- **Cross-city day-counts need the rate columns.** `heat_days_gt*` and `aod_days_gt*` count exceedances among *observed* days, and cloud cover makes that denominator range 404–40 (LST) and 347–91 (AOD) across cities. `run_all.py` derives `*_frac_gt*` companions (`utils.add_exceedance_rates`) — always compare on those. Using raw AOD counts reverses the city ranking, putting Lagos last on air pollution when the rate puts it first. Rainfall needs no rate (CHIRPS is gap-filled, `rain_valid_obs` = 730 everywhere).
- **Density conversions must reduce at the source's native scale.** These datasets store a count per cell; `ee.Image.pixelArea()` reports area at the *requested* scale, so reducing finer than native inflates density (WorldPop at 30m vs 93m: 9.4x too high).
- **Coordinates are sensitive**: `data/input/gsmm_listings.csv` holds exact business locations and is git-ignored. `data/input/` is otherwise tracked, so never remove that rule, and never copy the file into `cfi-map2r2-data`. Only the derived indicators are safe to share back.
- **Block pipeline**: Uses the same GEE datasets and config but operates on polygon geometries with zonal reductions (`reduceRegions` with `ee.Reducer.mean`). No buffers or fieldwork dates — blocks use a fixed analysis period and the polygon itself as the analysis unit. Block IDs are prefixed with city name for uniqueness.

## Related repos

- `cfi-map2r2-data` — R analysis pipeline (fixest, ggplot2) that consumes the output CSV
- `cfi-map2-blockexplorer2026` — Shiny app with sampling grid GeoJSONs (source for synthetic test coordinates)

## Conventions

- Config changes go in `config.yaml`, not hardcoded in scripts
- GEE dataset IDs and band names are always in config, not in code
- New indicators follow the pattern: `extract_{name}.py` with a `extract_{name}(df, config)` function and a `main()` entrypoint
- The data dictionary (`data/output/data_dictionary.md`) must be updated when columns are added or changed
