"""Catalogue of the supported PSE reports.

Every statement here was checked on 2026-10-26 against PSE sources:

* the OpenAPI description of the reports API, https://api.raporty.pse.pl/api/openapi (endpoints, fields, row keys),
* the field map https://api.raporty.pse.pl/EndpointsMap.pdf (field meanings),
* the report pages https://raporty.pse.pl/report/<name> (titles, units, comments),
* the API itself (first available business date, interval length, time stamps).

A unit that could not be confirmed in a PSE source has ``unit_verified=False``. Prices: PSE writes ``zł/MWh``
(energy) and ``zł/MW-h`` (capacity, per MW and hour); here they are written ``PLN/MWh`` and ``PLN/MW/h``.

Usage:
    from pse_opendata.catalog import REPORTS, get_report
    get_report("rce-pln").fields
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from pse_opendata.exceptions import UnknownReportError

CHECKED_ON = date(2026, 10, 26)
API_START = date(2024, 6, 14)          # first business date of the reports API (new balancing market)
LEGACY_END = date(2024, 6, 13)         # last business date of the legacy CSV export
REPORT_PAGE = "https://raporty.pse.pl/report/{name}"
FIELD_MAP = "https://api.raporty.pse.pl/EndpointsMap.pdf"
OPENAPI = "https://api.raporty.pse.pl/api/openapi"


@dataclass(frozen=True)
class Field:
    """One column of a report."""

    name: str
    description: str
    unit: str | None = None
    unit_verified: bool = True
    dtype: Literal["float", "str"] = "float"


@dataclass(frozen=True)
class Report:
    """A report of the reports API (https://api.raporty.pse.pl/api/<name>).

    ``resolution`` is the length of one interval; the API stamps each row with the interval END (``time_field``).
    ``key`` lists the fields that, with the interval, identify a row when a report has several rows per interval
    (the entity key in the OpenAPI description, e.g. one row per cross-section); rows are sorted on the interval
    and these fields and de-duplicated on them.
    ``unique_key=False`` marks reports whose rows can repeat in every field (identical anonymous offers). The keyset
    paging of the API skips rows at page boundaries for them, so they are requested one business date at a time in
    a single page, and nothing is de-duplicated.
    ``revision_days``: PSE republishes some reports after corrections; this is how many days after the end of a
    month the data may still change (latest republication observed for Sep 2025 - Oct 2026, rounded up). The cache
    treats a month as final only when it was downloaded at least this long after the month ended.
    """

    name: str
    title: str
    title_pl: str
    group: str
    resolution: str
    fields: tuple[Field, ...]
    first_date: date
    description: str
    key: tuple[str, ...] = ()
    unique_key: bool = True
    notes: tuple[str, ...] = ()
    revision_days: int = 3
    time_field: str = "dtime_utc"

    @property
    def interval(self) -> pd.Timedelta:
        return pd.Timedelta(self.resolution)

    @property
    def url(self) -> str:
        return REPORT_PAGE.format(name=self.name)

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    @property
    def value_fields(self) -> list[str]:
        """Fields that are not row keys."""
        return [f.name for f in self.fields if f.name not in self.key]

    @property
    def verified(self) -> bool:
        return all(f.unit_verified for f in self.fields)

    def field(self, name: str) -> Field:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)


def _fields(unit: str, items: dict[str, str]) -> tuple[Field, ...]:
    return tuple(Field(name, desc, unit) for name, desc in items.items())


_PRODUCTS = {
    "fcr_g": "FCR up (frequency containment reserve)",
    "fcr_d": "FCR down",
    "afrr_g": "aFRR up (automatic frequency restoration reserve)",
    "afrr_d": "aFRR down",
    "mfrrd_g": "mFRRd up (manual frequency restoration reserve, direct activation)",
    "mfrrd_d": "mFRRd down",
    "rr_g": "RR up (replacement reserve)",
    "rr_d": "RR down",
}
_SUPPLEMENTARY = {k: v for k, v in _PRODUCTS.items() if not k.startswith("rr")}
_CAPACITY_NOTE = (
    "Empty value: no capacity procured because the demand for that reserve type was 0 MW; "
    "0: demand was above 0 MW but nothing was procured (comment on the report page)."
)
_HOURLY_PRODUCT_NOTE = (
    "Hourly product until delivery day 2025-09-30: the API repeats the hourly value in the four quarter-hours. "
    "Quarter-hourly values from 2025-10-01."
)

REPORTS: dict[str, Report] = {}


def _add(report: Report) -> None:
    REPORTS[report.name] = report


# --- prices -------------------------------------------------------------------------------------------------------

_add(Report(
    name="rce-pln",
    title="Market price of electricity (RCE)",
    title_pl="Rynkowa cena energii elektrycznej (RCE)",
    group="prices",
    resolution="15min",
    fields=(Field("rce_pln", "RCE, described by PSE as the day-ahead wholesale market price of electricity",
                  "PLN/MWh"),),
    first_date=API_START,
    description="RCE price used e.g. in prosumer settlement. Hourly RCE before 2024-06-14: legacy PL_CENY_RYN_EN.",
    notes=(_HOURLY_PRODUCT_NOTE,),
))

_add(Report(
    name="csdac-pln",
    title="Single Day-ahead Coupling price",
    title_pl="Cena SDAC",
    group="prices",
    resolution="15min",
    fields=(Field("csdac_pln", "Price of the single day-ahead coupling (SDAC) for the Polish bidding zone",
                  "PLN/MWh"),),
    first_date=API_START,
    description="Day-ahead market coupling price for Poland. Differs from RCE.",
    notes=(_HOURLY_PRODUCT_NOTE,),
))

_add(Report(
    name="crb-rozl",
    title="Energy prices (balancing market settlement)",
    title_pl="Ceny energii",
    group="balancing",
    resolution="15min",
    fields=_fields("PLN/MWh", {
        "cen_cost": "CEN, imbalance price",
        "ckoeb_cost": "CKOEB, marginal price of balancing energy in BPKD/BO",
        "ceb_sr_cost": "CEBsr, weighted average price of balancing energy",
        "ceb_pp_cost": "CEBpp, price of balancing energy activated outside the European balancing energy platforms",
        "ceb_sr_afrrg_cost": "Average price of balancing energy from aFRR up activations on the aFRR platform",
        "ceb_sr_afrrd_cost": "Average price of balancing energy from aFRR down activations on the aFRR platform",
    }),
    first_date=API_START,
    description="Settlement prices of the balancing market, including the imbalance price CEN.",
    revision_days=120,
    notes=(
        "aFRR platform prices are empty before business date 2025-07-11.",
        "Settlement data are republished after corrections (e.g. June 2024 republished on 2025-09-16), "
        "so values can change after the first publication.",
        "EndpointsMap.pdf swaps the labels of ceb_sr_cost and ceb_pp_cost; the report page is followed here.",
    ),
))

_add(Report(
    name="en-rozl",
    title="The amount of unbalanced energy",
    title_pl="Ilość energii niezbilansowania",
    group="balancing",
    resolution="15min",
    fields=_fields("MWh", {
        "en_d": "Imbalance energy delivered (EN)",
        "en_w": "Imbalance energy withdrawn (EN)",
        "balance": "Balance of imbalance energy",
    }),
    first_date=API_START,
    description="Volume of imbalance energy of the power system per settlement period.",
    revision_days=240,
))

_add(Report(
    name="eb-rozl",
    title="Activated volume of balancing energy",
    title_pl="Ilość energii bilansującej aktywowanej",
    group="balancing",
    resolution="15min",
    fields=_fields("MWh", {
        "eb_d_pp": "Balancing energy delivered, activated outside the European balancing energy platforms (EBpp)",
        "eb_w_pp": "Balancing energy withdrawn, activated outside the European balancing energy platforms (EBpp)",
        "eb_afrrg": "Balancing energy from aFRR up activations on the aFRR platform",
        "eb_afrrd": "Balancing energy from aFRR down activations on the aFRR platform",
    }),
    first_date=API_START,
    description="Activated balancing energy volumes.",
    revision_days=120,
    notes=("aFRR platform volumes are empty before business date 2025-07-11.",),
))

_add(Report(
    name="cmbp-tp",
    title="Balancing capacity prices, primary (day-ahead) procurement",
    title_pl="Ceny mocy bilansujących nabytych w trybie podstawowym",
    group="balancing",
    resolution="1h",
    fields=_fields("PLN/MW/h", _PRODUCTS),
    first_date=API_START,
    description="Clearing prices of balancing capacity bought in the primary procurement, per reserve product.",
    notes=(_CAPACITY_NOTE, "rr_d has had no value since the start of the report (checked 2026-10-26)."),
))

_add(Report(
    name="mbp-tp",
    title="Balancing capacity volume, primary (day-ahead) procurement",
    title_pl="Wielkości mocy bilansujących nabytych w trybie podstawowym",
    group="balancing",
    resolution="1h",
    fields=_fields("MW", _PRODUCTS),
    first_date=API_START,
    description="Balancing capacity bought in the primary procurement, per reserve product.",
    notes=(_CAPACITY_NOTE,),
))

_add(Report(
    name="cmbu-tu",
    title="Balancing capacity prices, supplementary procurement",
    title_pl="Ceny mocy bilansujących nabytych w trybie uzupełniającym",
    group="balancing",
    resolution="15min",
    fields=_fields("PLN/MW/h", _SUPPLEMENTARY),
    first_date=API_START,
    description="Prices of balancing capacity bought in the supplementary procurement.",
    notes=("The API also returns the last quarter-hour of business date 2024-06-13.",),
))

_add(Report(
    name="mbu-tu",
    title="Balancing capacity volume, supplementary procurement",
    title_pl="Wielkości mocy bilansujących nabytych w trybie uzupełniającym",
    group="balancing",
    resolution="15min",
    fields=_fields("MW", _SUPPLEMENTARY),
    first_date=API_START,
    description="Balancing capacity bought in the supplementary procurement.",
    notes=("The API also returns the last quarter-hour of business date 2024-06-13.",),
))

_add(Report(
    name="popmb-rmb",
    title="Portfolio offers for balancing capacity",
    title_pl="Oferty portfolio na moce bilansujące",
    group="balancing",
    resolution="1h",
    fields=(
        Field("reserve_type", "Reserve product, e.g. 'aFRRᴳ' (up) or 'aFRRᴰ' (down)", dtype="str"),
        Field("pom", "POM, offered volume of balancing capacity", "MW", unit_verified=False),
        Field("com", "COM, unit price of the offered volume", "PLN/MW/h"),
        Field("comrr", "COMRR, unit price of the offered volume contracted as RR", "PLN/MW/h"),
    ),
    first_date=API_START,
    key=("reserve_type", "com", "pom", "comrr"),
    unique_key=False,
    description="Anonymous portfolio offers of the primary balancing capacity procurement; many rows per hour.",
    notes=(
        "reserve_type uses the modifier letters U+1D33 (ᴳ, up) and U+1D30 (ᴰ, down), as published.",
        "About 4,000-9,000 rows per business date; identical offers appear as identical rows.",
        "The API pages with a keyset cursor over (dtime_utc, pom, com, comrr, reserve_type), which skips rows "
        "with empty or repeated values at page boundaries (8 of 8,286 rows lost for 2025-10-02 with 1,000-row "
        "pages); this client requests one business date per page.",
    ),
))

# --- power system -------------------------------------------------------------------------------------------------

_SYSTEM_FIELDS = {
    "demand": "KSE power demand (identical to kse-load load_actual)",
    "jg": "Generation of scheduling units in the KSE (JGw, JGm, JGz and JGa)",
    "jgw1": "Generation of generating scheduling units JGw with ZAK=1",
    "jgw2": "Generation of generating scheduling units JGw with ZAK=2",
    "jgm1": "Generation of energy storage scheduling units JGm with ZAK=1",
    "jgm2": "Generation of energy storage scheduling units JGm with ZAK=2",
    "jgz1": "Generation of wind and PV scheduling units JGz with ZAK=1",
    "jgz2": "Generation of wind and PV scheduling units JGz with ZAK=2",
    "jgz3": "Generation of wind and PV scheduling units JGz with ZAK=3",
    "jga": "Generation of aggregator scheduling units (JGa)",
    "jgo": "Consumption of receiving scheduling units (JGo)",
    "jnwrb": "Generation of units not actively participating in the balancing market",
    "jgm": "Total charging power of energy storage scheduling units (JGm)",
    "wi": "Total generation of wind sources, units on and off the balancing market",
    "pv": "Total generation of photovoltaic sources, units on and off the balancing market",
    "swm_p": "Domestic balance of cross-border exchange, parallel (synchronous); + = import",
    "swm_np": "Domestic balance of cross-border exchange, non-parallel (asynchronous); + = import",
}

_add(Report(
    name="his-wlk-cal",
    title="Fundamental data",
    title_pl="Wielkości podstawowe",
    group="system",
    resolution="15min",
    fields=_fields("MW", _SYSTEM_FIELDS),
    first_date=API_START,
    description="Actual demand, generation by unit type, wind, PV and cross-border exchange of the Polish system.",
    revision_days=60,
    notes=(
        "Near real time: future intervals of the current day are returned with empty values.",
        "The API also returns the last quarter-hour of business date 2024-06-13.",
        "jgm is never positive in the data (charging is negative); the sign convention is not stated by PSE.",
    ),
))

_add(Report(
    name="kse-load",
    title="Load of Polish Power System",
    title_pl="Zapotrzebowanie mocy KSE",
    group="system",
    resolution="15min",
    fields=_fields("MW", {
        "load_fcst": "Forecasted total load",
        "load_actual": "Actual total load (identical to his-wlk-cal demand)",
    }),
    first_date=API_START,
    description="Forecast and actual demand of the national power system.",
    revision_days=60,
    notes=("The API also returns the last quarter-hour of business date 2024-06-13.",),
))

_add(Report(
    name="pdgopkd",
    title="Day Ahead Coordinated Plan (PKD), fundamental data",
    title_pl="Plan koordynacyjny dobowy (PKD), wielkości podstawowe",
    group="system",
    resolution="15min",
    fields=_fields("MW", {
        "kse_pow_dem": "KSE power demand (plan)",
        "gen_wi": "Total generation of wind sources (plan)",
        "gen_fv": "Total generation of photovoltaic sources (plan)",
        "gen_jgw_jgm_jgz_jga": "Generation of scheduling units JGw, JGm, JGz and JGa",
        "gen_jgw_zak_1": "Generation of generating scheduling units JGw with ZAK=1",
        "gen_jgw_zak_2": "Generation of generating scheduling units JGw with ZAK=2",
        "gen_jgm_zak_1": "Generation of energy storage scheduling units JGm with ZAK=1",
        "gen_jgm_zak_2": "Generation of energy storage scheduling units JGm with ZAK=2",
        "gen_jgz_zak_1": "Generation of wind and PV scheduling units JGz with ZAK=1",
        "gen_jgz_zak_2": "Generation of wind and PV scheduling units JGz with ZAK=2",
        "gen_jgz_zak_3": "Generation of wind and PV scheduling units JGz with ZAK=3",
        "gen_jga": "Generation of aggregator scheduling units (JGa)",
        "gen_jgo": "Consumption of receiving scheduling units (JGo)",
        "gen_not_activ_part": "Generation of units not actively participating in the balancing market",
        "tot_jgm_char_pow": "Total charging power of energy storage scheduling units (JGm)",
        "dom_balance_exchange_par": "Domestic balance of cross-border exchange, parallel",
        "dom_balance_exchange_non_par": "Domestic balance of cross-border exchange, non-parallel",
        "ogr_mwe": "Planned availability limitations and withdrawals of units (MWE)",
        "rez_over_demand": "Reserve capacity above demand",
        "rez_under": "Reserve capacity below demand",
        "capacity_jgw_jgm_jgz_jga": "Generation capacity of scheduling units JGw, JGm, JGz and JGa",
        "capacity_jgw_zak_1": "Generation capacity of generating scheduling units JGw with ZAK=1",
        "capacity_jgw_zak_2": "Generation capacity of generating scheduling units JGw with ZAK=2",
        "capacity_jgm_zak_1": "Generation capacity of energy storage scheduling units JGm with ZAK=1",
        "capacity_jgm_zak_2": "Generation capacity of energy storage scheduling units JGm with ZAK=2",
        "capacity_jgz_zak_1": "Generation capacity of wind and PV scheduling units JGz with ZAK=1",
        "capacity_jgz_zak_2": "Generation capacity of wind and PV scheduling units JGz with ZAK=2",
        "capacity_jgz_zak_3": "Generation capacity of wind and PV scheduling units JGz with ZAK=3",
        "capacity_jga": "Generation capacity of aggregator scheduling units (JGa)",
        "capacity_jgo": "Consumption capacity of receiving scheduling units (JGo)",
    }),
    first_date=API_START,
    description="Day-ahead plan of the system operator: forecast demand, wind, PV, generation and reserves.",
    notes=("Wind and PV totals include units on and off the balancing market (comment on the report page).",),
))

_add(Report(
    name="poze-redoze",
    title="Non-market redispatch of RES resources",
    title_pl="Nierynkowe redysponowanie źródeł OZE",
    group="system",
    resolution="15min",
    fields=_fields("MW", {
        "pv_red_balance": "PV units, redispatch for balancing of the power system",
        "pv_red_network": "PV units, redispatch for system constraints management",
        "wi_red_balance": "Wind units, redispatch for balancing of the power system",
        "wi_red_network": "Wind units, redispatch for system constraints management",
    }),
    first_date=date(2024, 9, 24),
    description="Curtailment of wind and PV ordered by the operator outside the market.",
    revision_days=90,
    notes=("Most intervals have empty values (no redispatch).",),
))

_add(Report(
    name="przeplywy-mocy",
    title="Cross-border electricity exchange, technical flows",
    title_pl="Wymiana międzysystemowa, przepływy mocy",
    group="system",
    resolution="15min",
    fields=(
        Field("section_code", "Cross-section, e.g. 'CZ-PL'", dtype="str"),
        Field("value", "Physical power flow on the cross-section; + = import to Poland, - = export", "MW"),
    ),
    first_date=API_START,
    key=("section_code",),
    description="Physical flows on the commercial cross-sections, one row per section and interval.",
    revision_days=60,
    notes=("Flows exclude local exchange over 110 kV lines (comment on the report page).",),
))

_add(Report(
    name="gen-jw",
    title="Production of generating units",
    title_pl="Generacja mocy jednostek wytwórczych",
    group="system",
    resolution="15min",
    fields=(
        Field("resource_code", "Unit code", dtype="str"),
        Field("operating_mode", "Operating mode (Polish label)", dtype="str"),
        Field("power_plant", "Power plant", dtype="str"),
        Field("operating_mode_eng", "Operating mode (English label)", dtype="str"),
        Field("value", "Generation of the unit", "MW", unit_verified=False),
    ),
    first_date=API_START,
    key=("resource_code", "operating_mode"),
    description="Generation per unit; units with installed capacity of 100 MW or more and an EIC code.",
    revision_days=60,
))


def get_report(name: str) -> Report:
    """Catalogue entry of a report, e.g. ``get_report("rce-pln")``."""
    try:
        return REPORTS[name]
    except KeyError:
        known = ", ".join(sorted(REPORTS))
        raise UnknownReportError(f"unknown report {name!r}; known reports: {known}") from None


# --- legacy CSV export (www.pse.pl, data until 2024-06-13) --------------------------------------------------------


@dataclass(frozen=True)
class LegacyColumn:
    header: str          # column header in the CSV, lower case
    field: Field


@dataclass(frozen=True)
class LegacyReport:
    """A report of the legacy export https://www.pse.pl/getcsv/-/export/csv/<code>/data_od/<YYYYMMDD>/data_do/<YYYYMMDD>.

    Hourly rows, local time (hour 1 = 00:00-01:00, extra autumn hour ``2A``), ``;``-separated, decimal comma, cp1250.
    """

    code: str
    title: str
    title_pl: str
    page: str
    columns: tuple[LegacyColumn, ...]
    first_date: date
    description: str
    notes: tuple[str, ...] = ()
    last_date: date = LEGACY_END
    resolution: str = "1h"

    @property
    def interval(self) -> pd.Timedelta:
        return pd.Timedelta(self.resolution)

    @property
    def field_names(self) -> list[str]:
        return [c.field.name for c in self.columns]

    @property
    def fields(self) -> tuple[Field, ...]:
        return tuple(c.field for c in self.columns)


def _col(header: str, name: str, desc: str, unit: str | None, verified: bool = False) -> LegacyColumn:
    return LegacyColumn(header, Field(name, desc, unit, unit_verified=verified))


_ARCHIVE = "https://www.pse.pl/dane-systemowe"
LEGACY_REPORTS: dict[str, LegacyReport] = {}


def _add_legacy(report: LegacyReport) -> None:
    LEGACY_REPORTS[report.code] = report


_add_legacy(LegacyReport(
    code="PL_WYK_KSE",
    title="Power system operation, fundamental data",
    title_pl="Praca KSE - wielkości podstawowe",
    page=f"{_ARCHIVE}/funkcjonowanie-kse/raporty-dobowe-z-pracy-kse/wielkosci-podstawowe",
    columns=(
        _col("krajowe zapotrzebowanie na moc", "demand", "National power demand", "MW"),
        _col("sumaryczna generacja jwcd", "jwcd", "Total generation of centrally dispatched units (JWCD)", "MW"),
        _col("generacja pi", "pi", "'Generacja PI' (column until 2020; not explained in the export)", "MW"),
        _col("generacja irz", "irz", "'Generacja IRZ' (column until 2020; not explained in the export)", "MW"),
        _col("sumaryczna generacja njwcd", "njwcd", "Total generation of units not centrally dispatched (nJWCD)",
             "MW"),
        _col("krajowe saldo wymiany międzysystemowej równoległej", "swm_p",
             "Domestic balance of parallel cross-border exchange", "MW"),
        _col("krajowe saldo wymiany międzysystemowej nierównoległej", "swm_np",
             "Domestic balance of non-parallel cross-border exchange", "MW"),
    ),
    first_date=date(2009, 1, 1),
    description="Hourly demand, generation of JWCD and nJWCD and exchange balance until 2024-06-13.",
    notes=(
        "Columns 'Generacja PI' and 'Generacja IRZ' exist until 2020 and are absent from 2021.",
        "Demand of the reports API (his-wlk-cal demand, kse-load load_actual) sits about 0.7% below this series "
        "around the switch; see pse_opendata.splice_factor.",
    ),
))

_add_legacy(LegacyReport(
    code="PL_GEN_WIATR",
    title="Power system operation, wind and PV generation",
    title_pl="Praca KSE - generacja źródeł wiatrowych i fotowoltaicznych",
    page=f"{_ARCHIVE}/funkcjonowanie-kse/raporty-dobowe-z-pracy-kse/generacja-zrodel-wiatrowych",
    columns=(
        _col("generacja źródeł wiatrowych", "wind", "Generation of wind sources", "MW"),
        _col("generacja źródeł fotowoltaicznych", "pv", "Generation of photovoltaic sources", "MW"),
    ),
    first_date=date(2012, 5, 26),
    description="Hourly wind and PV generation until 2024-06-13.",
    notes=("PV is '-' (empty) before 2020-04-10.",),
))

_add_legacy(LegacyReport(
    code="PL_CENY_RYN_EN",
    title="Market price of electricity (RCE), hourly",
    title_pl="Rynkowa cena energii elektrycznej (RCE)",
    page=f"{_ARCHIVE}/funkcjonowanie-rb/raporty-dobowe-z-funkcjonowania-rb/podstawowe-wskazniki-cenowe-i-kosztowe/"
         "rynkowa-cena-energii-elektrycznej-rce",
    columns=(_col("rce", "rce", "RCE, market price of electricity", "PLN/MWh"),),
    first_date=date(2018, 1, 1),
    description="Hourly RCE until 2024-06-13; continued by rce-pln.",
    notes=("Dates are written YYYYMMDD in this export.",),
))

_add_legacy(LegacyReport(
    code="PL_CENY_ROZL_RB",
    title="Balancing market settlement prices (before the 2024 reform)",
    title_pl="Funkcjonowanie RB - ceny rozliczeniowe",
    page=f"{_ARCHIVE}/funkcjonowanie-rb/raporty-dobowe-z-funkcjonowania-rb/podstawowe-wskazniki-cenowe-i-kosztowe/"
         "ceny-rozliczeniowe",
    columns=(
        _col("cor", "cor", "'COR' (column until 2020; not explained in the export)", "PLN/MWh"),
        _col("cro", "cro", "CRO, settlement price of imbalance energy", "PLN/MWh"),
        _col("cros", "cros", "CROs, settlement price of imbalance energy for sales", "PLN/MWh"),
        _col("croz", "croz", "CROz, settlement price of imbalance energy for purchases", "PLN/MWh"),
    ),
    first_date=date(2009, 1, 1),
    description="Hourly imbalance settlement prices of the old balancing market until 2024-06-13.",
    notes=(
        "Dates are written YYYYMMDD in this export.",
        "Column 'COR' exists until 2020 and is absent from 2021.",
        "Not the same quantity as CEN (crb-rozl cen_cost) of the reformed market; not stitched automatically.",
    ),
))


def get_legacy_report(code: str) -> LegacyReport:
    """Catalogue entry of a legacy export report, e.g. ``get_legacy_report("PL_WYK_KSE")``."""
    try:
        return LEGACY_REPORTS[code]
    except KeyError:
        known = ", ".join(sorted(LEGACY_REPORTS))
        raise UnknownReportError(f"unknown legacy report {code!r}; known reports: {known}") from None
