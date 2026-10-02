# cfi-environdata

Remote-sensing environmental indicator extraction for the CFI MAP2 Round 2 study of micro and small enterprises across five emerging market cities.

## Overview

This utility takes GPS coordinates of listed businesses in **Sao Paulo, Addis Ababa, Delhi, Jakarta and Lagos** and extracts environmental indicators, mostly from [Google Earth Engine](https://earthengine.google.com/). Output is designed for merging with MAP2 survey and enumeration data for downstream analysis in R.

There are **two pipelines**, producing three datasets:

| Pipeline | Output | Rows × cols | Unit of analysis |
|---|---|---|---|
| Point-level | `data/output/all_indicators.csv` | 24,497 × 117 | one listed business |
| Block-level, static | `data/output/blocks/all_block_indicators.csv` | 120,314 × 15 | one sampling-grid block |
| Block-level, longitudinal | `data/output/blocks/all_block_indicators_longitudinal.csv` | 1,925,024 × 18 | one block × 45-day period |

The three are **different units of analysis and must not be merged into one another**. An indicator sharing a name across them is not the same quantity.

## Indicators

### Point level — 17 indicators

| # | Indicator | Source | Native | Temporal |
|---|---|---|---|---|
| 1 | Elevation, slope | SRTM | 30 m | Static (2000) |
| 2 | Extreme heat days, day & night LST | MODIS LST | 1 km | 2 yr window |
| 3 | Flood vulnerability | MERIT Hydro HAND + JRC Surface Water | 30–90 m | Static / historical |
| 4 | Tree canopy cover | ESA WorldCover | 10 m | Static (2021) |
| 5 | Rainfall, dry days, dry spells | CHIRPS Daily | 5.5 km | 2 yr window |
| 6 | Air quality (AOD) | MODIS MAIAC | 1 km | 2 yr window |
| 7 | Nighttime lights | VIIRS Monthly | 500 m | 12 mo window |
| 8 | Built-up surface | JRC GHSL | 10 m | Static (2020) |
| 9 | Population density | WorldPop Global1, unconstrained | 100 m | 2020 |
| 10 | Population density | Meta HRSL | ~31 m | ~2015–20 |
| 11 | Humid heat stress (sWBGT) | ERA5-Land | ~11 km | 2 yr window |
| 12 | Traffic air pollution (NO₂) | Sentinel-5P TROPOMI | ~1.1 km | 2 yr window |
| 13 | Building count, height, footprint | Google Open Buildings 2.5D | 0.5 m | 2023 |
| 14 | Population density | WorldPop Global2 R2025A, constrained | 100 m | **2026** |
| 15 | Near-surface wind | ERA5-Land | ~11 km | 2 yr window |
| 16 | Wind gusts | ERA5 hourly | ~28 km | 2 yr window |
| 17 | UTCI, mean radiant temperature | ERA5-HEAT | ~28 km | 2 yr window |

Plus derived columns computed after the merge: exceedance rates (`*_frac_gt*`), a within-city `heat_exposure_index`, and the fire-spread proxies `building_spacing_m` / `building_spacing_ratio`.

### Block level

**Static (10 indicators):** terrain, heat, flood, canopy, built-up, nightlights, HRSL, buildings, NO₂, WorldPop 2026 — a deliberate **subset** of the point indicators, chosen on native resolution and measured within-city variance, because a block map can only show what varies between blocks.

**Longitudinal (6 indicators × 16 periods of 45 days):** heat, rainfall, air quality, nightlights, heat stress, NO₂. Rainfall, ERA5 heat stress and AOD are *dropped* from the static table for low spatial variation and appear here for high temporal variation.

Full definitions, caveats and analytical notes are in the data dictionaries:
- [`data/output/data_dictionary.md`](data/output/data_dictionary.md) — the 117 business-level columns
- [`data/output/blocks/block_data_dictionary.md`](data/output/blocks/block_data_dictionary.md) — both block tables

> **Read the dictionaries before using any indicator cross-city.** Several columns are not comparable between cities as raw values — the `*_days_gt*` counts are over *observed* days and cloud cover varies the denominator by 10×, and the ERA5-based columns at 11–28 km are city-level controls with no within-city signal.

## Setup

### Prerequisites

- Python 3.12 (developed against the miniconda base environment)
- A [Google Earth Engine](https://earthengine.google.com/) account with a cloud project

### Installation

```bash
pip install -r requirements.txt
earthengine authenticate
```

Set your GEE project ID in `config.yaml`:

```yaml
gee:
  project: "your-project-id"
```

## Usage

### Point-level pipeline

```bash
cd python
python3 prepare_gsmm_input.py   # rebuild the input from cfi-map2r2-data
python3 fetch_worldpop.py       # one-off: ~1.7 GB of rasters for indicator 14
python3 run_all.py              # all 17 indicators + merge + derived columns
```

`fetch_worldpop.py` only needs running once, and skips files already present. Without it indicator 14 fails with a message naming the missing file.

### Block-level pipelines

```bash
cd python/blocks
python3 run_all_blocks.py       # 10 static indicators + merge
python3 extract_longitudinal.py # 6 indicators x 16 periods + merge
```

Block polygons are read directly from the `cfi-map2-blockexplorer2026` repo, which must be checked out alongside this one.

Each `extract_*.py` can also be run standalone. The working directory must be `python/` (or `python/blocks/`) for relative imports to resolve.

### Reruns are incremental

`run_all.py` extracts only businesses missing from each indicator's output and reuses the rest, so **adding a city costs only that city**. Reuse is gated on a per-indicator **config fingerprint**: when a setting that affects an indicator's *values* changes, its cache is discarded and it recomputes in full, so one file can never hold rows computed under two different definitions. Within an indicator, every completed batch is checkpointed, so an interrupted run also resumes mid-way.

```bash
python3 run_all.py --force              # ignore all caches
python3 run_all.py --only heat,rainfall # subset (skips the merge)
```

> The fingerprint hashes **config, not code**. Editing an extractor's logic does *not* invalidate its cache — force that indicator explicitly after changing how it computes.

### Input contract

`prepare_gsmm_input.py` builds `data/input/gsmm_listings.csv` from `../cfi-map2r2-data/data/processed/gsmm_coords_for_environdata.csv`. **That repo owns all preparation and cleaning** — export selection, de-duplication, date parsing, coordinate recovery — so those rules are not reimplemented here and cannot drift.

| Column | Description |
|---|---|
| `business_id` | `<Country>_<Enterprise ID>` — GSMM ids are unique only *within* a country |
| `latitude`, `longitude` | WGS84 decimal degrees |
| `fieldwork_date` | Listing date (YYYY-MM-DD). Descriptive only; it defines no indicator's window |
| `city` | One of the five study cities |

> ### ⚠ The input holds exact business locations
>
> `data/input/gsmm_listings.csv` is **git-ignored and must stay that way**, and must never be copied into `cfi-map2r2-data`. Only the derived indicators are safe to share back — they describe the neighbourhood, not the address. The WorldPop rasters under `data/input/worldpop/` are likewise git-ignored, for size rather than sensitivity.

### Output for the analysis app

`make_registry.py` and `blocks/make_block_registry.py` generate three registry files, ported to `cfi-map2r2-data` to drive labelling and captions there:

| File | Frame |
|---|---|
| `registry_environment.R` | business |
| `registry_environment_blocks.R` | block |
| `registry_environment_blocks_longitudinal.R` | block × period |

Generation **fails if any output column is neither registered nor explicitly excluded**, so the registries cannot silently drift from the data. Regenerate after adding indicators; never hand-edit the `.R` files.

### Visual inspection

`inspect_indicators.ipynb` provides interactive maps (via [geemap](https://geemap.org/)) overlaying business points on the underlying GEE layers. Set the `CITY` parameter in the first cell to switch study areas.

```bash
pip install geemap ipywidgets
jupyter notebook inspect_indicators.ipynb
```

## Configuration

All parameters — thresholds, buffer radii, dataset IDs, temporal windows, batch sizes — are in [`config.yaml`](config.yaml), with the reasoning for each choice recorded alongside it. No hardcoded values in the extraction scripts.

## Dependencies beyond the main GEE catalog

Three, worth knowing about because they can break independently of this code:

- **Indicator 10** (Meta HRSL) — a GEE *community* asset, `projects/sat-io/...`
- **Indicator 17** (ERA5-HEAT) — a GEE *third-party* asset, `projects/climate-engine-pro/...`. The extractor checks readability and fails loudly rather than writing nulls
- **Indicator 14** (WorldPop R2025A) — **not in GEE at all**. Published only as per-country downloads, so it reads local GeoTIFFs with `rasterio`. The only indicator that does

## Related repositories

- [`cfi-map2r2-data`](https://github.com/pgubb/cfi-map2r2-data) — R analysis pipeline for MAP2 Round 2; owns input preparation and consumes the registries
- [`cfi-map2-blockexplorer2026`](https://github.com/pgubb/cfi-map2-blockexplorer2026) — sampling grid explorer (Shiny); source of the block polygons

## License

This project is part of the CFI/Mastercard MAP2 research initiative.
