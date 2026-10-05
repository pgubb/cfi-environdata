# Data Dictionary: `heat_timeseries_yearly.csv`

Yearly heat metrics per city, each value a **spatial mean over that city's entire sampling grid**. Produced by `python/extract_heat_timeseries.py`.

**Last generated:** 2026-10-05 — **430 rows**, 5 cities × 1940–2025, 19 columns.

A **third unit of analysis**, alongside the business and block tables. It answers *when across decades*; the block tables answer *where* and *when within the two-year study window*. The three must not be merged into one another.

---

## Columns

| Column | Years | Units | Description |
|---|---|---|---|
| `city`, `year` | — | — | Key. Complete calendar years only. |
| **UTCI — ERA5-HEAT, ~28 km** ||||
| `utci_max_c` | 1940– | °C | Peak UTCI: the highest daily-maximum UTCI of the year. |
| `utci_days_gt38c` | 1940– | days | Days of **very strong** heat stress (UTCI > 38 °C). |
| `utci_days_gt46c` | 1940– | days | Days of **extreme** heat stress (UTCI > 46 °C). |
| `mrt_dmax_mean_c` | 1940– | °C | Mean daily-peak mean radiant temperature. |
| **Air temperature — ERA5-Land, ~11 km** ||||
| `t2m_max_c` | 1951– | °C | Highest daily-maximum 2 m air temperature of the year. |
| `wbgt_max_c` | 1951– | °C | Highest daily sWBGT of the year. |
| `wbgt_days_gt28c` | 1951– | days | Days above sWBGT 28 °C (ISO 7243 "high risk for heavy work"). |
| **LST — MODIS, 1 km. Emitted twice; see below** ||||
| `lst_frac_gt40c_terra` | 2001– | 0–1 | Share of observed days above 40 °C. **Terra only.** |
| `lst_max_c_terra` | 2001– | °C | Highest daytime LST. **Terra only.** |
| `lst_nights_frac_gt25c_terra` | 2001– | 0–1 | Share of observed nights above 25 °C. **Terra only.** |
| `lst_day_obs_terra`, `lst_night_obs_terra` | 2001– | count | Clear-sky observations behind the two shares. |
| `lst_frac_gt40c`, `lst_max_c`, `lst_nights_frac_gt25c` | 2003– | — | As above, **Terra + Aqua**. |
| `lst_day_obs`, `lst_night_obs` | 2003– | count | Observations behind the merged shares. |

Each metric is formed **per pixel and then averaged over the grid**. The other order — pooling exceedances and observations across the city first — would weight each pixel by how often it happened to be cloud-free.

**Only complete calendar years are emitted.** All four instruments carry data into 2026, but a partial year would depress every count and read as a sharp fall at the end of each series.

---

## ⚠ Read this before plotting a trend

### 1. Never use the merged LST columns for a trend

Aqua starts in mid-2002 and its ~13:30 overpass catches afternoon peaks that Terra's ~10:30 never reaches. A merged series therefore **steps up in 2003 for purely instrumental reasons**. Measured here:

| City | Terra 2001–02 | merged 2003–04 | apparent rise | of which instrument |
|---|---|---|---|---|
| Addis Ababa | 41.2 | 47.1 | +5.9 °C | **+5.5 °C** |
| Sao Paulo | 40.8 | 45.3 | +4.5 °C | **+4.2 °C** |
| Lagos | 34.9 | 38.0 | +3.0 °C | +2.5 °C |
| Delhi | 46.9 | 49.7 | +2.9 °C | +2.4 °C |
| Jakarta | 43.3 | 45.4 | +2.1 °C | +2.7 °C |

In Addis Ababa **93% of the apparent warming is the second satellite arriving.** Use `*_terra` for any trend, slope or before/after claim; use the merged columns for levels only, where they are the better estimate of a true peak.

### 2. The LST columns show a spurious cooling after 2020 — both satellites are drifting

Terra-only maximum LST, change against its own 2016–2020 baseline:

| City | 2021 | 2022 | 2023 | 2024 | **2025** |
|---|---|---|---|---|---|
| Addis Ababa | +0.7 | −0.8 | −4.8 | −5.4 | **−6.2** |
| Delhi | −3.8 | −1.6 | −5.1 | −2.6 | **−7.6** |
| Jakarta | −0.6 | −1.4 | +0.1 | −2.7 | **−6.1** |
| Sao Paulo | −1.6 | −1.7 | −0.3 | −4.1 | **−5.2** |
| Lagos | +0.6 | −1.1 | +0.5 | +0.1 | **−3.2** |

Stable to 2020, then worsening monotonically to a 3–8 °C deficit by 2025, in **all five cities on three continents**. ERA5 air temperature over the same years does not fall. **This is an instrument artefact, and the cause is documented.**

**Both MODIS platforms have left their maintained orbits, and both are drifting away from peak surface heating:**

| | nominal | last maneuver | then | by |
|---|---|---|---|---|
| **Terra** | 10:30 MLT | 2020 | drifts **earlier** — 10:15 by Oct 2022 | ~09:00 Dec 2025 |
| **Aqua** | 13:30 MLT | Mar 2021 | drifts **later** — past 13:45 by Feb 2023 | ~15:50 Aug 2026 |

Terra moves back toward morning and Aqua forward into late afternoon, so **each samples further from the daily maximum every year**. That is why the decline appears in the merged series too, which had been the one thing Terra drift alone could not explain — they are drifting in opposite directions but with the same effect on a maximum.

**This is a sampling artefact, not a calibration failure.** The surface genuinely is cooler at 09:00 than at 10:30; the instrument is reporting correctly, it is simply no longer measuring the same time of day. (The separately documented MODIS calibration degradation from 2023 affects the *reflective solar* bands and products like ocean colour; LST uses thermal emissive bands calibrated against an onboard blackbody.)

Orbital drift producing spurious cooling in an LST record is a **well-established problem** — it is the classic artefact in the NOAA-AVHRR series, where later-drifting afternoon platforms introduced exactly this decreasing trend, and where correction methods based on reconstructing the diurnal cycle are standard. No such correction is applied here.

> **Restrict any LST trend to 2001–2020 and say so.** Do not report cooling from these columns. For anything after 2020 the LST columns remain usable as a *cross-city level* comparison within a single year, since all cities are sampled at the same drifted time — but not as a time series.

Sources: [Terra orbital drift](https://terra.nasa.gov/about/terras-orbit-changes/terra-orbital-drift-information) · [Terra/Aqua orbit changes](https://nsidc.org/data/user-resources/data-announcements/ongoing-changes-terra-and-aqua-orbits-impacting-modis-snow-and-sea-ice-products) · [orbit drift and MODIS observations](https://ntrs.nasa.gov/api/citations/20240001409/downloads/2023_SPIE_Twedt_MODIS_EV_orbit_drift_manuscript_v4.pdf) · [AVHRR drift correction](https://doi.org/10.3390/rs11232843)

### 3. Use the ERA5 metrics for the long view, with their own caveat

They are the only series spanning decades, they are internally consistent by construction, and they show what you would expect — days above a heat-stress threshold rising in the tropical cities:

| City | UTCI days >38 | sWBGT days >28 | air max |
|---|---|---|---|
| Lagos | **+8.0** | **+4.8** | +0.21 |
| Jakarta | **+7.6** | +2.0 | +0.10 |
| Delhi | +0.7 | +2.4 | −0.21 |
| Sao Paulo | +0.1 | +0.5 | +0.19 |
| Addis Ababa | 0.0 | 0.0 | +0.21 |

*(change per decade; UTCI from 1940, sWBGT and air from 1951)*

Their caveat is the opposite of the satellites': **they are modelled, not observed.** A 1940s value rests on far less observational input than a 2020s one while the series looks equally seamless. Early decades are better read as a plausible reconstruction than a measurement.

Note Delhi rises on *counts* while its *maximum* falls slightly — a maximum and a threshold count can diverge, and the counts are the more robust of the two.

---

## Recent levels, 2016–2025 mean

| City | UTCI max | UTCI d>38 | UTCI d>46 | air max | sWBGT d>28 | MRT peak | LST max (Terra) | LST frac>40 | LST nights frac>25 |
|---|---|---|---|---|---|---|---|---|---|
| Delhi | **48.3** | 159 | **14.1** | **43.8** | 152 | **55.0** | **46.1** | 0.10 | 0.31 |
| Lagos | 40.9 | 103 | 0 | 33.2 | **360** | 53.1 | 36.6 | 0.00 | 0.33 |
| Jakarta | 40.6 | 117 | 0 | 33.6 | **362** | 54.2 | 42.2 | **0.16** | **0.56** |
| Sao Paulo | 37.9 | 1 | 0 | 33.6 | 4 | 48.3 | 40.6 | 0.03 | 0.01 |
| Addis Ababa | 31.2 | 0 | 0 | 27.1 | 0 | 47.4 | 39.0 | 0.01 | 0.00 |

**Delhi is the only city reaching extreme heat stress** (14 days a year above UTCI 46 °C) and leads on every peak measure. **Jakarta and Lagos lead on duration** — about 360 days a year above sWBGT 28 °C, essentially permanent — while never reaching Delhi's extremes. Two different hazards, and a single metric would hide one of them.

---

## Method notes

**Geometry.** Each city's sampling grid is dissolved into one multipolygon and simplified by 0.001° (~100 m), which halves the vertex count with no measurable change in area. Grids are not contiguous — 38 to 593 separate parts per city.

**Reduction scale is 1 km for every group**, including the 11 km and 28 km products. The Lagos grid is ~200 km², smaller than a single 28 km cell, and reducing coarser than the geometry risks returning nothing — the hazard that left whole columns empty in the block pipeline. Sampling a coarse product finely only repeats cell values; it is safe here because every metric is a mean or a per-pixel count, never a `pixelArea`-derived density.

**No incremental cache.** Unlike the other pipelines this recomputes in full, about 90 minutes. There is no fingerprint, so a change to the code or config will not invalidate anything — regenerate deliberately.

**No coastal fill** is applied to ERA5-Land here, unlike indicators 11 and 15. The spatial mean uses whatever land cells the grid overlaps, which is the natural reading of "average across the sampling grid"; a few Lagos lagoon cells are simply excluded.
