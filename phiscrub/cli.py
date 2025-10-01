"""Command-line interface for PHISCRUB.

Examples
--------
Scan a directory and fail CI if any PHI is found::

    phiscrub scan ./logs
    phiscrub scan ./logs --format json | jq .

Redact PHI in place (rewrites files)::

    phiscrub redact notes.txt

Restrict to specific PHI kinds::

    phiscrub scan visit.csv --kinds ssn,mrn,email

Exit codes
----------
  0  no PHI found (clean)
  1  PHI found (CI gate should block)
  2  usage / runtime error
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import TOOL_NAME, TOOL_VERSION
from .core import (
    DETECTORS,
    redact_file,
    scan_path,
    summarize,
)


def _parse_kinds(value: str | None) -> list[str] | None:
    if not value:
        return None
    valid = {d.name for d in DETECTORS}
    kinds = [k.strip().lower() for k in value.split(",") if k.strip()]
    bad = [k for k in kinds if k not in valid]
    if bad:
        raise argparse.ArgumentTypeError(
            "unknown kind(s): %s (valid: %s)"
            % (", ".join(bad), ", ".join(sorted(valid)))
        )
    return kinds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="PHISCRUB - gitleaks-for-HIPAA. Scan logs/CSVs/notes for PHI "
        "(names, MRNs, SSNs, dates, phones, emails) and redact in place.",
        epilog="Examples:\n"
        "  phiscrub scan ./logs\n"
        "  phiscrub scan visit.csv --format json --kinds ssn,mrn\n"
        "  phiscrub redact notes.txt\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version",
        version="%s %s" % (TOOL_NAME, TOOL_VERSION),
    )
    parser.add_argument(
        "--format", choices=["table", "json"], default="table",
        help="output format (default: table)",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_scan = sub.add_parser(
        "scan", help="scan a file or directory for PHI (read-only CI gate)",
    )
    p_scan.add_argument("path", help="file or directory to scan")
    p_scan.add_argument(
        "--kinds", type=_parse_kinds, default=None,
        help="comma-separated PHI kinds to detect (default: all)",
    )

    p_redact = sub.add_parser(
        "redact", help="redact PHI in a file or directory (rewrites in place)",
    )
    p_redact.add_argument("path", help="file or directory to redact")
    p_redact.add_argument(
        "--kinds", type=_parse_kinds, default=None,
        help="comma-separated PHI kinds to redact (default: all)",
    )
    p_redact.add_argument(
        "--dry-run", action="store_true",
        help="report what would be redacted without writing files",
    )
    return parser


def _print_scan_table(results: dict, total: int) -> None:
    for fpath, findings in results.items():
        if not findings:
            continue
        print(fpath)
        for f in findings:
            print(
                "  %4d:%-3d  %-6s  %s"
                % (f.line, f.col, f.kind, f.value)
            )
    counts = summarize(
        f for findings in results.values() for f in findings
    )
    if total:
        print()
        print("PHI found: %d (%s)" % (
            total,
            ", ".join("%s=%d" % (k, v) for k, v in sorted(counts.items())),
        ))
    else:
        print("No PHI found. Clean.")


def _do_scan(args: argparse.Namespace) -> int:
    results = scan_path(args.path, kinds=args.kinds)
    total = sum(len(v) for v in results.values())
    if args.format == "json":
        payload = {
            "tool": TOOL_NAME,
            "version": TOOL_VERSION,
            "path": args.path,
            "total_findings": total,
            "summary": summarize(
                f for fs in results.values() for f in fs
            ),
            "files": {
                fp: [f.to_dict() for f in fs]
                for fp, fs in results.items() if fs
            },
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_scan_table(results, total)
    return 1 if total else 0


def _do_redact(args: argparse.Namespace) -> int:
    # Scan first so we can report and (optionally) not write.
    results = scan_path(args.path, kinds=args.kinds)
    total = sum(len(v) for v in results.values())
    written: dict[str, int] = {}
    for fpath, findings in results.items():
        if not findings:
            continue
        if args.dry_run:
            written[fpath] = len(findings)
        else:
            written[fpath] = redact_file(fpath, kinds=args.kinds, in_place=True)

    if args.format == "json":
        print(json.dumps({
            "tool": TOOL_NAME,
            "version": TOOL_VERSION,
            "path": args.path,
            "dry_run": args.dry_run,
            "total_redactions": total,
            "files": written,
        }, indent=2))
    else:
        verb = "Would redact" if args.dry_run else "Redacted"
        for fpath, n in written.items():
            print("%s %d in %s" % (verb, n, fpath))
        if total:
            print("\n%s %d PHI value(s) across %d file(s)."
                  % (verb, total, len(written)))
        else:
            print("No PHI found. Nothing to redact.")
    # A dry-run that found PHI is a gate failure; an actual redact succeeded.
    if args.dry_run:
        return 1 if total else 0
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        if args.command == "scan":
            return _do_scan(args)
        if args.command == "redact":
            return _do_redact(args)
    except FileNotFoundError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    parser.print_help()
    return 2
