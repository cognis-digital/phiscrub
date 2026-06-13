"""Core PHI detection and redaction engine (standard library only).

The engine is a set of named *detectors*. Each detector is a regular
expression plus an optional validation hook (e.g. SSN structural rules,
Luhn-style sanity, date plausibility). Detectors produce :class:`Finding`
objects with precise spans so callers can redact in place without disturbing
the surrounding bytes.

Nothing here touches the network or any third-party package.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from typing import Callable, Iterable, Iterator

# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Finding:
    """A single detected piece of PHI."""

    kind: str        # detector name, e.g. "ssn", "mrn", "email"
    value: str       # the raw matched text
    start: int       # character offset (inclusive) within the source text
    end: int         # character offset (exclusive)
    line: int        # 1-based line number
    col: int         # 1-based column on that line

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Validators (reduce false positives)
# --------------------------------------------------------------------------- #


def _valid_ssn(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9:
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    # Structural rules per SSA: no 000 area, 666 area, 9xx area, 00 group, 0000 serial.
    if area in ("000", "666") or area[0] == "9":
        return False
    if group == "00" or serial == "0000":
        return False
    return True


def _valid_date(value: str) -> bool:
    # Accept only plausible calendar values; rejects e.g. 13/40/9999 version-ish noise.
    nums = [int(n) for n in re.findall(r"\d+", value)]
    if len(nums) != 3:
        return False
    # Identify the 4-digit (or 2-digit) year and month/day pair heuristically.
    year = next((n for n in nums if n > 31), None)
    if year is None:
        # all <= 31: treat last as a 2-digit year, first two as month/day
        m, d = nums[0], nums[1]
    else:
        rest = [n for n in nums if n != year] + ([] if nums.count(year) == 1 else [])
        rest = [n for n in nums if n is not year]
        # rebuild order-independent month/day
        nz = [n for n in nums if n != year]
        m, d = nz[0], nz[1]
    if not (1900 <= (year or 1999) <= 2099):
        if year is not None:
            return False
    return 1 <= m <= 12 and 1 <= d <= 31


def _valid_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return len(digits) in (10, 11)


# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Detector:
    name: str
    pattern: re.Pattern
    validate: Callable[[str], bool] | None = None

    def finditer(self, text: str) -> Iterator[re.Match]:
        for m in self.pattern.finditer(text):
            if self.validate is None or self.validate(m.group(0)):
                yield m


# Order matters: more specific / higher-signal detectors first so their spans
# win during overlap resolution.
DETECTORS: list[Detector] = [
    Detector(
        "ssn",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b"),
        _valid_ssn,
    ),
    Detector(
        "mrn",
        # Explicitly labeled medical record numbers: MRN: 1234567
        # The captured value must contain at least one digit to avoid matching
        # plain English words (e.g. "Number") that follow the label prefix.
        re.compile(r"\b(?:MRN|Medical\s+Record(?:\s+(?:No|Number|#))?)\b[:#\s]*([A-Z0-9-]*\d[A-Z0-9-]*)",
                   re.IGNORECASE),
    ),
    Detector(
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    Detector(
        "phone",
        # Use digit-boundary lookbehind/lookahead instead of \b so that
        # parenthesised area codes like (843) are correctly anchored —
        # \b does not fire between a space and '(' since both are non-word chars.
        re.compile(
            r"(?<![0-9])(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}(?![0-9])"
        ),
        _valid_phone,
    ),
    Detector(
        "date",
        re.compile(
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
        ),
        _valid_date,
    ),
    Detector(
        "name",
        # Names introduced by a clinical label, e.g. "Patient: John Doe",
        # "Pt John Q. Doe". Keeps false positives low vs. matching any capitals.
        re.compile(
            r"\b(?:Patient|Pt|Name|DOB\s+for|Member|Insured)\b[:#\s]*"
            r"([A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+){1,2})"
        ),
    ),
]

_DETECTOR_BY_NAME = {d.name: d for d in DETECTORS}


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Return 1-based (line, col) for a character offset."""
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    last_nl = prefix.rfind("\n")
    col = offset - last_nl  # if no newline, last_nl == -1 -> offset+1
    return line, col


def _resolve_span(m: re.Match) -> tuple[int, int, str]:
    """Return the (start, end, value) for the most specific group available.

    Detectors that capture a sub-group (e.g. the actual MRN after the label)
    redact only that group; otherwise the whole match.
    """
    if m.lastindex:
        return m.start(1), m.end(1), m.group(1)
    return m.start(), m.end(), m.group(0)


def scan_text(text: str, kinds: Iterable[str] | None = None) -> list[Finding]:
    """Scan a string and return non-overlapping :class:`Finding` objects.

    ``kinds`` optionally restricts which detectors run.
    """
    selected = DETECTORS
    if kinds is not None:
        want = set(kinds)
        selected = [d for d in DETECTORS if d.name in want]

    raw: list[Finding] = []
    for det in selected:
        for m in det.finditer(text):
            start, end, value = _resolve_span(m)
            if start >= end:
                continue
            line, col = _line_col(text, start)
            raw.append(Finding(det.name, value, start, end, line, col))

    # Resolve overlaps: detectors are ordered by priority, so for any two
    # overlapping spans keep the one whose detector appeared first.
    priority = {d.name: i for i, d in enumerate(selected)}
    raw.sort(key=lambda f: (f.start, priority.get(f.kind, 999)))
    kept: list[Finding] = []
    occupied_end = -1
    for f in raw:
        if f.start >= occupied_end:
            kept.append(f)
            occupied_end = f.end
        # else: overlaps a higher-priority span already kept -> drop
    kept.sort(key=lambda f: f.start)
    return kept


def scan_file(path: str, kinds: Iterable[str] | None = None) -> list[Finding]:
    """Scan a single file's text content."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return scan_text(text, kinds=kinds)


_SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".tar",
    ".exe", ".dll", ".so", ".bin", ".ico", ".woff", ".woff2",
}


def scan_path(
    path: str, kinds: Iterable[str] | None = None
) -> dict[str, list[Finding]]:
    """Scan a file or recursively scan a directory.

    Returns a mapping of file path -> findings (only files with findings are
    omitted-or-kept by the caller; here every scanned text file is included so
    callers can report clean files too).
    """
    results: dict[str, list[Finding]] = {}
    if os.path.isfile(path):
        results[path] = scan_file(path, kinds=kinds)
        return results
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            if ext in _SKIP_EXT:
                continue
            fpath = os.path.join(root, name)
            try:
                results[fpath] = scan_file(fpath, kinds=kinds)
            except OSError:
                continue
    return results


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #


def _placeholder(kind: str) -> str:
    return "[REDACTED-%s]" % kind.upper()


def redact_text(text: str, kinds: Iterable[str] | None = None) -> tuple[str, int]:
    """Return ``(redacted_text, num_redactions)``.

    Each finding's span is replaced with ``[REDACTED-KIND]``. Replacement runs
    right-to-left so earlier offsets stay valid.
    """
    findings = scan_text(text, kinds=kinds)
    if not findings:
        return text, 0
    out = text
    for f in sorted(findings, key=lambda f: f.start, reverse=True):
        out = out[: f.start] + _placeholder(f.kind) + out[f.end :]
    return out, len(findings)


def redact_file(
    path: str, kinds: Iterable[str] | None = None, in_place: bool = True
) -> int:
    """Redact PHI in a file. Returns the number of redactions.

    When ``in_place`` is True the file is only rewritten if something changed.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    redacted, n = redact_text(text, kinds=kinds)
    if in_place and n:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(redacted)
    return n


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #


def summarize(findings: Iterable[Finding]) -> dict[str, int]:
    """Count findings by kind."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return counts
