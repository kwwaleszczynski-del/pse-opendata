# History before 2024

The reports API starts on 14 June 2024, together with the reformed balancing market. Older data are in the export
of the previous PSE data service, kept on the [archive pages](https://www.pse.pl/raporty-historyczne) of www.pse.pl.

## Legacy reports

```python
import pse_opendata as pse

kse = pse.legacy("PL_WYK_KSE", "2023-10-01", "2023-12-31")      # hourly, until 2024-06-13
wind_pv = pse.legacy("PL_GEN_WIATR", "2023-10-01", "2023-12-31")
rce_hourly = pse.legacy("PL_CENY_RYN_EN", "2023-10-01", "2023-12-31")
```

| Code | Content | From |
|---|---|---|
| `PL_WYK_KSE` | Demand, generation of JWCD and nJWCD, exchange balance | 2009-01-01 |
| `PL_GEN_WIATR` | Wind and PV generation (PV from 2020-04-10) | 2012-05-26 |
| `PL_CENY_RYN_EN` | RCE, hourly | 2018-01-01 |
| `PL_CENY_ROZL_RB` | Imbalance settlement prices CRO, CROs, CROz of the old market | 2009-01-01 |

The frames have the same columns as API frames (`start_utc`, `end_utc`, `start_local`, `end_local`,
`business_date`, then the fields), with hourly intervals.

### Limitations

- **Slow and rate-limited.** About one minute per month, one month per request, 15 seconds between requests; HTTP
  429 if you ask for more. Ten years of one report take a few hours the first time. Months are cached permanently
  (the history no longer changes), so this happens once.
- **Units are not stated** in the export. MW for power and PLN/MWh for prices are inferred and marked unverified in
  the catalogue.
- **Columns changed over time** (e.g. `Generacja PI` and `Generacja IRZ` until 2020); missing columns come back as
  NaN. Their meaning is not explained in the export.
- **Source gaps** are kept as gaps: a missing hour is absent, nothing is interpolated.
- **DST**: rows are placed by their hour label (`1`, `2`, `2A`, `3`, ...) assuming the file lists the hours of a day
  in time order. There is no overlap with the API to check this against independent data.

## Stitched series

`pse.history(series, start, end)` returns one hourly series across the switch:

| Series | Legacy part | API part |
|---|---|---|
| `rce` | `PL_CENY_RYN_EN` `rce` | `rce-pln` `rce_pln`, hourly mean |
| `demand` | `PL_WYK_KSE` `demand` | `his-wlk-cal` `demand`, hourly mean |
| `wind` | `PL_GEN_WIATR` `wind` | `his-wlk-cal` `wi`, hourly mean |
| `pv` | `PL_GEN_WIATR` `pv` | `his-wlk-cal` `pv`, hourly mean |

```python
demand = pse.history("demand", "2024-01-01", "2024-12-31")
demand.groupby("source")["demand"].mean()
```

The frame has the five time columns, the series and `source` (`"legacy"` or `"api"`). API hours are means of the
four quarter-hours and are empty when a quarter-hour is missing.

### Level difference at the seam

The two sources are not guaranteed to measure the same thing. For demand, the API runs about 0.7% below the legacy
export around the switch (weekday-and-hour matched means over two weeks either side). `rescale=True` multiplies the
API part by that ratio, computed by `pse.splice_factor`, and stores it in `frame.attrs["splice_factor"]`:

```python
scaled = pse.history("demand", "2024-01-01", "2024-12-31", rescale=True)
scaled.attrs["splice_factor"]
```

Whether to rescale depends on the analysis; the default leaves both sources as published.
