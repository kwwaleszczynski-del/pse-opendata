# Cache and reliability

## Monthly cache

`pse.get` works month by month. When a request covers a whole month (or the whole part of it in which the report
has data), that month is downloaded and stored as one Parquet file:

```text
<cache_dir>/api/rce-pln/2025-01.parquet
<cache_dir>/legacy/PL_WYK_KSE/2023-10.parquet
```

Part of a month is downloaded on its own and not cached, so a one-day request stays a one-day request.

A cached month is reused only when it is **final**: it was downloaded at least `revision_days` days after the end of
the month. The window depends on the report (3 days for prices, 60 for system data, 120 for balancing settlement
prices, 240 for imbalance volumes; see the [catalogue](reports.md) and [revisions](pitfalls.md#revisions)). Until
then a request for the whole month downloads and stores it again, and a request for part of it downloads just
those days. Legacy months are always final. Empty months are never stored.

Each file stores the download time in its Parquet metadata, so copying the cache (e.g. between CI runs) keeps the
right state. Writes are atomic.

```python
import pse_opendata as pse

client = pse.Client(cache_dir="data/pse")            # own directory
client = pse.Client(cache_dir=None)                  # no cache
client = pse.Client(refresh=True)                    # download again, rewrite the cache
client = pse.Client(offline=True)                    # cache only; CacheMissError if a month is missing
client = pse.Client(allow_stale=True)                # if a download fails (PseError), use the cached copy
client = pse.Client(revision_days=10)                # one window for all reports
rce = client.rce("2025-01-01", "2025-12-31")
```

## Requests

- **Retries**: network errors (including a connection dropped mid-response), timeouts, HTTP 429 and any 5xx are
  retried 4 times with exponential backoff (2, 4, 8, 16 s for the API; 30 s and up for the legacy export), or as
  long as `Retry-After` asks. Other HTTP errors are raised at once.
- **Write errors**: if a cache file cannot be written (permissions, full disk), a warning is logged and the
  downloaded data are still returned.
- **`cache --clear`** deletes only the `api/` and `legacy/` sub-folders of the cache directory.
- **Spacing**: at least 0.2 s between API requests and 15 s between legacy requests (`min_interval`,
  `legacy_min_interval`).
- **Server errors on long ranges**: if a multi-day API request fails with a 5xx error, it is repeated day by day.
- **Paging**: see [paging](pitfalls.md#paging).

## Errors

All exceptions derive from `pse_opendata.PseError`:

| Exception | When |
|---|---|
| `PseApiError` | a request failed; `.status`, `.code` and the API's message |
| `UnknownReportError` | the report is not in the catalogue |
| `UnknownFieldError` | a requested field does not belong to the report |
| `CacheMissError` | offline mode and the month is not cached |
| `LegacyFormatError` | the legacy export returned something other than the expected CSV |

## Logging

The package logs to the `pse_opendata` logger: one INFO line per download, WARNING for retries, stale cache use
and unexpected data. Enable it with `logging.basicConfig(level=logging.INFO)` or `pse-opendata ... -v`.
