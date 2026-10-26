# pse-opendata

Unofficial Python client for the public data of **PSE S.A.**, the Polish transmission system operator. It reads the
reports API [api.raporty.pse.pl](https://api.raporty.pse.pl) (from 14 June 2024) and the legacy CSV export of
www.pse.pl (hourly history until 13 June 2024) and returns tidy `pandas` frames with explicit interval times.

!!! note "Not an official PSE product"
    This is an independent open-source project, not affiliated with, endorsed by or supported by PSE S.A.
    Check the [terms of use](#data-and-terms-of-use) of PSE data before publishing results.

```python
import pse_opendata as pse

rce = pse.rce("2025-01-01", "2025-01-31")
rce.head(1)
```

```text
                  start_utc                   end_utc               start_local                 end_local business_date  rce_pln
0 2024-12-31 23:00:00+00:00 2024-12-31 23:15:00+00:00 2025-01-01 00:00:00+01:00 2025-01-01 00:15:00+01:00    2025-01-01    16.26
```

## What it does

- **One call per report**: `pse.get(report, start, end)` for any of the [catalogued reports](reports.md), plus
  `rce`, `sdac`, `fundamentals` (demand and generation), `imbalance_prices` and `balancing_capacity`.
- **Explicit time**: interval start and end in UTC and in Europe/Warsaw, and the business date, on every row.
  The API's end-of-interval stamps, DST days and the legacy `2A` hour are handled (see
  [pitfalls](pitfalls.md)).
- **History**: hourly legacy reports for 2009-2024 and stitched series (`pse.history("demand", ...)`) across the
  switch to the new API (see [history](history.md)).
- **Reliable downloads**: monthly Parquet cache that knows how long PSE keeps correcting each report, retries
  with backoff, request spacing, offline mode and clear exceptions (see [cache](caching.md)).
- **Command line**: `pse-opendata get rce-pln --start 2025-01-01 --end 2025-01-31 --out rce.parquet`.

## Data and terms of use

The data are public reports of PSE S.A. PSE's conditions for re-using public sector information
([BIP](https://www.pse.pl/bip/ponowne-wykorzystanie-informacji-publicznej), checked on 26 October 2026) allow
commercial and non-commercial re-use free of charge if you name the source and the date the information was
obtained, remove the PSE logo and, for processed information, say that it was processed and how. See the
[README](https://github.com/kwwaleszczynski-del/pse-opendata#data-source-and-terms-of-use) for the full summary and
an attribution example.
