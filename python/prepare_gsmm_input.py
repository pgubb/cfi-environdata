"""Build the point-pipeline input CSV from cfi-map2r2-data's prepared coordinates.

That repo is the single source of truth for GSMM preparation and cleaning: it
picks the authoritative export per country, de-duplicates on Enterprise ID,
parses dates and normalises decimals, then writes one tidy coordinate file.
This script only adapts that file to the pipeline's input contract — it does no
cleaning of its own, deliberately, so those rules cannot drift between repos.

Its one substantive job is the KEY. The source `business_id` is the bare GSMM
Enterprise ID, which is unique only *within* a country — five ids appear in two
cities each — while `run_all.py` merges every indicator on `business_id` alone.
A bare id would silently give two businesses one set of indicator values. The
key is therefore rewritten as "<Country>_<Enterprise ID>", with the raw id kept
as `enterprise_id` for the country+enterprise_id join back onto `enum_data`.

    cd python && python3 prepare_gsmm_input.py

The output carries exact business coordinates and is git-ignored. Do not commit
it, and do not copy it back into cfi-map2r2-data.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from utils import load_config

REPO_ROOT = Path(__file__).parent.parent


def load_prepared_coords(config: dict) -> pd.DataFrame:
    """Read and validate the prepared coordinate file."""
    gsmm = config["gsmm"]
    cols = gsmm["columns"]
    src = (REPO_ROOT / gsmm["source_file"]).resolve()

    if not src.exists():
        raise FileNotFoundError(
            f"Prepared coordinate file not found:\n  {src}\n"
            f"It is produced by cfi-map2r2-data and is git-ignored there, so it "
            f"will be absent on a fresh clone. Regenerate it in that repo, or "
            f"point gsmm.source_file at another location.")

    df = pd.read_csv(src, dtype={cols["id"]: str})
    print(f"Read {len(df):,} rows from {src}")

    missing = [c for c in cols.values() if c not in df.columns]
    if missing:
        raise ValueError(f"{src.name} missing required columns: {missing}")
    return df.rename(columns={
        cols["id"]: "enterprise_id", cols["lat"]: "latitude",
        cols["lon"]: "longitude", cols["date"]: "fieldwork_date",
        cols["city"]: "city",
    })


def prepare_gsmm_listings(config: dict,
                          cities: list[str] | None = None) -> pd.DataFrame:
    """Adapt the prepared coordinates to the pipeline's input contract."""
    gsmm = config["gsmm"]
    city_country = gsmm["city_country_map"]

    df = load_prepared_coords(config)

    unknown = sorted(set(df["city"]) - set(city_country))
    if unknown:
        raise ValueError(
            f"Cities in the source file with no country mapping: {unknown}. "
            f"Add them to gsmm.city_country_map in config.yaml.")

    wanted = cities or gsmm.get("include_cities") or sorted(city_country)
    bad = [c for c in wanted if c not in city_country]
    if bad:
        raise ValueError(f"Unknown cities {bad}; known: {sorted(city_country)}")
    if set(wanted) != set(city_country):
        skipped = sorted(set(df['city'].unique()) - set(wanted))
        print(f"  SUBSET: keeping {sorted(wanted)}; skipping {skipped}")
        df = df[df["city"].isin(wanted)]

    df = df.copy()
    df["enterprise_id"] = df["enterprise_id"].astype(str).str.strip()
    df["country"] = df["city"].map(city_country)
    df["business_id"] = df["country"] + "_" + df["enterprise_id"]
    df["fieldwork_date"] = pd.to_datetime(df["fieldwork_date"])

    # The bare Enterprise ID collides across countries; the prefixed key must
    # not. If this ever fires, two businesses in ONE country share an id and
    # cfi-map2r2-data's de-duplication has a gap — fix it there, not here.
    dupes = df[df["business_id"].duplicated(keep=False)]
    if not dupes.empty:
        raise RuntimeError(
            f"{len(dupes)} rows share a <Country>_<Enterprise ID> key after "
            f"prefixing, e.g.\n{dupes.head(6).to_string(index=False)}\n"
            f"Resolve in cfi-map2r2-data — this pipeline does not de-duplicate.")

    bad_coords = (df["latitude"].isna() | df["longitude"].isna()
                  | ~df["latitude"].between(-90, 90)
                  | ~df["longitude"].between(-180, 180))
    if bad_coords.any():
        print(f"  ! dropped {int(bad_coords.sum())} rows with invalid coordinates")
        df = df[~bad_coords]
    if df["fieldwork_date"].isna().any():
        n = int(df["fieldwork_date"].isna().sum())
        print(f"  ! dropped {n} rows with an unparseable fieldwork_date")
        df = df[df["fieldwork_date"].notna()]

    return df[["business_id", "latitude", "longitude", "fieldwork_date",
               "city", "country", "enterprise_id"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cities",
        help="Comma-separated subset to ingest, overriding gsmm.include_cities "
             "(e.g. 'Delhi,Lagos').")
    args = parser.parse_args()
    cities = ([c.strip() for c in args.cities.split(",") if c.strip()]
              if args.cities else None)

    config = load_config()
    df = prepare_gsmm_listings(config, cities)

    out_path = REPO_ROOT / config["gsmm"]["output_file"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["fieldwork_date"] = out["fieldwork_date"].dt.strftime(
        config.get("date_format", "%Y-%m-%d"))
    out.to_csv(out_path, index=False)

    print(f"\nWrote {len(out):,} listings across {df['city'].nunique()} cities "
          f"to {out_path}")
    summary = df.groupby("city").agg(
        businesses=("business_id", "size"),
        first_listed=("fieldwork_date", "min"),
        last_listed=("fieldwork_date", "max"))
    summary["first_listed"] = summary["first_listed"].dt.date
    summary["last_listed"] = summary["last_listed"].dt.date
    print(summary.to_string())
    print("\nThis file holds exact business coordinates: it is git-ignored, "
          "keep it that way.")


if __name__ == "__main__":
    sys.exit(main())
