# Test fixtures

Real responses of the PSE servers, used by the offline tests and recorded with `scripts/record_fixtures.py`:

- `api/*.json`: pages of the reports API `https://api.raporty.pse.pl/api`, limited to a few days or a single
  interval and to the fields the tests need (`$select`);
- `legacy/*.csv`: files of the legacy export `https://www.pse.pl/getcsv/-/export/csv/...`, byte for byte
  (cp1250), including one HTML error page (`*_404.csv`).

Information obtained from www.pse.pl and api.raporty.pse.pl (PSE S.A. reports `rce-pln`, `cmbp-tp`, `his-wlk-cal`,
`popmb-rmb`, `przeplywy-mocy`, `poze-redoze`, `PL_WYK_KSE`, `PL_GEN_WIATR`, `PL_CENY_RYN_EN`, `PL_CENY_ROZL_RB`),
state as of 26 October 2026. The information has been processed in part: selected days, intervals and fields only.
It is not an official PSE publication. See the PSE conditions for re-use in the main README.
