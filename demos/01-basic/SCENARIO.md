# Demo 01 - Basic PHI scan and redact

This demo shows PHISCRUB detecting Protected Health Information (PHI) in a
typical clinical visit log (`visit_log.csv`) and acting as a CI gate.

## Input

`visit_log.csv` is a small export of clinic visits that accidentally leaked
PHI into a log/export that someone is about to commit:

- Patient full names (`Patient: John Doe`)
- Medical Record Numbers (`MRN: 0048213`)
- Social Security Numbers (`123-45-6789`)
- Dates of birth (`04/12/1981`)
- Phone numbers (`(843) 555-0167`)
- Email addresses (`jdoe@example.com`)

## Run it

```bash
# Scan (read-only). Exits 1 because PHI is present -> blocks CI.
python -m phiscrub scan demos/01-basic/visit_log.csv

# Machine-readable output for pipelines / jq.
python -m phiscrub scan demos/01-basic/visit_log.csv --format json

# Restrict to high-severity identifiers only.
python -m phiscrub scan demos/01-basic/visit_log.csv --kinds ssn,mrn

# Redact in place (rewrites the file with [REDACTED-*] placeholders).
python -m phiscrub redact demos/01-basic/visit_log.csv
```

## Expected result

`scan` finds multiple PHI values across the file's rows: at least one each of
`ssn`, `mrn`, `email`, `phone`, `date`, and `name`. The command prints them
with line/column locations and **exits with code 1** so a CI job fails.

`redact` replaces every detected value with a typed placeholder such as
`[REDACTED-SSN]` / `[REDACTED-MRN]`, leaving the surrounding CSV structure
intact, and reports how many values were scrubbed.
