# Time and data pitfalls

What goes wrong when reading PSE data by hand, and what this package does about it. Everything below was checked
against the live API and the legacy export on 26 October 2026.

## The API stamps the end of the interval

Each row of the reports API carries `dtime_utc`, the **end** of its interval in UTC, and `business_date`, the
trading day. For the first quarter-hour of 26 October 2025 (00:00-00:15 Polish time) the API returns
`dtime_utc = "2025-10-25 22:15:00"`. Treating `dtime_utc` as the start shifts every series by one interval
(15 minutes, or one hour for hourly reports such as `cmbp-tp`).

The package computes the start as end minus the report resolution and returns both, in UTC and in Polish time:

| column | first quarter-hour of 2025-10-26 |
|---|---|
| `start_utc` | 2025-10-25 22:00:00+00:00 |
| `end_utc` | 2025-10-25 22:15:00+00:00 |
| `start_local` | 2025-10-26 00:00:00+02:00 |
| `end_local` | 2025-10-26 00:15:00+02:00 |
| `business_date` | 2025-10-26 |

`business_date` is the local date of the interval start. A consequence of end stamps: for `his-wlk-cal`,
`kse-load`, `cmbu-tu` and `mbu-tu` the API also returns the last quarter-hour of business date 2024-06-13
(stamped `2024-06-13 22:00:00` UTC). The package starts these reports on 2024-06-14 like the others.

## Daylight saving time

- The autumn day has 100 quarter-hours (25 hours), the spring day 92 (23 hours). Hourly reports have 25 and 23 rows.
- The local text fields `dtime` and `period` are ambiguous or broken on the autumn day: the repeated hour is written
  `02a:15`, and one period reads `03:00 - 02a:15`. Only `dtime_utc` is unambiguous; the package ignores the text
  fields.
- `start_local` and `end_local` are tz-aware, so the two 02:00 hours of the autumn day are different values
  (`02:00+02:00` and `02:00+01:00`).
- In the legacy export the extra autumn hour is labelled `2A` and the spring day has no hour `2`. Rows are placed
  by their label (`1, 2, 2A, 3, ...`), so a missing row leaves a gap instead of shifting the rest of the day.

## Paging

The API follows OData conventions of Microsoft Data API builder: `$filter`, `$select`, `$orderby`, `$first` and a
`nextLink` with an opaque `$after` cursor.

- Without `$first` a page has **100 rows**; the largest accepted `$first` is **100,000** (more gives HTTP 400). The
  package asks for 20,000 rows per page and follows `nextLink` until the end, refusing to loop.
- The cursor is a keyset over the entity key (for most reports `dtime_utc`). For the anonymous balancing capacity
  offers `popmb-rmb` the key is `(dtime_utc, pom, com, comrr, reserve_type)`, but identical offers exist and some
  fields are empty, and the cursor **skips rows at page boundaries**: 8 of 8,286 rows of 2025-10-02 were lost with
  1,000-row pages, 26 with 250-row pages. The package requests such reports one business date at a time in one
  page and keeps identical rows. Paging of `gen-jw`, `przeplywy-mocy`, `his-wlk-cal` and `crb-rozl` was checked
  complete.
- Unknown fields or reports give HTTP 400/404 with a JSON error; the message is passed on in `PseApiError`.

## Hourly products in quarter-hour rows

RCE (`rce-pln`) and the SDAC price (`csdac-pln`) were hourly until delivery day 30 September 2025, but the API
returns 96 rows per day since June 2024: the hourly price is repeated in the four quarter-hours. Quarter-hourly
prices start on 1 October 2025. `pse.to_hourly(frame)` averages complete hours, which gives the hourly price before
October 2025 and the mean of the four quarter-hour prices after.

## Revisions

Some reports are republished after corrections. The latest republication of each month, observed for September
2025 to October 2026:

| Report | Last republication after the month end |
|---|---|
| `rce-pln`, `csdac-pln`, `cmbp-tp`, `mbp-tp`, `pdgopkd`, `popmb-rmb` | none (published before delivery) |
| `cmbu-tu`, `mbu-tu` | about 1 day |
| `his-wlk-cal`, `kse-load`, `przeplywy-mocy`, `gen-jw` | usually 1 day; up to about 31 days, plus a bulk republication of 2024-2025 data on 2026-01-18 |
| `crb-rozl`, `eb-rozl` | about 46-48 days, once 106 days |
| `poze-redoze` | up to about 70 days |
| `en-rozl` | in steps of about 48, 108 and 228 days |

The cache uses these windows (`Report.revision_days`) so a month is not frozen before PSE stops correcting it.
For backtests where the information available at a past moment matters, note that the API only serves the latest
version of each row.

## Stitching the legacy export and the API

- The two sources do not overlap: the legacy export ends on 2024-06-13 and the API starts on 2024-06-14. The seam is
  local midnight of 14 June 2024 (2024-06-13 22:00 UTC).
- Time stamps: legacy hour `1` is 00:00-01:00 local time; the API stamps quarter-hour ends in UTC. Using the
  legacy hour label as a start in UTC, or the API end as a start, shifts one side by one or two hours. Both are
  converted to interval starts here.
- Level: API demand (`his-wlk-cal` `demand`, identical to `kse-load` `load_actual`) runs below the legacy
  "Krajowe zapotrzebowanie na moc"; matched by weekday and hour over two weeks either side of the seam the ratio is
  about 1.007. `pse.history(..., rescale=True)` applies it; by default nothing is rescaled. See
  [history](history.md).
- The imbalance price changed with the market reform: legacy `CRO` and API `cen_cost` (CEN) are not stitched.

## Legacy export limits

- One calendar month per request at most: longer ranges get HTTP 429. One-day ranges are rejected; the package
  widens them to two days and trims the result.
- The server takes about a minute for a month and answers HTTP 429 to quick series of requests. The package waits
  15 seconds between requests and backs off on 429.
- Files are cp1250 with `;` separators and decimal commas; missing values are `-`. Dates are `YYYY-MM-DD` in some
  reports and `YYYYMMDD` in others. Columns change over time (`Generacja PI` and `Generacja IRZ` until 2020,
  `COR` in the price report until 2020).

## pandas versions

Time columns are always `datetime64[ns, tz]`, whichever resolution pandas used when parsing (pandas 3 parses text
to microseconds by default). Cached files written with one pandas version read the same with another.
