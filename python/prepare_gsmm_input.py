"""Build the point-pipeline input CSV from the GSMM enumeration exports.

The GSMM business listing is the census of business LOCATIONS: every listed
business has coordinates, whether or not it was ever selected or interviewed.
Extracting environmental indicators once per listing therefore covers the
interviewed sample as a by-product and keeps ONE environmental value per
business. (Rationale in cfi-map2r2-data/R/prep_enumeration.R.)

Reads the "Business Data" sheet of the latest export per country from
`gsmm.source_dir` and writes `gsmm.output_file` with the column names
`run_all.py` expects: business_id, latitude, longitude, fieldwork_date, city.

    cd python && python3 prepare_gsmm_input.py

The output carries exact business coordinates and is git-ignored. Do not commit
it, and do not copy it into cfi-map2r2-data.
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

from utils import load_config

REPO_ROOT = Path(__file__).parent.parent

# Excel stores dates as days since this epoch (the 1900 date system, offset by
# Excel's phantom 1900 leap day).
EXCEL_EPOCH = "1899-12-30"


def gsmm_snapshot_path(country: str, source_dir: Path,
                       prefixes: list[str]) -> Path | None:
    """The export this study analyses for `country`, or None if it has none.

    Preference is by KIND first, then newest date within that kind — a port of
    gsmm_snapshot_path() in cfi-map2r2-data/R/prep_cto.R. The vendor's
    GSMM_Report is refreshed daily and would otherwise overtake a country team's
    cleaned GSMM_Analysis dataset that is a few days older but authoritative.
    """
    for prefix in prefixes:
        pattern = re.compile(rf"^{re.escape(prefix)}_.*_{re.escape(country)}\.xlsx$")
        files = [p for p in source_dir.glob(f"{prefix}_*_{country}.xlsx")
                 if pattern.match(p.name) and not p.name.startswith("~$")]
        dated = [(m.group(), p) for p in files
                 if (m := re.search(r"\d{8}", p.name))]
        if dated:
            return max(dated)[1]
    return None


def _to_number(s: pd.Series) -> pd.Series:
    """Numeric from GSMM text, tolerating the comma decimal separator."""
    return pd.to_numeric(
        s.astype(str).str.strip().str.replace(",", ".", regex=False),
        errors="coerce")


def _to_listing_date(s: pd.Series) -> pd.Series:
    """Whole-day dates from GSMM's "Date time", which arrives in two formats.

    The cleaned Analysis workbooks have been round-tripped through Excel and
    carry serial numbers ("46244.6666"); the vendor's exports carry datetime
    cells that pandas reads as ISO strings. Both appear in the same folder, so
    handle each per row rather than per file.
    """
    text = s.astype(str).str.strip()
    serial = pd.to_numeric(text, errors="coerce")

    out = pd.Series(pd.NaT, index=text.index, dtype="datetime64[ns]")
    is_serial = serial.notna()
    if is_serial.any():
        # Floor to whole days before converting, matching R's .excel_date().
        out.loc[is_serial] = pd.to_datetime(
            serial[is_serial].astype(float).round(6) // 1,
            unit="D", origin=EXCEL_EPOCH)
    if (~is_serial).any():
        out.loc[~is_serial] = pd.to_datetime(
            text[~is_serial], errors="coerce", format="mixed")
    return out.dt.normalize()


def read_country_listings(country: str, path: Path, config: dict) -> pd.DataFrame:
    """One row per listed business in `country`, ready to concatenate."""
    gsmm = config["gsmm"]
    cols = gsmm["columns"]
    city = gsmm["country_city_map"][country]

    raw = pd.read_excel(path, sheet_name=gsmm["sheet"], dtype=str)

    missing = [c for c in cols.values() if c not in raw.columns]
    # `city` is only used as a cross-check, so its absence is not fatal.
    missing = [c for c in missing if c != cols["city"]]
    if missing:
        raise ValueError(
            f"{path.name}: sheet '{gsmm['sheet']}' missing columns {missing}")

    eid = raw[cols["id"]].astype(str).str.strip()
    df = pd.DataFrame({
        "country": country,
        "enterprise_id": eid,
        "latitude": _to_number(raw[cols["lat"]]),
        "longitude": _to_number(raw[cols["lon"]]),
        "fieldwork_date": _to_listing_date(raw[cols["date"]]),
        "city": city,
    })

    n_raw = len(df)

    # The export's own City column should agree with the config map; a
    # disagreement means one of them has drifted and is worth seeing.
    if cols["city"] in raw.columns:
        seen = set(raw[cols["city"]].dropna().str.strip().unique()) - {""}
        if seen and seen != {city}:
            print(f"  ! {country}: export City column is {sorted(seen)}, "
                  f"config says '{city}' — using config")

    # De-duplicate on Enterprise ID, keeping the first (a few repeats occur),
    # as prep_enumeration() does.
    blank = ~eid.astype(bool) | eid.isin({"nan", "None"})
    if blank.any():
        print(f"  ! {country}: dropped {int(blank.sum())} rows with a blank "
              f"Enterprise ID")
        df = df[~blank]
    n_dedupe = int(df["enterprise_id"].duplicated().sum())
    df = df[~df["enterprise_id"].duplicated()]

    # Enterprise IDs are unique only WITHIN a country — 5 are reused across two
    # countries — and run_all.py merges every indicator on business_id alone, so
    # a bare id would fan those rows out silently.
    df["business_id"] = df["country"] + "_" + df["enterprise_id"]

    bad = (df["latitude"].isna() | df["longitude"].isna()
           | ~df["latitude"].between(-90, 90)
           | ~df["longitude"].between(-180, 180)
           | ((df["latitude"].abs() < 0.001) & (df["longitude"].abs() < 0.001)))
    n_bad = int(bad.sum())
    df = df[~bad]

    n_nodate = int(df["fieldwork_date"].isna().sum())
    df = df[df["fieldwork_date"].notna()]

    span = ""
    if len(df):
        span = (f"  {df['fieldwork_date'].min():%Y-%m-%d} to "
                f"{df['fieldwork_date'].max():%Y-%m-%d}")
    print(f"  {country:<10s} {path.name:<42s} {n_raw:>6,} listed -> "
          f"{len(df):>6,} usable"
          f"{f' (-{n_dedupe} dup id)' if n_dedupe else ''}"
          f"{f' (-{n_bad} bad coords)' if n_bad else ''}"
          f"{f' (-{n_nodate} no date)' if n_nodate else ''}{span}")
    return df


def prepare_gsmm_listings(config: dict,
                          countries: list[str] | None = None) -> pd.DataFrame:
    """Read each country's latest GSMM export into one input DataFrame.

    `countries` (or gsmm.include_countries in config) restricts the ingest to a
    subset — useful for a test run over fewer cities. None means all five.
    """
    gsmm = config["gsmm"]
    source_dir = (REPO_ROOT / gsmm["source_dir"]).resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(
            f"GSMM source directory not found: {source_dir}\n"
            f"Set gsmm.source_dir in config.yaml, or sync the exports "
            f"(see cfi-map2r2-data/data/README.md).")

    known = gsmm["country_city_map"]
    wanted = countries or gsmm.get("include_countries") or sorted(known)
    unknown = [c for c in wanted if c not in known]
    if unknown:
        raise ValueError(
            f"Unknown countries {unknown}; known: {sorted(known)}")
    selected = [c for c in sorted(known) if c in set(wanted)]

    print(f"Reading GSMM exports from {source_dir}")
    if len(selected) < len(known):
        skipped = sorted(set(known) - set(selected))
        print(f"  SUBSET: {len(selected)} of {len(known)} countries "
              f"({', '.join(selected)}); skipping {', '.join(skipped)}")

    frames = []
    for country in selected:
        path = gsmm_snapshot_path(country, source_dir, gsmm["file_prefixes"])
        if path is None:
            print(f"  ! {country:<10s} no export found — skipped")
            continue
        frames.append(read_country_listings(country, path, config))

    if not frames:
        raise RuntimeError(f"No GSMM exports found in {source_dir}")

    df = pd.concat(frames, ignore_index=True)

    collisions = int(df["business_id"].duplicated().sum())
    if collisions:
        raise RuntimeError(
            f"{collisions} duplicate business_id values after prefixing by "
            f"country — the id scheme is not unique, do not run the pipeline.")

    return df[["business_id", "latitude", "longitude", "fieldwork_date",
               "city", "country", "enterprise_id"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--countries",
        help="Comma-separated subset to ingest, overriding "
             "gsmm.include_countries (e.g. 'Ethiopia,Indonesia,Nigeria').")
    args = parser.parse_args()
    countries = ([c.strip() for c in args.countries.split(",") if c.strip()]
                 if args.countries else None)

    config = load_config()
    df = prepare_gsmm_listings(config, countries)

    out_path = REPO_ROOT / config["gsmm"]["output_file"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["fieldwork_date"] = out["fieldwork_date"].dt.strftime(
        config.get("date_format", "%Y-%m-%d"))
    out.to_csv(out_path, index=False)

    print(f"\nWrote {len(out):,} listings across {df['city'].nunique()} cities "
          f"to {out_path}")
    print(df.groupby("city").size().to_string())
    print("\nThis file holds exact business coordinates: it is git-ignored, "
          "keep it that way.")
    if config.get("input_file") != config["gsmm"]["output_file"]:
        print(f"\nNOTE: config.yaml input_file is "
              f"'{config.get('input_file')}'. Point it at "
              f"'{config['gsmm']['output_file']}' before running run_all.py.")


if __name__ == "__main__":
    sys.exit(main())
