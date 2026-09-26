#!/usr/bin/env python3
"""Compare database fingerprints taken before and after a rehearsed migration.

Usage: python3 compare.py before.json after.json migration.sql

before.json / after.json hold the rows returned by the fingerprint query in
SKILL.md (a JSON array of objects). Prints a markdown risk report, then a final
line `VERDICT: SAFE|REVIEW|BLOCK`.
"""
import json
import re
import sys
from decimal import Decimal, InvalidOperation


def lint(sql):
    """Static checks on the migration SQL. Returns (severity, statement, reason)."""
    findings = []
    for raw in sql.split(";"):
        stmt = " ".join(raw.split())
        up = stmt.upper()
        if not up:
            continue
        short = stmt if len(stmt) <= 80 else stmt[:77] + "..."

        def add(sev, reason):
            findings.append((sev, short, reason))

        if re.search(r"\bDROP\s+TABLE\b", up):
            add("HIGH", "Drops a table: its data is permanently deleted")
        if re.search(r"\bDROP\s+COLUMN\b", up):
            add("HIGH", "Drops a column: its data is permanently deleted")
        if re.search(r"\bALTER\s+COLUMN\s+\S+\s+(SET\s+DATA\s+)?TYPE\b", up):
            add("HIGH", "Changes a column type: rewrites the table under an exclusive lock and can silently change values")
        if re.match(r"TRUNCATE\b", up):
            add("HIGH", "Truncates a table: every row is deleted")
        if re.match(r"(DELETE|UPDATE)\b", up) and "WHERE" not in up:
            add("HIGH", "DELETE/UPDATE without WHERE touches every row")
        if re.search(r"\bADD\s+(COLUMN\s+)?\S+\s.*\bNOT\s+NULL\b", up) and "DEFAULT" not in up:
            add("HIGH", "Adds a NOT NULL column without a DEFAULT: fails on a non-empty table")
        if re.search(r"\bSET\s+NOT\s+NULL\b", up):
            add("MEDIUM", "SET NOT NULL scans the whole table under an exclusive lock")
        if re.search(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b", up) and "CONCURRENTLY" not in up:
            add("MEDIUM", "CREATE INDEX without CONCURRENTLY blocks writes while it builds")
        if re.search(r"\bRENAME\b", up):
            add("MEDIUM", "Renames an object: running application code may break")
    return findings


def load(path):
    with open(path) as f:
        data = json.load(f)
    # Neon's run_sql returns [{"fingerprint": [...]}]; unwrap that single row.
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict) and "fingerprint" in data[0]:
        data = data[0]["fingerprint"]
    # Accept a bare array, or an object wrapping one (e.g. {"rows": [...]}).
    if isinstance(data, dict):
        data = data.get("fingerprint") or next((v for v in data.values() if isinstance(v, list)), [])
    if isinstance(data, str):
        data = json.loads(data)
    rows = {}
    for r in data:
        rows[(r["table_name"], r["column_name"])] = r
    return rows


def num(v):
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def diff(before, after):
    """Data drift between the two fingerprints. Returns (severity, where, what)."""
    findings = []
    tables_before = {t for t, _ in before}
    tables_after = {t for t, _ in after}

    for t in sorted(tables_before - tables_after):
        findings.append(("HIGH", t, "Table is gone after the migration"))
    for t in sorted(tables_after - tables_before):
        findings.append(("INFO", t, "New table"))

    for key in sorted(set(before) | set(after)):
        t, c = key
        where = f"{t}.{c}"
        b, a = before.get(key), after.get(key)
        if t not in tables_after or t not in tables_before:
            continue
        if a is None:
            findings.append(("HIGH", where, "Column removed: its data is lost"))
            continue
        if b is None:
            findings.append(("INFO", where, f"New column ({a.get('data_type')})"))
            continue
        if b.get("data_type") != a.get("data_type"):
            findings.append(("INFO", where, f"Type {b.get('data_type')} -> {a.get('data_type')}"))
        bn, an = num(b.get("null_count")), num(a.get("null_count"))
        if bn is not None and an is not None and an > bn:
            findings.append(("MEDIUM", where, f"NULLs went from {bn} to {an}"))
        bs, as_ = num(b.get("col_sum")), num(a.get("col_sum"))
        if bs is not None and as_ is not None and bs != as_:
            findings.append(("HIGH", where,
                             f"Silent data change: SUM went from {bs} to {as_} (drift {as_ - bs})"))

    # Row counts are repeated on every column row; compare once per table.
    counts_b = {t: num(r.get("row_count")) for (t, _), r in before.items()}
    counts_a = {t: num(r.get("row_count")) for (t, _), r in after.items()}
    for t in sorted(tables_before & tables_after):
        if counts_b.get(t) != counts_a.get(t):
            findings.append(("HIGH", t, f"Row count changed: {counts_b.get(t)} -> {counts_a.get(t)}"))
    return findings


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    before, after = load(sys.argv[1]), load(sys.argv[2])
    with open(sys.argv[3]) as f:
        sql = f.read()

    lint_findings = lint(sql)
    drift_findings = diff(before, after)

    if any(sev == "HIGH" for sev, _, _ in drift_findings):
        verdict = "BLOCK"
    elif any(sev in ("HIGH", "MEDIUM") for sev, _, _ in lint_findings + drift_findings):
        verdict = "REVIEW"
    else:
        verdict = "SAFE"

    print("## Rehearsal report\n")
    print("### Static checks on the SQL")
    if lint_findings:
        for sev, stmt, reason in lint_findings:
            print(f"- **{sev}** `{stmt}` - {reason}")
    else:
        print("- No risky patterns found")
    print("\n### Data drift (prod vs. rehearsal branch)")
    if drift_findings:
        for sev, where, what in drift_findings:
            print(f"- **{sev}** `{where}` - {what}")
    else:
        print("- No drift: row counts, NULLs and sums are identical")
    print(f"\nVERDICT: {verdict}")


if __name__ == "__main__":
    main()
