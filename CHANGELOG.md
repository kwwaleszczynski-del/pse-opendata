# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/).

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

[0.2.0]: https://github.com/kwwaleszczynski-del/pse-opendata/releases/tag/v0.2.0
[0.1.0]: https://github.com/kwwaleszczynski-del/pse-opendata/tree/8b01ec882b6f3af9c9ea91308293dda64108d705
