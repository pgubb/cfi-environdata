"""Zonal population density from the WorldPop R2025A local rasters.

Shared by the point pipeline (`extract_pop2026.py`, 50m/150m buffers) and the
block pipeline (zonal mean over block polygons), so the two cannot drift — the
same convention this repo already applies to the GEE image builders.

THIS IS THE ONLY INDICATOR THAT DOES NOT USE GOOGLE EARTH ENGINE. R2025A is
published as per-country downloads and is not in the GEE catalog, so the
rasters are read locally with rasterio. See `fetch_worldpop.py`.

--------------------------------------------------------------------------
WHAT "DENSITY" MEANS HERE, AND WHY IT IS COMPUTED THIS WAY
--------------------------------------------------------------------------
The band holds a population COUNT PER CELL, not a density — the same trap
CLAUDE.md flags for the GEE layers, arriving by a different route. Two things
follow.

1. EVERY CELL HAS A DIFFERENT GROUND AREA. The grid is 3 arc-seconds in
   EPSG:4326, so a cell is 8,536 m2 at Jakarta (6.2S) but 7,539 m2 at Delhi
   (28.6N) — 13% apart across the five cities. Assuming a flat 100x100m would
   bias every cross-city density comparison, and by a different amount in each
   city. Cell area is therefore computed per raster ROW from the spheroid:
   A = R^2 * dlon * |sin(lat_top) - sin(lat_bottom)|.

2. PARTIAL CELLS MUST BE WEIGHTED, NOT COUNTED WHOLE. A 50m buffer is smaller
   than one cell and a ~149m block covers only a handful, so which cells count
   as "inside" dominates the answer. Each overlapping cell contributes the
   exact fraction `w` of its own area that the zone covers, and the zone's
   density is

       1e6 * sum(count_i * w_i) / sum(cell_area_m2_i * w_i)

   i.e. people in the overlap divided by ground area of the overlap. Taking a
   plain unweighted mean of cell densities instead would let a cell clipped at
   1% of its area count as much as one fully enclosed.

Overlap fractions are computed in DEGREE space (`intersection_area_deg /
cell_area_deg`). That is exact for the fraction even though the areas
themselves are not metric, because the degrees-to-metres scaling is constant
across a single 92m cell; the metric conversion happens once, per row, via the
cell areas.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import shapely
from rasterio.windows import Window, from_bounds

# Authalic (equal-area) mean radius of WGS84, metres.
_EARTH_R = 6371007.181

# Cap on the number of (zone, cell) pairs intersected in one vectorised call,
# to bound peak memory on the large cities.
_PAIR_CHUNK = 250_000


def raster_path(city: str, config: dict) -> Path:
    """Local GeoTIFF for the country containing `city`."""
    cfg = config["pop2026"]
    iso = cfg["country_iso3"].get(city)
    if iso is None:
        raise KeyError(f"No ISO-3 configured for city {city!r} in pop2026.country_iso3")
    root = Path(__file__).resolve().parent.parent / cfg["raster_dir"]
    name = (f"{iso.lower()}_pop_{int(cfg['year'])}_CN_100m_"
            f"{cfg['release']}_v{cfg['file_version']}.tif")
    path = root / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Run `cd python && python3 fetch_worldpop.py` "
            f"to download the WorldPop {cfg['release']} rasters (~1.7 GB).")
    return path


def _row_cell_areas(top_lat: float, dlat: float, dlon: float, n_rows: int) -> np.ndarray:
    """Ground area (m2) of one cell in each of `n_rows` raster rows."""
    lat_top = top_lat - dlat * np.arange(n_rows)
    lat_bot = lat_top - dlat
    return (np.radians(dlon) * _EARTH_R ** 2
            * np.abs(np.sin(np.radians(lat_top)) - np.sin(np.radians(lat_bot))))


class CityRaster:
    """The population window covering one city, held in memory.

    Reading a window rather than the national raster is what makes this cheap:
    India's file is 748 MB, but Delhi's extent is a few hundred cells square.
    """

    def __init__(self, city: str, config: dict, bounds, margin_deg: float = 0.02):
        self.city = city
        self.path = raster_path(city, config)
        self.nodata_as_zero = bool(config["pop2026"].get("nodata_as_zero", False))

        minx, miny, maxx, maxy = bounds
        with rasterio.open(self.path) as src:
            self.nodata = src.nodata
            win = from_bounds(minx - margin_deg, miny - margin_deg,
                              maxx + margin_deg, maxy + margin_deg,
                              src.transform).round_offsets().round_lengths()
            # Clip the window to the raster, so a city on a national edge does
            # not read outside the array.
            win = win.intersection(Window(0, 0, src.width, src.height))
            self.counts = src.read(1, window=win).astype("float64")
            self.transform = src.window_transform(win)

        self.dlon = abs(self.transform.a)
        self.dlat = abs(self.transform.e)
        self.x0 = self.transform.c
        self.y0 = self.transform.f
        self.n_rows, self.n_cols = self.counts.shape

        # NoData handling. On a CONSTRAINED layer, unbuilt land can legitimately
        # be either 0 or nodata depending on the country tile, and the two mean
        # different things for a mean: nodata excluded shrinks the denominator
        # (density over populated ground), nodata as zero keeps it (density over
        # all ground). Default is to EXCLUDE, matching how GEE masks, with the
        # choice exposed in config because it materially changes the values.
        self.valid = np.isfinite(self.counts)
        if self.nodata is not None:
            self.valid &= (self.counts != self.nodata)
        if self.nodata_as_zero:
            self.counts = np.where(self.valid, self.counts, 0.0)
            self.valid = np.ones_like(self.counts, dtype=bool)
        else:
            self.counts = np.where(self.valid, self.counts, 0.0)

        self.cell_area = _row_cell_areas(self.y0, self.dlat, self.dlon, self.n_rows)

    def density(self, geoms) -> np.ndarray:
        """Area-weighted people/km2 for each geometry; NaN where no valid cell."""
        geoms = np.asarray(geoms, dtype=object)
        out = np.full(len(geoms), np.nan)
        if len(geoms) == 0:
            return out

        minx, miny, maxx, maxy = shapely.bounds(geoms).T
        c0 = np.floor((minx - self.x0) / self.dlon).astype(np.int64)
        c1 = np.ceil((maxx - self.x0) / self.dlon).astype(np.int64)
        r0 = np.floor((self.y0 - maxy) / self.dlat).astype(np.int64)
        r1 = np.ceil((self.y0 - miny) / self.dlat).astype(np.int64)
        np.clip(c0, 0, self.n_cols, out=c0); np.clip(c1, 0, self.n_cols, out=c1)
        np.clip(r0, 0, self.n_rows, out=r0); np.clip(r1, 0, self.n_rows, out=r1)

        n_cell = np.maximum(r1 - r0, 0) * np.maximum(c1 - c0, 0)
        # Build the flat (zone, cell) pair list: every zone paired with every
        # cell its bounding box touches.
        zone_idx = np.repeat(np.arange(len(geoms)), n_cell)
        if zone_idx.size == 0:
            return out
        within = np.arange(n_cell.sum()) - np.repeat(
            np.cumsum(n_cell) - n_cell, n_cell)
        width = np.repeat(c1 - c0, n_cell)
        rows = np.repeat(r0, n_cell) + within // width
        cols = np.repeat(c0, n_cell) + within % width

        num = np.zeros(len(geoms))
        den = np.zeros(len(geoms))
        cell_deg_area = self.dlon * self.dlat

        for s in range(0, zone_idx.size, _PAIR_CHUNK):
            zi = zone_idx[s:s + _PAIR_CHUNK]
            rr = rows[s:s + _PAIR_CHUNK]
            cc = cols[s:s + _PAIR_CHUNK]
            boxes = shapely.box(
                self.x0 + cc * self.dlon, self.y0 - (rr + 1) * self.dlat,
                self.x0 + (cc + 1) * self.dlon, self.y0 - rr * self.dlat)
            w = shapely.area(shapely.intersection(geoms[zi], boxes)) / cell_deg_area
            keep = (w > 0) & self.valid[rr, cc]
            if not keep.any():
                continue
            zi, rr, cc, w = zi[keep], rr[keep], cc[keep], w[keep]
            np.add.at(num, zi, self.counts[rr, cc] * w)
            np.add.at(den, zi, self.cell_area[rr] * w)

        nz = den > 0
        out[nz] = 1e6 * num[nz] / den[nz]
        return out


def metre_buffers(lons, lats, radius_m: float):
    """Circular-in-metres buffers around lon/lat points, as EPSG:4326 polygons.

    Built as degree ellipses (dlat fixed, dlon scaled by cos(lat)) rather than
    by reprojecting: at 50-150m the difference from a true geodesic circle is
    far below the ~92m cell size, and it keeps everything in one CRS.
    """
    lats = np.asarray(lats, dtype="float64")
    lons = np.asarray(lons, dtype="float64")
    dlat = radius_m / 110_574.0
    dlon = radius_m / (111_320.0 * np.cos(np.radians(lats)))
    theta = np.linspace(0, 2 * np.pi, 33)[:-1]
    xs = lons[:, None] + dlon[:, None] * np.cos(theta)[None, :]
    ys = lats[:, None] + dlat * np.sin(theta)[None, :]
    return shapely.polygons(np.stack([xs, ys], axis=-1))


def density_for_points(df: pd.DataFrame, radius_m: int, config: dict) -> pd.Series:
    """People/km2 within `radius_m` of each row's coordinates, by city."""
    out = pd.Series(np.nan, index=df.index, dtype="float64")
    for city, g in df.groupby("city"):
        buf = metre_buffers(g["longitude"].to_numpy(), g["latitude"].to_numpy(),
                            radius_m)
        ras = CityRaster(city, config, shapely.total_bounds(buf))
        out.loc[g.index] = ras.density(buf)
    return out


def density_for_blocks(gdf, config: dict) -> pd.Series:
    """People/km2 over each block polygon, by city. `gdf` needs `city` + geometry."""
    out = pd.Series(np.nan, index=gdf.index, dtype="float64")
    for city, g in gdf.groupby("city"):
        geoms = g.geometry.to_numpy()
        ras = CityRaster(city, config, shapely.total_bounds(geoms))
        out.loc[g.index] = ras.density(geoms)
    return out
