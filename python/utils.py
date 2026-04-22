"""Shared utilities for cfi-environdata remote sensing extraction."""

import os
from pathlib import Path

import ee
import pandas as pd
import yaml


def load_config(config_path: str = None) -> dict:
    """Load configuration from config.yaml."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def init_gee(config: dict):
    """Authenticate and initialise Google Earth Engine."""
    project = config.get("gee", {}).get("project")
    if project:
        ee.Initialize(project=project)
    else:
        ee.Initialize()


def load_business_points(config: dict) -> pd.DataFrame:
    """Load and validate the input business coordinates CSV.

    Returns a DataFrame with columns: business_id, latitude, longitude,
    fieldwork_date (as datetime), city.
    """
    input_path = Path(__file__).parent.parent / config["input_file"]
    col_map = config["input_columns"]
    date_fmt = config.get("date_format", "%Y-%m-%d")

    df = pd.read_csv(input_path)

    # Validate required columns exist
    required = [col_map["id"], col_map["lat"], col_map["lon"],
                col_map["date"], col_map["city"]]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Input file missing required columns: {missing}")

    # Rename to canonical names for internal use
    df = df.rename(columns={
        col_map["id"]: "business_id",
        col_map["lat"]: "latitude",
        col_map["lon"]: "longitude",
        col_map["date"]: "fieldwork_date",
        col_map["city"]: "city",
    })

    df["fieldwork_date"] = pd.to_datetime(df["fieldwork_date"], format=date_fmt)

    # Basic validation
    assert df["latitude"].between(-90, 90).all(), "Latitude out of range"
    assert df["longitude"].between(-180, 180).all(), "Longitude out of range"

    print(f"Loaded {len(df)} business records across "
          f"{df['city'].nunique()} cities.")
    return df


def df_to_ee_feature_collection(df: pd.DataFrame) -> ee.FeatureCollection:
    """Convert a pandas DataFrame with lat/lon to a GEE FeatureCollection.

    Each row becomes a Feature with a Point geometry and all columns as
    properties.
    """
    features = []
    for _, row in df.iterrows():
        geom = ee.Geometry.Point([row["longitude"], row["latitude"]])
        props = {
            "business_id": str(row["business_id"]),
            "fieldwork_date": row["fieldwork_date"].strftime("%Y-%m-%d"),
            "city": row["city"],
        }
        features.append(ee.Feature(geom, props))
    return ee.FeatureCollection(features)


def batch_points(df: pd.DataFrame, batch_size: int):
    """Yield successive batches of rows from the DataFrame."""
    for start in range(0, len(df), batch_size):
        yield df.iloc[start:start + batch_size]


def extract_to_dict(fc: ee.FeatureCollection) -> list[dict]:
    """Pull a GEE FeatureCollection into a list of dicts (client-side)."""
    return fc.getInfo()["features"]


def fc_to_dataframe(features: list[dict]) -> pd.DataFrame:
    """Convert GEE feature list (from getInfo) to a pandas DataFrame."""
    rows = []
    for f in features:
        row = f["properties"].copy()
        rows.append(row)
    return pd.DataFrame(rows)


def save_output(df: pd.DataFrame, name: str, config: dict):
    """Save a DataFrame to the configured output directory."""
    out_dir = Path(__file__).parent.parent / config["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}")
    return out_path
