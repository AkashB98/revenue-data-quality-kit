"""Generator determinism, shape, and the planted defect sets."""

import hashlib
import json
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fees import compute_fee_cents, is_half_cent_boundary, schedule_by_version  # noqa: E402
from generator import (DEFAULT_DAYS, PLANTED, bundle_to_json,  # noqa: E402
                       generate_bundle, generate_ledger)


class TestLedger(unittest.TestCase):
    def test_default_shape_and_dates(self):
        ledger = generate_ledger()
        self.assertEqual(len(ledger), DEFAULT_DAYS * 5)
        self.assertEqual(ledger[0]["charge_date"], "2026-01-01")
        self.assertEqual(ledger[-1]["charge_date"], "2026-03-31")
        ids = [c["charge_id"] for c in ledger]
        self.assertEqual(len(ids), len(set(ids)))

    def test_determinism(self):
        self.assertEqual(generate_bundle(), generate_bundle())
        self.assertEqual(bundle_to_json(generate_bundle()),
                         bundle_to_json(generate_bundle()))

    def test_seed_changes_output(self):
        self.assertNotEqual(generate_ledger(5, seed=1),
                            generate_ledger(5, seed=2))

    def test_negative_days_rejected(self):
        with self.assertRaises(ValueError):
            generate_ledger(-1)


class TestPlantedDefects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = generate_bundle()
        cls.planted = cls.bundle["_planted_ids"]
        cls.by_id = {c["charge_id"]: c for c in cls.bundle["ledger"]}
        cls.events_by_charge = {}
        for e in cls.bundle["events"]:
            cls.events_by_charge.setdefault(e["charge_id"], []).append(e)

    def test_planted_counts(self):
        self.assertEqual(len(self.planted["version_bug"]), PLANTED["FEE_VERSION_BUG"])
        self.assertEqual(len(self.planted["rounding"]), PLANTED["ROUNDING_BOUNDARY"])
        self.assertEqual(len(self.planted["duplicate"]), PLANTED["DUPLICATE"])
        self.assertEqual(len(self.planted["missing"]), PLANTED["MISSING"])
        self.assertEqual(len(self.planted["late"]), PLANTED["LATE"])

    def test_defect_sets_disjoint_except_dup_late(self):
        sets = [set(self.planted[k]) for k in
                ("version_bug", "rounding", "duplicate", "missing", "late")]
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                self.assertEqual(sets[i] & sets[j], set())
        self.assertIn(self.planted["duplicate_and_late"],
                      self.planted["duplicate"])
        self.assertNotIn(self.planted["duplicate_and_late"],
                         self.planted["late"])

    def test_version_bug_charges_billed_at_v1(self):
        v1 = schedule_by_version("v1")
        for cid in self.planted["version_bug"]:
            charge = self.by_id[cid]
            self.assertGreaterEqual(charge["charge_date"], "2026-02-15")
            expected_v1 = compute_fee_cents(
                charge["units"], charge["charge_date"], schedule=v1)
            expected = compute_fee_cents(charge["units"], charge["charge_date"])
            billed = self.events_by_charge[cid][0]["billed_fee_cents"]
            self.assertEqual(billed, expected_v1)
            self.assertNotEqual(billed, expected)

    def test_rounding_charges_on_boundary_and_one_cent_low(self):
        for cid in self.planted["rounding"]:
            charge = self.by_id[cid]
            self.assertTrue(is_half_cent_boundary(
                charge["units"], charge["charge_date"]))
            expected = compute_fee_cents(charge["units"], charge["charge_date"])
            billed = self.events_by_charge[cid][0]["billed_fee_cents"]
            self.assertEqual(billed, expected - 1)

    def test_missing_charges_have_no_event(self):
        for cid in self.planted["missing"]:
            self.assertNotIn(cid, self.events_by_charge)

    def test_duplicate_charges_have_two_events(self):
        for cid in self.planted["duplicate"]:
            self.assertEqual(len(self.events_by_charge[cid]), 2)

    def test_late_events_arrive_after_sla(self):
        for cid in self.planted["late"]:
            charge = self.by_id[cid]
            event = self.events_by_charge[cid][0]
            delta = (date.fromisoformat(event["arrival_date"])
                     - date.fromisoformat(charge["charge_date"]))
            self.assertGreater(delta, timedelta(days=3))

    def test_dup_and_late_charge_is_also_late_in_data(self):
        cid = self.planted["duplicate_and_late"]
        charge = self.by_id[cid]
        for event in self.events_by_charge[cid]:
            delta = (date.fromisoformat(event["arrival_date"])
                     - date.fromisoformat(charge["charge_date"]))
            self.assertGreater(delta, timedelta(days=3))

    def test_all_other_events_clean(self):
        defective = set()
        for key in ("version_bug", "rounding", "duplicate", "missing", "late"):
            defective |= set(self.planted[key])
        for charge in self.bundle["ledger"]:
            cid = charge["charge_id"]
            if cid in defective:
                continue
            group = self.events_by_charge[cid]
            self.assertEqual(len(group), 1)
            self.assertEqual(group[0]["billed_fee_cents"], compute_fee_cents(
                charge["units"], charge["charge_date"]))
            delta = (date.fromisoformat(group[0]["arrival_date"])
                     - date.fromisoformat(charge["charge_date"]))
            self.assertLessEqual(delta, timedelta(days=3))

    def test_bundle_json_md5_pinned(self):
        md5 = hashlib.md5(bundle_to_json(generate_bundle()).encode()).hexdigest()
        self.assertEqual(md5, "c7ba604377b4dbc77b5d11e85735129c")


class TestCleanVariant(unittest.TestCase):
    def test_clean_bundle_has_one_correct_event_per_charge(self):
        bundle = generate_bundle(clean=True)
        self.assertEqual(len(bundle["events"]), len(bundle["ledger"]))
        by_id = {c["charge_id"]: c for c in bundle["ledger"]}
        for event in bundle["events"]:
            charge = by_id[event["charge_id"]]
            self.assertEqual(event["billed_fee_cents"], compute_fee_cents(
                charge["units"], charge["charge_date"]))


if __name__ == "__main__":
    unittest.main()
