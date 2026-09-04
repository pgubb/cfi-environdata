"""Shared utilities for cfi-environdata remote sensing extraction."""

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

import ee
import pandas as pd
import yaml


# --- GEE resilience settings ---
# Mirrors blocks/utils_blocks.py. The point pipeline runs tens of thousands of
# getInfo() calls, so a bare call is the single most likely way for a long run
# to die.
GETINFO_TIMEOUT_SEC = 300   # 5 min per request (GEE server limit is ~5 min)
GETINFO_MAX_RETRIES = 3
GETINFO_RETRY_BACKOFF = 30  # seconds before first retry, doubling thereafter


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


def safe_getinfo(ee_object, timeout=GETINFO_TIMEOUT_SEC,
                 max_retries=GETINFO_MAX_RETRIES):
    """Call .getInfo() with a client-side timeout and retry on failure.

    GEE's getInfo() blocks indefinitely if the server stalls, so wrap it in a
    thread with a timeout and retry transient errors (timeouts, EEException,
    connection resets). Raises the last error once retries are exhausted.
    """
    last_err = None
    for attempt in range(1, max_retries + 1):
        # NOT `with ThreadPoolExecutor(...)`: the context manager's __exit__
        # calls shutdown(wait=True), which blocks until the worker finishes —
        # so a timeout would still wait out the full server-side request and
        # buy nothing. shutdown(wait=False) abandons the in-flight call
        # immediately. The worker thread lingers until GEE responds; that is
        # the price of getInfo() having no cancellation mechanism.
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(ee_object.getInfo)
            return future.result(timeout=timeout)
        except FuturesTimeout:
            last_err = TimeoutError(
                f"getInfo() timed out after {timeout}s "
                f"(attempt {attempt}/{max_retries})")
        except Exception as e:
            last_err = e
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if attempt == max_retries:
            break
        backoff = GETINFO_RETRY_BACKOFF * (2 ** (attempt - 1))
        print(f"    [retry] Attempt {attempt}/{max_retries} failed: "
              f"{last_err}. Retrying in {backoff}s...")
        time.sleep(backoff)

    raise last_err


# --- Checkpoint / resume support ---
#
# Each indicator appends every completed batch to a checkpoint CSV in the output
# directory, so a run killed midway resumes where it stopped instead of
# restarting from zero. The file is deleted once the indicator finishes.
# `.checkpoint_*.csv` matches the data/output/*.csv gitignore rule.

def _checkpoint_path(indicator_name: str, config: dict) -> Path:
    """Return the path for an indicator's checkpoint CSV."""
    out_dir = Path(__file__).parent.parent / config["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f".checkpoint_{indicator_name}.csv"


def load_checkpoint(indicator_name: str, config: dict,
                    verbose: bool = True) -> pd.DataFrame | None:
    """Load an indicator's partial results, or None if there is no checkpoint."""
    cp = _checkpoint_path(indicator_name, config)
    if not cp.exists():
        return None
    df = pd.read_csv(cp)
    df["business_id"] = df["business_id"].astype(str)
    if verbose and len(df):
        print(f"  Resuming from checkpoint: {len(df):,} points already done")
    return df


def append_checkpoint(rows: list[dict], indicator_name: str, config: dict):
    """Append a batch of result rows to the checkpoint CSV."""
    if not rows:
        return
    cp = _checkpoint_path(indicator_name, config)
    pd.DataFrame(rows).to_csv(cp, mode="a", header=not cp.exists(), index=False)


def clear_checkpoint(indicator_name: str, config: dict):
    """Remove the checkpoint file after the indicator completes."""
    cp = _checkpoint_path(indicator_name, config)
    if cp.exists():
        cp.unlink()


def filter_remaining_points(df: pd.DataFrame,
                            checkpoint_df: pd.DataFrame | None) -> pd.DataFrame:
    """Return only the points not already recorded in the checkpoint."""
    if checkpoint_df is None or checkpoint_df.empty:
        return df
    done = set(checkpoint_df["business_id"].astype(str))
    remaining = df[~df["business_id"].astype(str).isin(done)]
    print(f"  {len(remaining):,} of {len(df):,} points remaining")
    return remaining


def finish_indicator(indicator_name: str, config: dict) -> pd.DataFrame:
    """Read back an indicator's full results and clear its checkpoint."""
    final_df = load_checkpoint(indicator_name, config, verbose=False)
    clear_checkpoint(indicator_name, config)
    if final_df is None:
        return pd.DataFrame()
    return final_df


class BatchProgress:
    """Prints one line per completed batch so a long run is observable."""

    def __init__(self, total_points: int, label: str = ""):
        self.total = total_points
        self.done = 0
        self.label = label
        self.started = time.time()

    def update(self, n: int):
        self.done += n
        elapsed = time.time() - self.started
        rate = self.done / elapsed if elapsed > 0 else 0
        eta = (self.total - self.done) / rate if rate > 0 else 0
        pct = 100 * self.done / self.total if self.total else 100
        print(f"    {self.label}{self.done:,}/{self.total:,} ({pct:.1f}%) "
              f"| {rate:.0f} pts/s | ETA {eta/60:.1f} min", flush=True)


def get_city_window(city_df: pd.DataFrame, config: dict,
                    trailing_years: int = None,
                    trailing_months: int = None) -> tuple[str, str]:
    """Return (start_date, end_date) for one city's time-series window.

    The window is a FIXED length — exactly `trailing_years` or `trailing_months`
    back from the end date — so every city and every indicator spans the same
    number of days. The `*_days_gt*` columns are counts, so an unequal window
    length would silently inflate one city's count relative to another's.

    The end date is `time_window.analysis_end_date` from config. Set that to
    null to anchor each city at its own latest fieldwork date instead (lengths
    stay equal; the calendar period becomes city-specific).
    """
    if (trailing_years is None) == (trailing_months is None):
        raise ValueError("Pass exactly one of trailing_years / trailing_months")

    configured_end = config.get("time_window", {}).get("analysis_end_date")
    end = (pd.Timestamp(configured_end) if configured_end
           else city_df["fieldwork_date"].max())

    offset = (pd.DateOffset(years=trailing_years) if trailing_years is not None
              else pd.DateOffset(months=trailing_months))
    start = end - offset
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# --- Incremental extraction: config fingerprints -----------------------------
#
# An indicator's cached output can be REUSED for businesses already in it, but
# only while the settings that produced it are unchanged. A fingerprint of the
# config that actually affects each indicator's VALUES is stored alongside the
# output; when it changes, the cache and checkpoint are discarded and the
# indicator recomputes in full.
#
# Without this, changing (say) the analysis window would leave a mix of rows
# computed under old and new semantics in one file, which is worse than an
# obvious full recompute because nothing looks wrong.

# Config sections whose values feed each indicator.
INDICATOR_CONFIG_KEYS = {
    "elevation":   ["elevation"],
    "heat":        ["heat", "time_window"],
    "flood":       ["flood", "elevation"],   # elevation feeds the coastal flag
    "canopy":      ["canopy"],
    "rainfall":    ["rainfall", "time_window"],
    "airquality":  ["airquality", "time_window"],
    "nightlights": ["nightlights", "time_window"],
    "builtup":     ["builtup"],
    "population":  ["population"],
    "hrsl":        ["hrsl"],
    "heatstress":  ["heatstress", "time_window"],
    "no2":         ["no2", "time_window"],
}

# Indicators whose window depends on the data when analysis_end_date is null.
TIME_SERIES_INDICATORS = {"heat", "rainfall", "airquality", "nightlights",
                          "heatstress", "no2"}

# Keys that affect only speed, never results. Tuning these must NOT invalidate
# a cache — otherwise raising a batch size silently forces a multi-hour rerun.
PERFORMANCE_ONLY_KEYS = {"batch_size", "getinfo_timeout_sec"}

# Indicators sampling at gee.default_scale_m rather than their own scale_m.
_USES_DEFAULT_SCALE = {"elevation", "flood"}


def _strip_perf_keys(obj):
    """Recursively drop performance-only keys so tuning them keeps the cache."""
    if isinstance(obj, dict):
        return {k: _strip_perf_keys(v) for k, v in sorted(obj.items())
                if k not in PERFORMANCE_ONLY_KEYS}
    if isinstance(obj, list):
        return [_strip_perf_keys(v) for v in obj]
    return obj


def indicator_fingerprint(name: str, config: dict, df: pd.DataFrame) -> str:
    """Stable hash of everything that affects this indicator's output values."""
    payload = {k: _strip_perf_keys(config.get(k))
               for k in INDICATOR_CONFIG_KEYS.get(name, [name])}

    if name in _USES_DEFAULT_SCALE:
        payload["_default_scale_m"] = config.get("gee", {}).get("default_scale_m")

    # When analysis_end_date is null each city's window ends at its own latest
    # listing date, so ADDING BUSINESSES CAN MOVE THE WINDOW and invalidate
    # every existing row for that city. Fold the per-city max dates in so that
    # shift is detected instead of silently mixing two windows in one file.
    tw = config.get("time_window", {}) or {}
    if name in TIME_SERIES_INDICATORS and not tw.get("analysis_end_date"):
        payload["_city_max_dates"] = {
            str(city): str(pd.Timestamp(g["fieldwork_date"].max()).date())
            for city, g in df.groupby("city")
        }

    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _manifest_path(config: dict) -> Path:
    out_dir = Path(__file__).parent.parent / config["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "extraction_manifest.json"


def load_manifest(config: dict) -> dict:
    """Read the per-indicator fingerprint/row-count record."""
    mp = _manifest_path(config)
    if not mp.exists():
        return {}
    try:
        return json.loads(mp.read_text())
    except (json.JSONDecodeError, OSError):
        print("  ! extraction_manifest.json unreadable; treating as absent")
        return {}


def save_manifest(manifest: dict, config: dict):
    _manifest_path(config).write_text(json.dumps(manifest, indent=2, sort_keys=True))


# --- Derived exceedance rates ---------------------------------------------
#
# The `*_days_gt*` columns are counts of days exceeding a threshold AMONG DAYS
# THAT WERE OBSERVED. Cloud masking makes that denominator vary enormously
# between cities — measured over a 730-day window, mean valid observations run
# 404 (Addis Ababa) to 40 (Lagos) for MODIS LST, and 347 to 91 for MAIAC AOD.
# So a raw count of 0 for Lagos ("0 of ~40 observed days") is not comparable
# with 0 for Addis Ababa ("0 of ~404"), and the city with the LOWER raw count
# can have the HIGHER exceedance rate.
#
# These fractions normalise by each point's own observation count, which is
# what makes the indicator comparable across cities.
#
# Rainfall is deliberately NOT included: CHIRPS is gap-filled rather than
# cloud-masked, so rain_valid_obs is exactly 730 everywhere and a fraction
# would be a constant rescaling carrying no extra information.
# {count-column prefix: (denominator column, rate-column prefix)}
#
# The rate prefix is given EXPLICITLY rather than derived by string surgery on
# the count name. An earlier version did `col.replace("_days_gt", "_frac_gt")`,
# which silently produced the SAME name for heat_nights_gt* (no "_days_gt"
# substring) and overwrote the counts with their own rates in place.
RATE_DENOMINATORS = {
    "heat_days_gt":   ("lst_valid_obs", "heat_frac_gt"),
    "heat_nights_gt": ("lst_night_valid_obs", "heat_nights_frac_gt"),
    "aod_days_gt":    ("aod_valid_obs", "aod_frac_gt"),
}
# wbgt_days_gt* and the NO2 summaries are deliberately absent: ERA5-Land is a
# reanalysis with no cloud gaps (every day present), and the NO2 columns are
# means rather than day-counts, so neither needs an observation-count
# denominator.


def add_exceedance_rates(merged: pd.DataFrame) -> pd.DataFrame:
    """Add `*_frac_gt*` columns beside each `*_days_gt*` / `*_nights_gt*` count.

    Each is the share of that point's OBSERVED days (or nights) exceeding the
    threshold, in [0, 1]. NaN where the observation count is zero or missing —
    a point with no observations has an undefined rate, not a rate of zero.

    Deliberately NOT annualised (e.g. fraction x 365). That would extrapolate
    the clear-sky exceedance rate to cloudy days, which are systematically
    cooler and less polluted, and would overstate exposure most in exactly the
    cloudiest cities.
    """
    out = merged.copy()
    for prefix, (denom_col, rate_prefix) in RATE_DENOMINATORS.items():
        if denom_col not in out.columns:
            continue
        denom = out[denom_col].where(out[denom_col] > 0)  # 0 and NaN -> NaN
        for col in [c for c in merged.columns if c.startswith(prefix)]:
            rate_col = rate_prefix + col[len(prefix):]
            # A rate must never land on top of the count it is derived from.
            if rate_col == col:
                raise ValueError(
                    f"Rate column for {col!r} resolves to the same name; "
                    f"fix the rate prefix for {prefix!r} in RATE_DENOMINATORS.")
            values = out[col] / denom
            if rate_col in out.columns:
                out[rate_col] = values
            else:
                out.insert(out.columns.get_loc(col) + 1, rate_col, values)
    return out
