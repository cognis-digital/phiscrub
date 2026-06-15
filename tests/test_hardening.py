"""Hardening tests: error paths, edge cases, and input validation.

These tests cover the robust-error-handling improvements and should remain
green alongside the existing smoke tests.
"""

import pytest

from phiscrub.core import _valid_date, scan_text, scan_file, redact_file
from phiscrub.cli import main


# ---------------------------------------------------------------------------
# core.py: _valid_date no longer crashes on degenerate inputs
# ---------------------------------------------------------------------------


def test_valid_date_no_crash_on_duplicate_year():
    """Pattern like 32/32/32 must not raise IndexError."""
    # All three equal and > 31 -> heuristic treats first as year,
    # remaining two are also the same value (32) -> invalid month/day -> False.
    assert _valid_date("32/32/32") is False


def test_valid_date_all_equal_small():
    """All three numbers <= 31 and equal — month/day check applies."""
    # e.g. 1/1/1 -> m=1, d=1, year=None -> valid
    assert _valid_date("1/1/1") is True


def test_valid_date_rejects_impossible_month():
    assert _valid_date("13/01/2024") is False


def test_valid_date_rejects_impossible_day():
    assert _valid_date("01/40/2024") is False


def test_valid_date_accepts_iso():
    assert _valid_date("2024-04-15") is True


# ---------------------------------------------------------------------------
# core.py: scan_text raises TypeError on non-string input
# ---------------------------------------------------------------------------


def test_scan_text_raises_on_none():
    with pytest.raises(TypeError, match="scan_text\\(\\) requires a str"):
        scan_text(None)  # type: ignore[arg-type]


def test_scan_text_raises_on_int():
    with pytest.raises(TypeError):
        scan_text(42)  # type: ignore[arg-type]


def test_scan_text_empty_string_returns_empty():
    assert scan_text("") == []


# ---------------------------------------------------------------------------
# core.py: scan_file / redact_file raise FileNotFoundError for missing paths
# ---------------------------------------------------------------------------


def test_scan_file_missing_raises():
    with pytest.raises(FileNotFoundError):
        scan_file("/nonexistent/does_not_exist.txt")


def test_redact_file_missing_raises():
    with pytest.raises(FileNotFoundError):
        redact_file("/nonexistent/does_not_exist.txt")


# ---------------------------------------------------------------------------
# cli.py: missing path returns exit code 2 (not 0 or traceback)
# ---------------------------------------------------------------------------


def test_cli_scan_missing_path_exits_2(capsys):
    rc = main(["scan", "/this/path/absolutely/does/not/exist"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error" in err.lower()


def test_cli_redact_missing_path_exits_2(capsys):
    rc = main(["redact", "/this/path/absolutely/does/not/exist"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error" in err.lower()


# ---------------------------------------------------------------------------
# mcp_server.py: module now imports cleanly (broken import was scan/to_json)
# ---------------------------------------------------------------------------


def test_mcp_server_imports_cleanly():
    """mcp_server must import without ImportError."""
    import importlib
    mod = importlib.import_module("phiscrub.mcp_server")
    assert hasattr(mod, "serve")
    assert callable(mod.serve)
