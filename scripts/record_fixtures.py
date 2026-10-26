"""Record real PSE responses used by the offline tests (tests/fixtures).

Responses are trimmed to the fields the tests need. Legacy export files are stored byte for byte (cp1250).
The legacy server rate-limits, so legacy requests are spaced by ``--pause`` seconds.

Usage:
    python scripts/record_fixtures.py               # API and legacy fixtures
    python scripts/record_fixtures.py --only api
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
API = "https://api.raporty.pse.pl/api"
LEGACY = "https://www.pse.pl/getcsv/-/export/csv/{code}/data_od/{start}/data_do/{end}"
HEADERS = {"User-Agent": "pse-opendata fixture recorder (+https://github.com/kwwaleszczynski-del/pse-opendata)"}
log = logging.getLogger("record_fixtures")

# name -> (endpoint, OData filter, fields, page size)
API_FIXTURES = {
    "rce-pln_2025-10-26": ("rce-pln", "business_date eq '2025-10-26'", ["rce_pln"], 20000),
    "rce-pln_2025-03-30": ("rce-pln", "business_date eq '2025-03-30'", ["rce_pln"], 20000),
    "rce-pln_2025-09-30_2025-10-01": ("rce-pln", "business_date ge '2025-09-30' and business_date le '2025-10-01'",
                                      ["rce_pln"], 20000),
    "rce-pln_2025-10-02_paged": ("rce-pln", "business_date eq '2025-10-02'", ["rce_pln"], 40),
    "cmbp-tp_2025-10-26": ("cmbp-tp", "business_date eq '2025-10-26'", ["afrr_g", "afrr_d", "rr_d"], 20000),
    "cmbp-tp_2025-03-30": ("cmbp-tp", "business_date eq '2025-03-30'", ["afrr_g", "afrr_d", "rr_d"], 20000),
    "his-wlk-cal_2024-06-13_2024-06-14": ("his-wlk-cal",
                                          "business_date ge '2024-06-13' and business_date le '2024-06-14'",
                                          ["demand", "wi", "pv"], 20000),
    "his-wlk-cal_2024-06-14_2024-06-27": ("his-wlk-cal",
                                          "business_date ge '2024-06-14' and business_date le '2024-06-27'",
                                          ["demand"], 20000),
    "his-wlk-cal_2026-10-26_partial": ("his-wlk-cal", "business_date eq '2026-10-26'", ["demand", "wi", "pv"], 20000),
    "popmb-rmb_2025-10-02_first_hour": ("popmb-rmb", "dtime_utc eq '2025-10-01 23:00:00'",
                                        ["reserve_type", "pom", "com", "comrr"], 20000),
    "przeplywy-mocy_2025-10-02_first_interval": ("przeplywy-mocy", "dtime_utc eq '2025-10-01 22:15:00'",
                                                 ["section_code", "value"], 20000),
    "poze-redoze_2024-09-24_first_rows": ("poze-redoze", "business_date eq '2024-09-24'",
                                          ["pv_red_balance", "wi_red_network"], 4),
}

# name -> (code, first day, last day)
LEGACY_FIXTURES = {
    "PL_WYK_KSE_2023-10-28_2023-10-30": ("PL_WYK_KSE", "20231028", "20231030"),
    "PL_WYK_KSE_2023-03-25_2023-03-27": ("PL_WYK_KSE", "20230325", "20230327"),
    "PL_WYK_KSE_2010-01-01_2010-01-03": ("PL_WYK_KSE", "20100101", "20100103"),
    "PL_WYK_KSE_2024-05-29_2024-06-13": ("PL_WYK_KSE", "20240529", "20240613"),
    "PL_WYK_KSE_2008-01-01_2008-01-03_404": ("PL_WYK_KSE", "20080101", "20080103"),
    "PL_GEN_WIATR_2023-10-28_2023-10-30": ("PL_GEN_WIATR", "20231028", "20231030"),
    "PL_GEN_WIATR_2020-04-09_2020-04-11": ("PL_GEN_WIATR", "20200409", "20200411"),
    "PL_CENY_RYN_EN_2023-10-28_2023-10-30": ("PL_CENY_RYN_EN", "20231028", "20231030"),
    "PL_CENY_ROZL_RB_2023-10-28_2023-10-30": ("PL_CENY_ROZL_RB", "20231028", "20231030"),
    "PL_CENY_ROZL_RB_2019-01-01_2019-01-03": ("PL_CENY_ROZL_RB", "20190101", "20190103"),
}


def record_api(session: requests.Session) -> None:
    for name, (endpoint, flt, fields, first) in API_FIXTURES.items():
        params = {"$filter": flt, "$select": ",".join(["dtime_utc", "business_date", *fields]), "$first": first}
        url, pages = f"{API}/{endpoint}", []
        while url:
            r = session.get(url, params=params, headers=HEADERS, timeout=120)
            r.raise_for_status()
            payload = r.json()
            pages.append(payload)
            url, params = payload.get("nextLink"), None
            if name == "poze-redoze_2024-09-24_first_rows" or len(pages) >= 3:
                break   # a few pages are enough
        path = ROOT / "api" / f"{name}.json"
        path.write_text(json.dumps({"endpoint": endpoint, "filter": flt, "pages": pages}, ensure_ascii=False),
                        encoding="utf-8")
        log.info("%s: %d pages, %d rows", name, len(pages), sum(len(p["value"]) for p in pages))
        time.sleep(1)


def record_legacy(session: requests.Session, pause: float) -> None:
    for name, (code, start, end) in LEGACY_FIXTURES.items():
        path = ROOT / "legacy" / f"{name}.csv"
        if path.exists():
            continue
        r = session.get(LEGACY.format(code=code, start=start, end=end), headers=HEADERS, timeout=300)
        if r.status_code == 429:
            raise SystemExit("HTTP 429 from the legacy export; wait a few minutes and run again")
        path.write_bytes(r.content)
        log.info("%s: HTTP %d, %d bytes", name, r.status_code, len(r.content))
        time.sleep(pause)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=["api", "legacy"])
    parser.add_argument("--pause", type=float, default=30.0, help="seconds between legacy requests")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    (ROOT / "api").mkdir(parents=True, exist_ok=True)
    (ROOT / "legacy").mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    if args.only in (None, "api"):
        record_api(session)
    if args.only in (None, "legacy"):
        record_legacy(session, args.pause)


if __name__ == "__main__":
    main()
