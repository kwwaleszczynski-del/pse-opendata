"""Command line interface.

Usage:
    pse-opendata get rce-pln --start 2025-01-01 --end 2025-01-31 --out rce.parquet
    pse-opendata get his-wlk-cal --start 2025-06-01 --fields demand,wi,pv --out mix.csv
    pse-opendata legacy PL_WYK_KSE --start 2023-01-01 --end 2023-01-31 --out kse.parquet
    pse-opendata history demand --start 2019-01-01 --end 2025-12-31 --out demand.parquet
    pse-opendata reports [--legacy] [--markdown]
    pse-opendata cache [--clear]

Without ``--out`` the table is written to stdout as CSV. Dates are business days in Polish local time, inclusive.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from pse_opendata import __version__, reports
from pse_opendata.cache import default_cache_dir
from pse_opendata.catalog import LEGACY_REPORTS, REPORTS
from pse_opendata.client import Client
from pse_opendata.exceptions import PseError
from pse_opendata.stitch import SERIES

log = logging.getLogger("pse_opendata")


def _write(frame: pd.DataFrame, out: Path | None) -> None:
    if out is None:
        try:
            frame.to_csv(sys.stdout, index=False, lineterminator="\n")    # text stdout adds \r on Windows
            sys.stdout.flush()
        except (BrokenPipeError, OSError):    # e.g. piped into `head`
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".parquet":
        frame.to_parquet(out, index=False)
    elif out.suffix.lower() == ".csv":
        frame.to_csv(out, index=False)
    else:
        raise SystemExit(f"unsupported output format {out.suffix!r}; use .parquet or .csv")
    log.info("wrote %d rows to %s", len(frame), out)


def markdown_table(frame: pd.DataFrame) -> str:
    """A GitHub Markdown table (no extra dependency)."""
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|")

    lines = ["| " + " | ".join(frame.columns) + " |", "|" + "---|" * len(frame.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join(lines)


def _client(args: argparse.Namespace) -> Client:
    cache_dir = None if args.no_cache else (args.cache_dir or default_cache_dir())
    return Client(cache_dir=cache_dir, refresh=args.refresh, offline=args.offline, allow_stale=args.allow_stale)


def _range(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--start", required=True, help="first business date, YYYY-MM-DD")
    sub.add_argument("--end", help="last business date, YYYY-MM-DD (default: --start)")
    sub.add_argument("--out", type=Path, help="output file, .parquet or .csv (default: CSV to stdout)")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cache-dir", type=Path, help=f"cache directory (default: {default_cache_dir()})")
    common.add_argument("--no-cache", action="store_true", help="do not read or write the cache")
    common.add_argument("--refresh", action="store_true", help="download again months the cache holds as final")
    common.add_argument("--offline", action="store_true", help="use the cache only")
    common.add_argument("--allow-stale", action="store_true", help="on download errors use cached copies")
    common.add_argument("-v", "--verbose", action="store_true", help="log every request")

    parser = argparse.ArgumentParser(prog="pse-opendata", description="Public data of PSE (Polish TSO) as tables.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subs = parser.add_subparsers(dest="command", required=True)

    p = subs.add_parser("get", parents=[common], help="data of a report of the reports API")
    p.add_argument("report", choices=sorted(REPORTS), metavar="REPORT", help="report name, e.g. rce-pln")
    _range(p)
    p.add_argument("--fields", help="comma-separated fields (default: all)")
    p.add_argument("--dropna", action="store_true", help="drop rows with all values empty")

    p = subs.add_parser("legacy", parents=[common], help="hourly data of the legacy CSV export (until 2024-06-13)")
    p.add_argument("code", choices=sorted(LEGACY_REPORTS), metavar="CODE", help="report code, e.g. PL_WYK_KSE")
    _range(p)
    p.add_argument("--fields", help="comma-separated fields (default: all)")

    p = subs.add_parser("history", parents=[common], help="hourly series stitched from the legacy export and the API")
    p.add_argument("series", choices=sorted(SERIES), help="series name")
    _range(p)
    p.add_argument("--rescale", action="store_true", help="rescale the API part to the legacy level")

    p = subs.add_parser("reports", help="list the catalogue")
    p.add_argument("--legacy", action="store_true", help="list the legacy export reports")
    p.add_argument("--markdown", action="store_true", help="print a Markdown table")

    p = subs.add_parser("cache", parents=[common], help="show the cache directory")
    p.add_argument("--clear", action="store_true", help="delete all cached files")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):    # CSV and titles contain e.g. 'ł' and 'ᴳ'; Windows consoles use cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    try:
        if args.command == "reports":
            table = reports(legacy=args.legacy)
            if not args.markdown:
                table = table[[c for c in table.columns if c not in ("title_pl", "fields", "url", "page")]]
            print(markdown_table(table) if args.markdown else table.to_string(index=False))
            return 0
        client = _client(args)
        if args.command == "cache":
            if client.cache is None:
                print("cache disabled")
            elif args.clear:
                print(f"deleted {client.cache.clear()} files from {client.cache.root}")
            else:
                print(client.cache.root)
            return 0
        fields = args.fields.split(",") if getattr(args, "fields", None) else None
        if args.command == "get":
            frame = client.get(args.report, args.start, args.end, fields=fields, dropna=args.dropna)
        elif args.command == "legacy":
            frame = client.legacy(args.code, args.start, args.end, fields=fields)
        else:
            frame = client.history(args.series, args.start, args.end, rescale=args.rescale)
        _write(frame, args.out)
    except (PseError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
