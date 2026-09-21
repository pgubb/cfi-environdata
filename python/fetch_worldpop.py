"""Download the WorldPop R2025A (Global2) national population rasters.

Fetches one GeoTIFF per study country from hub.worldpop.org into
`data/input/worldpop/`. These are SOURCE data, ~1.7 GB in total, git-ignored
and re-downloadable — nothing derived from them lives here.

    cd python && python3 fetch_worldpop.py          # skips files already present
    cd python && python3 fetch_worldpop.py --force  # re-download everything

WHY A SEPARATE SCRIPT RATHER THAN GOOGLE EARTH ENGINE. The R2025A release is
not in the GEE catalog; GEE carries `WorldPop/GP/100m/pop`, which is the older
Global1 2000-2020 series (indicator 9). This release is published only as
per-country downloads, so the extraction for it reads local rasters instead of
calling GEE. That is the one indicator in this pipeline that does.

FILE NAMING follows the release statement's convention
`{iso}_{gender}_{age}_{year}_{type}_{resolution}_{release}_{version}.tif`, with
`pop` standing in for gender+age on the all-ages/both-sexes totals we want:

    ind_pop_2026_CN_100m_R2025A_v1.tif

`CN` is Constrained — population allocated only to cells where the built
settlement model found buildings. R2025A ships constrained ONLY; there is no
unconstrained variant of this release, which matters because indicator 9 (the
Global1 2020 layer) IS unconstrained. See the data dictionary.
"""

import argparse
import sys
import urllib.request
from pathlib import Path

from utils import load_config

BASE = ("https://data.worldpop.org/GIS/Population/Global_2015_2030/"
        "{release}/{year}/{ISO}/v{fv}/100m/constrained/"
        "{iso}_pop_{year}_CN_100m_{release}_v{fv}.tif")


def target_dir(config: dict) -> Path:
    cfg = config["pop2026"]
    return Path(__file__).resolve().parent.parent / cfg["raster_dir"]


def expected_files(config: dict) -> dict[str, Path]:
    """Map ISO-3 (upper) -> local path, for every configured country."""
    cfg = config["pop2026"]
    out_dir = target_dir(config)
    return {
        iso.upper(): out_dir / BASE.format(
            release=cfg["release"], year=int(cfg["year"]),
            ISO=iso.upper(), iso=iso.lower(), fv=cfg["file_version"]).split("/")[-1]
        for iso in cfg["country_iso3"].values()
    }


def _download(url: str, dest: Path):
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(tmp, "wb") as fh:
            while chunk := r.read(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total and done % (50 << 20) < (1 << 20):
                    print(f"    {done/1e6:,.0f} / {total/1e6:,.0f} MB", flush=True)
    # Rename only on success, so an interrupted download never looks complete.
    tmp.rename(dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="Re-download files that are already present.")
    args = ap.parse_args()

    config = load_config()
    cfg = config["pop2026"]
    out_dir = target_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)

    for city, iso in sorted(cfg["country_iso3"].items()):
        url = BASE.format(release=cfg["release"], year=int(cfg["year"]),
                          ISO=iso.upper(), iso=iso.lower(), fv=cfg["file_version"])
        dest = out_dir / url.split("/")[-1]
        if dest.exists() and not args.force:
            print(f"  {iso}: already have {dest.name} "
                  f"({dest.stat().st_size/1e6:,.0f} MB)")
            continue
        print(f"  {iso}: downloading {dest.name}", flush=True)
        try:
            _download(url, dest)
        except Exception as e:
            # A partial file must not be left where the extractor would read it.
            dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
            sys.exit(f"FAILED {iso}: {e}\n  {url}")
        print(f"    done ({dest.stat().st_size/1e6:,.0f} MB)")

    print(f"\nAll rasters in {out_dir}")


if __name__ == "__main__":
    main()
