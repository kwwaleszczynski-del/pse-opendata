# Examples

Outputs below come from real runs on 26 October 2026.

## One report

```python
import pse_opendata as pse

rce = pse.rce("2025-01-01", "2025-01-31")       # same as pse.get("rce-pln", "2025-01-01", "2025-01-31")
rce.head(3)
```

```text
                  start_utc                   end_utc               start_local                 end_local business_date  rce_pln
0 2024-12-31 23:00:00+00:00 2024-12-31 23:15:00+00:00 2025-01-01 00:00:00+01:00 2025-01-01 00:15:00+01:00    2025-01-01    16.26
1 2024-12-31 23:15:00+00:00 2024-12-31 23:30:00+00:00 2025-01-01 00:15:00+01:00 2025-01-01 00:30:00+01:00    2025-01-01    16.26
2 2024-12-31 23:30:00+00:00 2024-12-31 23:45:00+00:00 2025-01-01 00:30:00+01:00 2025-01-01 00:45:00+01:00    2025-01-01    16.26
```

2,976 rows (31 days of 96 quarter-hours). `end` is optional; `pse.rce("2025-01-01")` returns one day. Dates are
business days in Polish local time, inclusive, given as `"YYYY-MM-DD"`, `datetime.date`, `datetime` or
`pandas.Timestamp`; a time zone-aware value is converted to Polish time first.

## Selected fields

```python
mix = pse.fundamentals("2025-06-01", "2025-06-30", fields=["demand", "wi", "pv"])
mix.columns.tolist()
# ['start_utc', 'end_utc', 'start_local', 'end_local', 'business_date', 'demand', 'wi', 'pv']
round(mix["pv"].sum() / 4 / 1000, 1)        # MW in 15-minute intervals -> GWh
# 2577.1
```

`pse.reports()` lists the reports and `pse.get_report("his-wlk-cal").fields` the fields with descriptions and units.

## Hourly and daily values

```python
hourly = pse.to_hourly(rce)                  # complete hours only, others NaN
daily = rce.groupby("business_date")["rce_pln"].mean()
daily.head(3)
```

```text
business_date
2025-01-01    -47.61875
2025-01-02    328.04375
2025-01-03    386.03375
```

Group by `business_date` or by `start_local` for Polish days, months or hours of the day; use `start_utc` to join
with other UTC data.

## Balancing market

```python
cen = pse.imbalance_prices("2025-07-01", "2025-07-31")       # cen_cost, ckoeb_cost, ceb_sr_cost, ...
cap = pse.balancing_capacity("2025-07-01", "2025-07-31")     # hourly, primary procurement
cap.iloc[:2, 5:9]
```

```text
   fcr_g_price  fcr_g_mw  fcr_d_price  fcr_d_mw
0       110.94     171.0        18.22     171.0
1        77.50     171.0        18.22     171.0
```

`balancing_capacity(..., procurement="supplementary")` gives the 15-minute supplementary procurement. The
anonymous offers behind the primary procurement are in `pse.get("popmb-rmb", day)`, several thousand rows per day,
sorted by product and price.

## Settings and cache

```python
client = pse.Client(cache_dir="data/pse", allow_stale=True)
sdac = client.sdac("2025-10-01", "2025-10-07")
pse.rce("2025-10-01", client=client)          # module functions accept a client too
```

See [cache and reliability](caching.md).

## History across 2024

```python
demand = pse.history("demand", "2024-01-01", "2024-12-31")
demand.groupby("source").size()
```

```text
source
api       4825
legacy    3959
```

8,784 hours, the whole leap year without gaps. The first call downloaded six months of the legacy export and took
5.5 minutes; the second took 0.1 s from the cache. With `rescale=True` the API part is multiplied by
`frame.attrs["splice_factor"]`, 1.0075 for demand. See [history](history.md).

## Any endpoint, raw

Reports outside the catalogue can be read as raw records (no parsing, no cache):

```python
rows = pse.Client().records("rcco2", filter="business_date ge '2025-01-01' and business_date le '2025-01-31'")
```

## Command line

```bash
pse-opendata get rce-pln --start 2025-01-01 --end 2025-01-31 --out rce.parquet
pse-opendata get his-wlk-cal --start 2025-06-01 --end 2025-06-30 --fields demand,wi,pv --out mix.csv
pse-opendata get crb-rozl --start 2025-07-01 --end 2025-07-31 --dropna --out cen.csv
pse-opendata legacy PL_CENY_RYN_EN --start 2023-10-01 --end 2023-10-31 --out rce_2023_10.parquet
pse-opendata history demand --start 2024-01-01 --end 2024-12-31 --out demand.parquet
pse-opendata reports --markdown
pse-opendata cache
```

Without `--out` the table goes to standard output as UTF-8 CSV; prefer `--out` for files (Windows PowerShell 5.1
re-encodes redirected output). Common options: `--cache-dir`, `--no-cache`, `--refresh`, `--offline`,
`--allow-stale`, `-v` (log requests).
