import asyncio
import re
from pathlib import Path

import pytest

from polyquack.cli import main
from polyquack.ingestion.models import FeeRate
from polyquack.ingestion.platforms import POLYMARKET
from polyquack.storage.db import Database
from polyquack.times import from_iso

from .exchange import FakeExchange

SOURCE = Path(__file__).parent.parent / "src" / "polyquack"
ORDER_OR_ACCOUNT_ENDPOINTS = re.compile(
    r"/v1/(account|order|orders|trade|trades|fills|positions|transfer|withdraw)|/exchange\b",
    re.IGNORECASE,
)
NETWORK_MODULES = re.compile(
    r"^\s*(import|from)\s+(httpx|websockets|socket|urllib|requests)\b", re.M
)


def test_ac12_no_source_file_references_an_order_or_account_endpoint() -> None:
    offenders = [
        path.name
        for path in SOURCE.rglob("*.py")
        if ORDER_OR_ACCOUNT_ENDPOINTS.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_ac12_the_evaluation_package_imports_no_network_module() -> None:
    files = list((SOURCE / "evaluation").glob("*.py"))

    assert files
    assert [f.name for f in files if NETWORK_MODULES.search(f.read_text(encoding="utf-8"))] == []


def test_dec3_the_polymarket_crypto_taker_fee_comes_from_the_versioned_data_file() -> None:
    rates = asyncio.run(FakeExchange().platforms()[POLYMARKET].fees())

    assert FeeRate("crypto", "0", 0.0004, 0.000125, from_iso("2026-10-21T00:00:00.000Z")) in rates


def test_cli_evaluate_with_nothing_preregistered_reports_no_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "cli.db"
    monkeypatch.setenv("POLYQUACK_DB", str(database))
    Database(database).close()

    assert main(["evaluate"]) == 0

    assert "0 decisions" in capsys.readouterr().out


def test_cli_evaluate_and_variants_need_an_existing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("POLYQUACK_DB", str(tmp_path / "missing.db"))

    assert main(["evaluate"]) == 1
    assert main(["variants"]) == 1

    assert "No database" in capsys.readouterr().err
