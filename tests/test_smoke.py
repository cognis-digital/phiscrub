"""Smoke tests for PHISCRUB. No network; runs against the demo file."""

import os
import shutil

import pytest

from phiscrub import (
    TOOL_NAME,
    TOOL_VERSION,
    scan_text,
    scan_file,
    redact_text,
    redact_file,
    summarize,
)
from phiscrub.cli import main

DEMO = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "demos", "01-basic", "visit_log.csv",
)


def test_metadata():
    assert TOOL_NAME == "phiscrub"
    assert TOOL_VERSION.count(".") == 2


def test_scan_text_detects_each_kind():
    text = (
        "Patient: John Doe MRN: 0048213 SSN 123-45-6789 "
        "born 04/12/1981 call (843) 555-0167 email jdoe@example.com"
    )
    kinds = {f.kind for f in scan_text(text)}
    for expected in {"ssn", "mrn", "email", "phone", "date", "name"}:
        assert expected in kinds, "missing detector: %s" % expected


def test_ssn_validation_rejects_invalid():
    # 000 area is structurally invalid -> should not match as SSN.
    findings = scan_text("id 000-12-3456 here")
    assert all(f.kind != "ssn" for f in findings)
    # A valid SSN should match.
    assert any(f.kind == "ssn" for f in scan_text("ssn 123-45-6789"))


def test_finding_offsets_are_accurate():
    text = "x SSN 123-45-6789 y"
    f = next(f for f in scan_text(text) if f.kind == "ssn")
    assert text[f.start:f.end] == "123-45-6789"
    assert f.line == 1 and f.col == text.index("123") + 1


def test_scan_file_demo_has_phi():
    findings = scan_file(DEMO)
    assert len(findings) >= 6
    counts = summarize(findings)
    assert counts.get("ssn", 0) >= 2
    assert counts.get("mrn", 0) >= 2


def test_redact_replaces_and_removes_phi():
    text = "SSN 123-45-6789 and email a@b.com"
    redacted, n = redact_text(text)
    assert n == 2
    assert "123-45-6789" not in redacted
    assert "a@b.com" not in redacted
    assert "[REDACTED-SSN]" in redacted
    # Redacted output is clean on a second pass.
    assert redact_text(redacted)[1] == 0


def test_redact_file_in_place(tmp_path):
    work = tmp_path / "copy.csv"
    shutil.copy(DEMO, work)
    before = scan_file(str(work))
    n = redact_file(str(work))
    assert n == len(before)
    after = scan_file(str(work))
    assert after == []


def test_kinds_filter():
    text = "SSN 123-45-6789 email a@b.com"
    only_ssn = scan_text(text, kinds=["ssn"])
    assert {f.kind for f in only_ssn} == {"ssn"}


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "phiscrub" in out and TOOL_VERSION in out


def test_cli_scan_exit_nonzero_on_phi(capsys):
    rc = main(["scan", DEMO])
    assert rc == 1  # CI gate fails when PHI present
    out = capsys.readouterr().out
    assert "PHI found" in out


def test_cli_scan_json(capsys):
    rc = main(["--format", "json", "scan", DEMO])
    assert rc == 1
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "phiscrub"
    assert payload["total_findings"] >= 6
    assert "summary" in payload


def test_cli_scan_clean_exits_zero(tmp_path, capsys):
    clean = tmp_path / "clean.txt"
    clean.write_text("Build 1.2.3 deployed. No patient data here.\n")
    rc = main(["scan", str(clean)])
    assert rc == 0
    assert "No PHI found" in capsys.readouterr().out


def test_cli_redact_dry_run_nonzero(tmp_path, capsys):
    work = tmp_path / "copy.csv"
    shutil.copy(DEMO, work)
    rc = main(["redact", str(work), "--dry-run"])
    assert rc == 1
    # Dry-run must not modify the file.
    assert scan_file(str(work)) != []
