"""Golden evals for revenue-data-quality-kit.

SYNTHETIC DATA ONLY (fictional usage-billing dataset). Every eval is
deterministic: run_evals.py writes eval_report.json and the file must
be byte-identical across runs. No timestamps, ports, or temp paths
enter the report — only names, booleans, pinned counts and hashes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from checks import build_report, cause_map  # noqa: E402
from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main  # noqa: E402
from fees import (compute_fee_cents, round_half_down, round_half_up,  # noqa: E402
                  schedule_by_version)
from generator import PLANTED, bundle_to_json, generate_bundle  # noqa: E402
from validation import validate_bundle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(ROOT, "fixtures", "sample_bundle.json")
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def main():
    print("== golden evals: revenue-data-quality-kit ==")
    bundle = generate_bundle()
    report = build_report(bundle)
    causes = cause_map(report)
    planted = bundle["_planted_ids"]

    # E1: generator determinism (bytes pinned) + report md5 stable
    text1 = bundle_to_json(generate_bundle())
    text2 = bundle_to_json(generate_bundle())
    bundle_md5 = hashlib.md5(text1.encode()).hexdigest()
    report_md5 = hashlib.md5(
        json.dumps(report, sort_keys=True).encode()).hexdigest()
    check("E1 determinism (bundle + report md5 pinned, seed=42)",
          text1 == text2
          and bundle_md5 == "c7ba604377b4dbc77b5d11e85735129c"
          and report_md5 == "1d2a933cd64768445822e0d2906b3a04",
          f"bundle_md5={bundle_md5} report_md5={report_md5}")

    # E2: the rounding rule, pinned on hand-computed boundaries
    check("E2 rounding rule is round-half-up (hand-computed)",
          round_half_up(1500) == 2 and round_half_up(2500) == 3
          and round_half_down(1500) == 1
          and compute_fee_cents(10, "2026-01-10") == 627   # 626.5 -> up
          and compute_fee_cents(10, "2026-02-20") == 697)  # 696.5 -> up

    # E3: exact planted-cause recovery (counts AND charge ids)
    exact = all(causes[name]["count"] == count
                for name, count in PLANTED.items())
    exact_ids = (
        causes["FEE_VERSION_BUG"]["charge_ids"] == planted["version_bug"]
        and causes["ROUNDING_BOUNDARY"]["charge_ids"] == planted["rounding"]
        and causes["DUPLICATE"]["charge_ids"] == planted["duplicate"]
        and causes["MISSING"]["charge_ids"] == planted["missing"]
        and causes["LATE"]["charge_ids"] == planted["late"])
    check("E3 exact planted-cause recovery (12/3/8/6/5, ids match)",
          exact and exact_ids
          and causes["UNEXPLAINED_FEE_ERROR"]["count"] == 0
          and causes["ORPHAN_EVENT"]["count"] == 0,
          f"findings={report['summary']['total_findings']}")

    # E4: attribution priority — DUPLICATE outranks LATE
    dup_late = planted["duplicate_and_late"]
    check("E4 attribution priority (duplicate-and-late counts once)",
          dup_late in causes["DUPLICATE"]["charge_ids"]
          and dup_late not in causes["LATE"]["charge_ids"]
          and causes["DUPLICATE"]["count"] == 8
          and causes["LATE"]["count"] == 5,
          f"dup_and_late={dup_late}")

    # E5: dollar impacts pinned per cause
    check("E5 dollar impacts pinned (integer cents)",
          causes["FEE_VERSION_BUG"]["impact_cents"] == 6602
          and causes["ROUNDING_BOUNDARY"]["impact_cents"] == 3
          and causes["DUPLICATE"]["impact_cents"] == 29425
          and causes["MISSING"]["impact_cents"] == 10960
          and causes["LATE"]["impact_cents"] == 15299
          and report["summary"]["total_impact_cents"] == 62289)

    # E6: fee-version hypothesis — version-bug charges price at v1
    v1 = schedule_by_version("v1")
    by_id = {c["charge_id"]: c for c in bundle["ledger"]}
    events = {}
    for e in bundle["events"]:
        events.setdefault(e["charge_id"], []).append(e)
    version_ok = all(
        events[cid][0]["billed_fee_cents"] == compute_fee_cents(
            by_id[cid]["units"], by_id[cid]["charge_date"], schedule=v1)
        and by_id[cid]["charge_date"] >= "2026-02-15"
        for cid in planted["version_bug"])
    check("E6 version-bug charges billed exactly at the v1 schedule",
          version_ok)

    # E7: clean variant — zero findings, check exits 0
    import tempfile
    tmp = tempfile.mkdtemp(prefix="revdq-evals-")
    clean_path = os.path.join(tmp, "clean.json")
    seeded_path = os.path.join(tmp, "seeded.json")
    with open(clean_path, "w", encoding="utf-8") as fh:
        fh.write(bundle_to_json(generate_bundle(clean=True)))
    with open(seeded_path, "w", encoding="utf-8") as fh:
        fh.write(bundle_to_json(bundle))
    clean_report = build_report(generate_bundle(clean=True))
    check("E7 clean variant has zero findings",
          clean_report["causes"] == []
          and clean_report["summary"]["total_findings"] == 0
          and clean_report["summary"]["clean_charges"] == 450)

    # E8: CLI check exit codes 1 (seeded, by design) / 0 (clean) / 2 (bad)
    codes = (_run_cli(["check", "--input", seeded_path]),
             _run_cli(["check", "--input", clean_path]),
             _run_cli(["check", "--input", "/tmp/no-such-revdq-xyz.json"]))
    check("E8 CLI check exit codes 1/0/2",
          codes == (EXIT_FAIL, EXIT_OK, EXIT_ERROR), f"codes={codes}")

    # E9: validation flags planted structural defects; bundles clean
    import copy
    bad = copy.deepcopy(generate_bundle(clean=True))
    bad["ledger"].append(dict(bad["ledger"][0]))
    bad["events"][0]["billed_fee_cents"] = -1
    check("E9 validation flags defects, generated bundles clean",
          len(validate_bundle(bad)) == 2
          and validate_bundle(bundle) == []
          and validate_bundle(generate_bundle(clean=True)) == [])

    # E10: bundled fixture pinned (450 charges, same report)
    with open(FIXTURE, encoding="utf-8") as fh:
        fixture = json.load(fh)
    check("E10 fixture pinned (450 charges, 452 events, same report)",
          len(fixture["ledger"]) == 450 and len(fixture["events"]) == 452
          and validate_bundle(fixture) == []
          and build_report(fixture) == report)

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    summary_doc = {"passed": passed, "total": total,
                   "all_passed": passed == total, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total} evals passed -> evals/eval_report.json")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
