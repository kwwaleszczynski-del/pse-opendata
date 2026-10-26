# pse-opendata

[![tests](https://github.com/kwwaleszczynski-del/pse-opendata/actions/workflows/ci.yml/badge.svg)](https://github.com/kwwaleszczynski-del/pse-opendata/actions/workflows/ci.yml)
[![docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://kwwaleszczynski-del.github.io/pse-opendata/)

Unofficial Python client for the public data of **PSE S.A.**, the Polish transmission system operator: market
prices (RCE, SDAC), demand and generation, the balancing market (imbalance prices, balancing capacity, offers),
cross-border flows and redispatch of renewables. It returns tidy `pandas` frames with explicit interval start and
end times in UTC and Polish local time, caches monthly Parquet files and also reads the legacy CSV export that holds
the history before June 2024.

> This is an independent open-source project. It is not affiliated with, endorsed by or supported by PSE S.A.

## Why

PSE publishes its data openly at [api.raporty.pse.pl](https://api.raporty.pse.pl) (from 14 June 2024) and, for
earlier years, through the CSV export of [www.pse.pl](https://www.pse.pl/raporty-historyczne). Both are easy to
download and easy to get subtly wrong:

- `dtime_utc` is the **end** of each interval, not the start; local `dtime` reads `02a:15` on the autumn DST day;
- the API pages with `$first` and `nextLink`, at most 100,000 rows per page, and its keyset paging **skips rows**
  of the balancing capacity offers (`popmb-rmb`) at page boundaries;
- RCE and SDAC were hourly products until 30 September 2025: the API repeats the hourly price in four quarter-hours;
- settlement reports are republished for months after the fact (imbalance volumes up to ~230 days later);
- the legacy export is slow, rate-limited, takes one month per request, labels the extra autumn hour `2A`, changes
  its columns over the years and does not overlap with the API, whose demand sits ~0.7% below it at the switch.

`pse-opendata` handles these once, with tests on recorded responses, instead of a copy of a small client in every
analysis project. Details: [time and data pitfalls](https://kwwaleszczynski-del.github.io/pse-opendata/pitfalls/).

## Install

Python 3.11 or newer. The package is not on PyPI yet; install it from GitHub:

```bash
pip install "pse-opendata @ git+https://github.com/kwwaleszczynski-del/pse-opendata"
```

## Quick start

```python
import pse_opendata as pse

rce = pse.rce("2025-01-01", "2025-01-31")                    # RCE price, PLN/MWh, 15-minute rows
mix = pse.fundamentals("2025-06-01", "2025-06-30", fields=["demand", "wi", "pv"])   # MW
cen = pse.imbalance_prices("2025-07-01", "2025-07-31")       # imbalance price CEN and balancing energy prices
cap = pse.balancing_capacity("2025-07-01", "2025-07-31")     # FCR/aFRR/mFRRd/RR prices and MW, hourly
sdac = pse.get("csdac-pln", "2025-10-01", "2025-10-07")      # any catalogued report by name

demand = pse.history("demand", "2024-01-01", "2024-12-31")   # legacy export + API, hourly, one series
```

Every frame has the same time columns, one row per interval:

| column | meaning |
|---|---|
| `start_utc`, `end_utc` | interval start and end, `datetime64[ns, UTC]` |
| `start_local`, `end_local` | the same instants in `Europe/Warsaw` (DST days are unambiguous) |
| `business_date` | trading day in Polish local time (`datetime.date`) |

followed by row keys (for reports with several rows per interval) and the fields of the report, with PSE's field
names (e.g. `rce_pln`, `demand`, `wi`, `pv`, `cen_cost`). Dates are business days, inclusive.

From the command line:

```bash
pse-opendata get rce-pln --start 2025-01-01 --end 2025-01-31 --out rce.parquet
pse-opendata get his-wlk-cal --start 2025-06-01 --fields demand,wi,pv --out mix.csv
pse-opendata history demand --start 2024-01-01 --end 2024-12-31 --out demand.parquet
pse-opendata reports
```

## Catalogue

| Report | Content | Resolution | From |
|---|---|---|---|
| `rce-pln` | RCE, market price of electricity | 15 min (hourly product until 2025-09-30) | 2024-06-14 |
| `csdac-pln` | SDAC day-ahead price for Poland | 15 min (hourly product until 2025-09-30) | 2024-06-14 |
| `crb-rozl` | Imbalance price CEN and balancing energy prices | 15 min | 2024-06-14 |
| `en-rozl` | Imbalance energy volumes | 15 min | 2024-06-14 |
| `eb-rozl` | Activated balancing energy, incl. aFRR platform | 15 min | 2024-06-14 |
| `cmbp-tp`, `mbp-tp` | Balancing capacity prices and volumes, primary procurement | 1 h | 2024-06-14 |
| `cmbu-tu`, `mbu-tu` | Balancing capacity prices and volumes, supplementary procurement | 15 min | 2024-06-14 |
| `popmb-rmb` | Anonymous portfolio offers for balancing capacity | 1 h, many rows | 2024-06-14 |
| `his-wlk-cal` | Demand, generation by unit type, wind, PV, exchange | 15 min | 2024-06-14 |
| `kse-load` | Forecast and actual load | 15 min | 2024-06-14 |
| `pdgopkd` | Day-ahead coordinated plan (forecast demand, wind, PV, reserves) | 15 min | 2024-06-14 |
| `poze-redoze` | Non-market redispatch of wind and PV | 15 min | 2024-09-24 |
| `przeplywy-mocy` | Physical cross-border flows per section | 15 min, many rows | 2024-06-14 |
| `gen-jw` | Generation per unit (≥ 100 MW) | 15 min, many rows | 2024-06-14 |

Legacy export (hourly, until 2024-06-13): `PL_WYK_KSE` (demand, JWCD/nJWCD generation, exchange, from 2009),
`PL_GEN_WIATR` (wind from 2012-05-26, PV from 2020-04-10), `PL_CENY_RYN_EN` (RCE, from 2018),
`PL_CENY_ROZL_RB` (imbalance prices CRO of the old balancing market, from 2009). The legacy server is slow (about a
minute per month, one month per request), so long histories take a while the first time and are then cached.
Field descriptions, units, sources and notes for each report:
[report catalogue](https://kwwaleszczynski-del.github.io/pse-opendata/reports/). Other endpoints of the API can
be read raw with `pse.Client().records(endpoint, filter=...)`.

## Cache and reliability

- Whole months are cached as Parquet files (`$PSE_OPENDATA_CACHE` or the user cache directory; `Client(cache_dir=...)`
  to choose, `cache_dir=None` to switch off). A month is reused only once it was downloaded after the report's
  revision window (3 days for prices, up to 240 days for settlement volumes); the legacy history never changes.
- Requests retry with exponential backoff on network errors, HTTP 429 and 5xx (honouring `Retry-After`) and are
  spaced (0.2 s for the API, 15 s for the legacy export).
- `offline=True` reads the cache only; `allow_stale=True` falls back to a cached copy when a download fails.
- Errors are explicit: `PseApiError` (with the API's message), `UnknownReportError`, `UnknownFieldError`,
  `CacheMissError`, `LegacyFormatError`. Logging goes to the `pse_opendata` logger.

## Data source and terms of use

All data come from public reports of **PSE S.A.** (Polskie Sieci Elektroenergetyczne): the reports API
`https://api.raporty.pse.pl/api` and the export of www.pse.pl. No key is needed. This package does not include or
redistribute PSE data, except small samples of real responses used as test fixtures (see
[tests/fixtures/README.md](tests/fixtures/README.md)).

PSE publishes conditions for re-using public sector information
([BIP, "Ponowne wykorzystywanie informacji sektora publicznego"](https://www.pse.pl/bip/ponowne-wykorzystanie-informacji-publicznej),
entry changed on 14 October 2026, checked on 26 October 2026). They allow commercial and non-commercial re-use of
information published in the BIP and on www.pse.pl free of charge, on condition that you name the source and the date
the information was obtained (e.g. "Informacja pozyskana od PSE S.A. według stanu strony www.pse.pl na dzień
[data]"), remove the PSE logo, keep unchanged information unchanged and, when you pass on processed information, tell
recipients that it was changed and how, without misleading them. PSE accepts no liability for processed information,
and some materials may be protected by copyright or database rights. The conditions are written for www.pse.pl;
the reports API is run by the same operator. When you publish results built with this package, add the attribution
yourself, for example:

> Information obtained from www.pse.pl (PSE S.A. report `rce-pln`), state as of [date]. The information has been
> processed in whole or in part.

## Documentation and development

Documentation: <https://kwwaleszczynski-del.github.io/pse-opendata/> (installation, examples, catalogue, time
pitfalls, API reference). To work on the package:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,docs]"     # Linux/macOS: .venv/bin/python
pytest -q                                                 # offline, recorded responses
pytest -q --live tests/live                               # optional: calls the real PSE servers
ruff check .
mypy
mkdocs build --strict
```

## License

Code: MIT, see [LICENSE](LICENSE). Data: PSE S.A. public reports, see
[Data source and terms of use](#data-source-and-terms-of-use).
