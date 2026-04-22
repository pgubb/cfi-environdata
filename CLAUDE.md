# CLAUDE.md

## Project overview

`cfi-environdata` is a Python utility that extracts remote-sensing environmental indicators from Google Earth Engine (GEE) for business GPS locations across five emerging market cities (Sao Paulo, Addis Ababa, Delhi, Jakarta, Lagos) as part of the CFI MAP2 Round 2 study of micro and small enterprises.

The utility outputs a single CSV (`data/output/all_indicators.csv`) that is consumed downstream by the R analysis pipeline in `cfi-map2r2-data`.

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
  extract_elevation.py       # Indicator 1: SRTM 30m
  extract_heat.py            # Indicator 2: MODIS LST (per fieldwork_date)
  extract_flood.py           # Indicator 3: MERIT Hydro HAND + JRC surface water
  extract_canopy.py          # Indicator 4: ESA WorldCover 10m (50m + 150m buffers)
  extract_rainfall.py        # Indicator 5: CHIRPS daily (per city)
  extract_airquality.py      # Indicator 6: MODIS MAIAC AOD (per city)
  extract_nightlights.py     # Indicator 7: VIIRS monthly (per fieldwork_date)
  extract_builtup.py         # Indicator 8: JRC GHSL 10m (50m + 150m buffers)
  run_all.py                 # Orchestrator: runs all 8 + merges
data/
  input/                     # Business coordinate CSVs
  output/                    # Extracted indicator CSVs + data_dictionary.md
inspect_indicators.ipynb     # Jupyter notebook for visual inspection (geemap)
plan.md                      # Implementation plan with design decisions
```

## Running the pipeline

```bash
cd python
python3 run_all.py
```

Each `extract_*.py` can also be run standalone. The working directory must be `python/` for relative imports to resolve.

## Key patterns

- **Batching**: All extraction scripts batch GEE API calls via `utils.batch_points()` (default 50 points per call) to avoid GEE memory limits.
- **Grouping strategy**: Time-series indicators (heat, nightlights) group by `fieldwork_date` to reuse the same image collection. Coarse-resolution indicators (rainfall at 5.5km, AOD at 1km) group by `city` instead for efficiency.
- **Buffer-based indicators**: Canopy and built-up compute zonal stats within circular buffers (50m, 150m). Nightlights use a 150m buffer. All others are point samples.
- **Column naming**: Buffer-dependent columns include the radius suffix (e.g., `canopy_fraction_50m`, `builtup_fraction_150m`).

## Related repos

- `cfi-map2r2-data` — R analysis pipeline (fixest, ggplot2) that consumes the output CSV
- `cfi-map2-blockexplorer2026` — Shiny app with sampling grid GeoJSONs (source for synthetic test coordinates)

## Conventions

- Config changes go in `config.yaml`, not hardcoded in scripts
- GEE dataset IDs and band names are always in config, not in code
- New indicators follow the pattern: `extract_{name}.py` with a `extract_{name}(df, config)` function and a `main()` entrypoint
- The data dictionary (`data/output/data_dictionary.md`) must be updated when columns are added or changed
