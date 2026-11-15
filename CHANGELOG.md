# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/).

## [0.2.1] - 2026-11-15

Fixes from an independent review. Default behaviour is unchanged except where noted under Changed.

### Added

- `net_flows(frame)`: net cross-border flow per neighbour from `przeplywy-mocy`, adding the two directional rows of
  each border (`X-PL` import >= 0, `PL-X` export <= 0); `UA_DOB` sections count as `UA`.
- `get(..., publication=True)` adds `publication_utc`, when PSE published each row (e.g. `kse-load` `load_fcst` is
  published with the actual load the next day).
- `Client(check_republished=True)`: before reusing final cached months, ask PSE for the latest publication time of
  their rows (usually one request per report and client) and download again months republished after the cached
  copy, such as the bulk republication of 2024-2025 data on 2026-01-18/19. Off by default in 0.2.x.
- `MonthLoad.complete`: `False` (with a warning) when a cached or stale copy was downloaded before the end of the
  requested days, e.g. a current-month file used offline.
- Cache files store the latest publication time of their rows; files written by 0.2.0 stay valid.

### Changed

- `to_hourly` raises `ValueError` for frames with several rows per interval and no `key` (it returned all-NaN
  values).
- Requests to the reports API also select `publication_ts_utc` (slightly larger responses); parsed frames and cache
  files carry a `publication_utc` column, which `get` returns only with `publication=True`.

### Fixed

- Catalogue: `przeplywy-mocy` `section_code` and `value` described one signed row per border; they are directional
  rows. `gen-jw` `value` now says that consumption (`operating_mode` "Pobór") is negative.
- Documentation: `Retry-After` waits are capped at `max_backoff` (120 s API, 600 s legacy export); the revisions
  section no longer claims the cache cannot freeze a month before PSE stops correcting it.

## [0.2.0] - 2026-10-31

First release on PyPI.

### Added

- `Client.loads`: one `MonthLoad` per month loaded (cached, downloaded or stale, with the download time and the
  number of rows), e.g. to show data freshness on a dashboard.
- `CITATION.cff` and Zenodo metadata.

### Changed

- Installation from PyPI (`pip install pse-opendata`) in the README and the documentation.

## [0.1.0] - 2026-10-26

First version, published on GitHub only (commit 8b01ec8), not on PyPI.

### Added

- `get(report, start, end)` for 16 reports of the PSE reports API (prices, balancing market, power system), returning
  frames with `start_utc`, `end_utc`, `start_local`, `end_local` and `business_date` on every row.
- Convenience functions `rce`, `sdac`, `fundamentals`, `imbalance_prices` and `balancing_capacity`.
- Report catalogue with titles, field descriptions, units, resolution, first date, revision window and PSE sources,
  checked on 2026-10-26; unconfirmed units are marked unverified.
- Legacy CSV export of www.pse.pl (`legacy`): `PL_WYK_KSE`, `PL_GEN_WIATR`, `PL_CENY_RYN_EN`, `PL_CENY_ROZL_RB`,
  hourly until 2024-06-13, with DST hour labels, changing columns and rate limits handled.
- `history` for hourly `rce`, `demand`, `wind` and `pv` series stitched across the switch to the API on 2024-06-14,
  with optional rescaling (`splice_factor`).
- Monthly Parquet cache with per-report revision windows, offline and stale modes; retries with backoff, request
  spacing, explicit exceptions and logging.
- Day-by-day single-page requests for `popmb-rmb`, whose keyset paging skips rows.
- Command line interface `pse-opendata` (`get`, `legacy`, `history`, `reports`, `cache`).
- Offline tests on recorded PSE responses, optional live tests, ruff, mypy, GitHub Actions for Python 3.11-3.13,
  MkDocs documentation and a release workflow for PyPI Trusted Publishing (disabled).

[0.2.1]: https://github.com/kwwaleszczynski-del/pse-opendata/releases/tag/v0.2.1
[0.2.0]: https://github.com/kwwaleszczynski-del/pse-opendata/releases/tag/v0.2.0
[0.1.0]: https://github.com/kwwaleszczynski-del/pse-opendata/tree/8b01ec882b6f3af9c9ea91308293dda64108d705
