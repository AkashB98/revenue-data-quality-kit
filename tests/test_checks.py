"""Recomputation + reconciliation: exact planted-cause recovery."""

import copy
import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from checks import build_report, cause_map  # noqa: E402
from fees import compute_fee_cents  # noqa: E402
from generator import PLANTED, generate_bundle  # noqa: E402


class TestSeededRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = generate_bundle()
        cls.report = build_report(cls.bundle)
        cls.causes = cause_map(cls.report)
        cls.planted = cls.bundle["_planted_ids"]

    def test_recovers_exactly_the_planted_counts(self):
        for name, count in PLANTED.items():
            self.assertEqual(self.causes[name]["count"], count, name)
        self.assertEqual(self.causes["UNEXPLAINED_FEE_ERROR"]["count"], 0)
        self.assertEqual(self.causes["ORPHAN_EVENT"]["count"], 0)

    def test_recovers_exactly_the_planted_charges(self):
        self.assertEqual(self.causes["FEE_VERSION_BUG"]["charge_ids"],
                         self.planted["version_bug"])
        self.assertEqual(self.causes["ROUNDING_BOUNDARY"]["charge_ids"],
                         self.planted["rounding"])
        self.assertEqual(self.causes["DUPLICATE"]["charge_ids"],
                         self.planted["duplicate"])
        self.assertEqual(self.causes["MISSING"]["charge_ids"],
                         self.planted["missing"])
        self.assertEqual(self.causes["LATE"]["charge_ids"],
                         self.planted["late"])

    def test_rounding_impact_is_three_cents(self):
        # 3 boundary charges, each billed exactly 1 cent low.
        self.assertEqual(self.causes["ROUNDING_BOUNDARY"]["impact_cents"], 3)

    def test_duplicate_impact_is_extra_copies_billed(self):
        by_id = {c["charge_id"]: c for c in self.bundle["ledger"]}
        events = {}
        for e in self.bundle["events"]:
            events.setdefault(e["charge_id"], []).append(e)
        expected_impact = 0
        for cid in self.planted["duplicate"]:
            group = sorted(events[cid], key=lambda e: e["event_id"])
            expected_impact += group[1]["billed_fee_cents"]
        self.assertEqual(self.causes["DUPLICATE"]["impact_cents"],
                         expected_impact)
        # Sanity: duplicate charges are fee-correct, so impact is the
        # full expected fee of each duplicated charge.
        fee_sum = sum(compute_fee_cents(by_id[c]["units"],
                                        by_id[c]["charge_date"])
                      for c in self.planted["duplicate"])
        self.assertEqual(expected_impact, fee_sum)

    def test_missing_impact_is_expected_fees_never_billed(self):
        by_id = {c["charge_id"]: c for c in self.bundle["ledger"]}
        expected_impact = sum(
            compute_fee_cents(by_id[c]["units"], by_id[c]["charge_date"])
            for c in self.planted["missing"])
        self.assertEqual(self.causes["MISSING"]["impact_cents"],
                         expected_impact)

    def test_summary_totals(self):
        s = self.report["summary"]
        self.assertEqual(s["ledger_charges"], len(self.bundle["ledger"]))
        self.assertEqual(s["billing_events"], len(self.bundle["events"]))
        self.assertEqual(s["total_findings"], sum(PLANTED.values()))
        self.assertEqual(
            s["clean_charges"],
            s["ledger_charges"] - len(set().union(*[
                set(self.planted[k]) for k in
                ("version_bug", "rounding", "duplicate", "missing", "late")])))

    def test_report_deterministic_and_md5_stable(self):
        again = build_report(generate_bundle())
        self.assertEqual(again, self.report)
        digest = hashlib.md5(
            json.dumps(self.report, sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest, "1d2a933cd64768445822e0d2906b3a04")

    def test_checker_ignores_ground_truth_block(self):
        # Stripping (or corrupting) the planting record changes nothing:
        # causes are recovered from ledger + events + schedule alone.
        stripped = {k: v for k, v in self.bundle.items()
                    if not k.startswith("_")}
        self.assertEqual(build_report(stripped), self.report)
        corrupted = copy.deepcopy(self.bundle)
        corrupted["_planted_ids"] = {"missing": [], "duplicate": [],
                                     "late": [], "version_bug": [],
                                     "rounding": [],
                                     "duplicate_and_late": None}
        self.assertEqual(build_report(corrupted), self.report)


class TestAttributionPriority(unittest.TestCase):
    def test_duplicate_outranks_late(self):
        bundle = generate_bundle()
        causes = cause_map(build_report(bundle))
        dup_late = bundle["_planted_ids"]["duplicate_and_late"]
        self.assertIn(dup_late, causes["DUPLICATE"]["charge_ids"])
        self.assertNotIn(dup_late, causes["LATE"]["charge_ids"])
        self.assertEqual(causes["LATE"]["count"], PLANTED["LATE"])


class TestCleanAndHandmade(unittest.TestCase):
    def test_clean_bundle_zero_findings(self):
        report = build_report(generate_bundle(clean=True))
        self.assertEqual(report["causes"], [])
        self.assertEqual(report["summary"]["total_findings"], 0)
        self.assertEqual(report["summary"]["clean_charges"],
                         report["summary"]["ledger_charges"])

    def test_unexplained_fee_error_not_forced_into_known_cause(self):
        bundle = generate_bundle(clean=True)
        bundle["events"][0]["billed_fee_cents"] += 7  # arbitrary wrong fee
        causes = cause_map(build_report(bundle))
        self.assertEqual(causes["UNEXPLAINED_FEE_ERROR"]["count"], 1)
        self.assertEqual(causes["UNEXPLAINED_FEE_ERROR"]["impact_cents"], 7)

    def test_orphan_event_reported(self):
        bundle = generate_bundle(clean=True)
        bundle["events"].append({
            "event_id": "EVT-9999", "charge_id": "CHG-9999",
            "customer_id": "CUST-001", "arrival_date": "2026-01-05",
            "billed_fee_cents": 100})
        causes = cause_map(build_report(bundle))
        self.assertEqual(causes["ORPHAN_EVENT"]["count"], 1)
        self.assertEqual(causes["ORPHAN_EVENT"]["impact_cents"], 100)


if __name__ == "__main__":
    unittest.main()
