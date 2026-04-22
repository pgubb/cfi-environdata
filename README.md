# cfi-environdata

Remote-sensing environmental indicator extraction for the CFI MAP2 Round 2 study of micro and small enterprises across five emerging market cities.

## Overview

This utility takes GPS coordinates of surveyed businesses in **Sao Paulo, Addis Ababa, Delhi, Jakarta, and Lagos** and extracts environmental indicators from publicly available satellite imagery via [Google Earth Engine](https://earthengine.google.com/). The output is a single CSV designed for merging with MAP2 survey and enumeration data for downstream analysis in R.

## Indicators

| # | Indicator | Source | Resolution | Temporal |
|---|---|---|---|---|
| 1 | Elevation | SRTM 30m | 30m | Static (2000) |
| 2 | Extreme heat days | MODIS LST | 1km | 2yr trailing window |
| 3 | Flood vulnerability | MERIT Hydro HAND + JRC Surface Water | 30–90m | Static / historical |
| 4 | Tree canopy cover | ESA WorldCover | 10m | Static (2021) |
| 5 | Heavy rainfall days | CHIRPS Daily | 5.5km | 2yr trailing window |
| 6 | Air quality (AOD) | MODIS MAIAC | 1km | 2yr trailing window |
| 7 | Nighttime lights | VIIRS Monthly | 500m | 12mo trailing window |
| 8 | Built-up surface | JRC GHSL | 10m | Static (2020) |

Full definitions, processing details, and analytical notes for all 47 output columns are in [`data/output/data_dictionary.md`](data/output/data_dictionary.md).

## Setup

### Prerequisites

- Python 3.10+
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

### Run the full pipeline

```bash
cd python
python run_all.py
```

This processes all 8 indicators and writes:
- Per-indicator CSVs to `data/output/`
- A merged `data/output/all_indicators.csv` with all columns

Each extraction script can also be run independently (e.g., `python extract_elevation.py`).

### Input format

A CSV file (path configured in `config.yaml`) with columns:

| Column | Description |
|---|---|
| `business_id` | Unique identifier |
| `latitude` | WGS84 latitude (decimal degrees) |
| `longitude` | WGS84 longitude (decimal degrees) |
| `fieldwork_date` | Date of data collection (YYYY-MM-DD) |
| `city` | City name (Sao Paulo, Addis Ababa, Delhi, Jakarta, Lagos) |

### Visual inspection

The Jupyter notebook `inspect_indicators.ipynb` provides interactive maps (via [geemap](https://geemap.org/)) overlaying business points on the underlying GEE raster layers for each indicator. Set the `CITY` parameter in the first cell to switch between study areas.

```bash
pip install geemap ipywidgets
jupyter notebook inspect_indicators.ipynb
```

## Configuration

All parameters — thresholds, buffer radii, dataset IDs, temporal windows — are in [`config.yaml`](config.yaml). No hardcoded values in the extraction scripts.

## Related repositories

- [`cfi-map2r2-data`](https://github.com/pgubb/cfi-map2r2-data) — R analysis pipeline for MAP2 Round 2
- [`cfi-map2-blockexplorer2026`](https://github.com/pgubb/cfi-map2-blockexplorer2026) — Sampling grid explorer (Shiny)

## License

This project is part of the CFI/Mastercard MAP2 research initiative.
