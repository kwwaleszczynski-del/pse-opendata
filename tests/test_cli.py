"""Command line interface."""

from __future__ import annotations

import pandas as pd
import pytest

from pse_opendata import Client, __version__, cli

from conftest import FakeSession, api_pages, serve_pages


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    session = FakeSession(serve_pages(api_pages("rce-pln_2025-10-26")))

    def factory(**kwargs):
        kwargs.pop("cache_dir", None)
        return Client(session=session, cache_dir=tmp_path / "cache", sleep=lambda s: None, **kwargs)

    monkeypatch.setattr(cli, "Client", factory)
    return session


def test_get_writes_parquet(fake_client, tmp_path):
    out = tmp_path / "rce.parquet"
    assert cli.main(["get", "rce-pln", "--start", "2025-10-26", "--out", str(out)]) == 0
    frame = pd.read_parquet(out)
    assert len(frame) == 100
    assert list(frame.columns) == ["start_utc", "end_utc", "start_local", "end_local", "business_date", "rce_pln"]


def test_get_prints_csv(fake_client, capsys):
    assert cli.main(["get", "rce-pln", "--start", "2025-10-26", "--fields", "rce_pln"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "start_utc,end_utc,start_local,end_local,business_date,rce_pln"
    assert lines[1].startswith("2025-10-25 22:00:00+00:00,2025-10-25 22:15:00+00:00,2025-10-26 00:00:00+02:00")
    assert len(lines) == 101


def test_errors_exit_with_status_1(fake_client, capsys):
    assert cli.main(["get", "rce-pln", "--start", "2025-10-26", "--fields", "price"]) == 1
    assert "unknown fields" in capsys.readouterr().err
    assert cli.main(["get", "rce-pln", "--start", "2025-10-27", "--end", "2025-10-26"]) == 1


def test_unknown_report_is_rejected_by_argparse():
    with pytest.raises(SystemExit):
        cli.main(["get", "rce", "--start", "2025-10-26"])


def test_reports_markdown(capsys):
    assert cli.main(["reports", "--markdown"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("| name | title |")
    assert any(line.startswith("| rce-pln |") for line in out)
    assert cli.main(["reports", "--legacy"]) == 0
    assert "PL_WYK_KSE" in capsys.readouterr().out


def test_cache_command(fake_client, tmp_path, capsys):
    cli.main(["get", "rce-pln", "--start", "2025-10-01", "--end", "2025-10-31", "--out", str(tmp_path / "x.csv")])
    assert cli.main(["cache"]) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / "cache")
    assert cli.main(["cache", "--clear"]) == 0
    assert "deleted 1 files" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.startswith(f"pse-opendata {__version__}")
