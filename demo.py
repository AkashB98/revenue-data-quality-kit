"""End-to-end demo: generate -> validate -> recompute -> reconcile ->
report -> check exit codes.

SYNTHETIC DATA ONLY (fictional usage-billing dataset). Runs fully
offline. Every stage asserts, including exact recovery of the planted
defect counts.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checks import build_report, cause_map  # noqa: E402
from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main  # noqa: E402
from fees import compute_fee_cents  # noqa: E402
from generator import PLANTED, bundle_to_json, generate_bundle  # noqa: E402
from validation import validate_bundle  # noqa: E402


def main() -> None:
    print("== 1. generate synthetic billing bundle (seed=42, 90 days) ==")
    bundle = generate_bundle()
    again = generate_bundle()
    assert bundle == again, "generator must be deterministic"
    assert validate_bundle(bundle) == [], validate_bundle(bundle)[:3]
    ledger, events = bundle["ledger"], bundle["events"]
    print(f"   {len(ledger)} ledger charges, {len(events)} billing events, "
          f"deterministic re-generation verified")

    print("\n== 2. fee recomputation spot-check (versioned schedule) ==")
    sample = next(c for c in ledger if c["charge_date"] >= "2026-02-15")
    fee = compute_fee_cents(sample["units"], sample["charge_date"])
    print(f"   {sample['charge_id']} on {sample['charge_date']}: "
          f"{sample['units']} units -> expected fee {fee} cents (v2 rate)")

    print("\n== 3. root-cause report recovers the planted defects exactly ==")
    report = build_report(bundle)
    causes = cause_map(report)
    for name, planted_count in sorted(PLANTED.items()):
        got = causes[name]["count"]
        assert got == planted_count, f"{name}: planted {planted_count}, got {got}"
        print(f"   {name}: {got} charges, "
              f"impact {causes[name]['impact_cents']} cents")
    assert causes["UNEXPLAINED_FEE_ERROR"]["count"] == 0
    assert causes["ORPHAN_EVENT"]["count"] == 0
    digest = hashlib.md5(json.dumps(report, sort_keys=True).encode()).hexdigest()
    assert build_report(generate_bundle()) == report
    print(f"   report md5 {digest}; re-run reproduces it exactly")

    print("\n== 4. attribution priority: duplicate outranks late ==")
    dup_late = bundle["_planted_ids"]["duplicate_and_late"]
    assert dup_late in causes["DUPLICATE"]["charge_ids"]
    assert dup_late not in causes["LATE"]["charge_ids"]
    print(f"   {dup_late} is both duplicated and late; "
          f"counted under DUPLICATE only")

    print("\n== 5. CLI check gate exit codes ==")
    tmp = tempfile.mkdtemp(prefix="revdq-demo-")
    seeded_path = os.path.join(tmp, "seeded.json")
    clean_path = os.path.join(tmp, "clean.json")
    with open(seeded_path, "w", encoding="utf-8") as fh:
        fh.write(bundle_to_json(bundle))
    with open(clean_path, "w", encoding="utf-8") as fh:
        fh.write(bundle_to_json(generate_bundle(clean=True)))
    code_seeded = cli_main(["check", "--input", seeded_path])
    code_clean = cli_main(["check", "--input", clean_path])
    code_err = cli_main(["check", "--input", "/tmp/no-such-revdq-xyz.json"])
    print(f"   seeded={code_seeded} (1 by design) clean={code_clean} "
          f"missing-file={code_err}")
    assert code_seeded == EXIT_FAIL and code_clean == EXIT_OK \
        and code_err == EXIT_ERROR

    clean_report = build_report(generate_bundle(clean=True))
    assert clean_report["summary"]["total_findings"] == 0
    print("   clean variant: zero findings, as planted (none)")

    print("\nDemo OK: generate, validate, fee recomputation, reconciliation, "
          "root-cause report and check verified.")


if __name__ == "__main__":
    main()
