"""Fee schedule versioning and the round-half-up rule."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fees import (compute_fee_cents, fee_millicents, is_half_cent_boundary,  # noqa: E402
                  round_half_down, round_half_up, schedule_by_version,
                  schedule_for_date)


class TestRounding(unittest.TestCase):
    def test_round_half_up_boundaries(self):
        self.assertEqual(round_half_up(0), 0)
        self.assertEqual(round_half_up(1499), 1)
        self.assertEqual(round_half_up(1500), 2)   # exactly .5 rounds UP
        self.assertEqual(round_half_up(1501), 2)
        self.assertEqual(round_half_up(2500), 3)   # exactly .5 rounds UP
        self.assertEqual(round_half_up(123500), 124)

    def test_round_half_down_differs_only_on_boundary(self):
        self.assertEqual(round_half_down(1500), 1)
        self.assertEqual(round_half_down(1499), round_half_up(1499))
        self.assertEqual(round_half_down(1501), round_half_up(1501))

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            round_half_up(-1)


class TestScheduleVersioning(unittest.TestCase):
    def test_version_effective_dates(self):
        self.assertEqual(schedule_for_date("2026-01-01")["version"], "v1")
        self.assertEqual(schedule_for_date("2026-02-14")["version"], "v1")
        self.assertEqual(schedule_for_date("2026-02-15")["version"], "v2")
        self.assertEqual(schedule_for_date("2026-03-31")["version"], "v2")

    def test_before_first_version_raises(self):
        with self.assertRaises(ValueError):
            schedule_for_date("2025-12-31")

    def test_fee_uses_version_effective_on_charge_date(self):
        v1 = schedule_by_version("v1")
        # Same units either side of the changeover price differently.
        before = compute_fee_cents(100, "2026-02-14")
        after = compute_fee_cents(100, "2026-02-15")
        self.assertEqual(before, round_half_up(fee_millicents(100, v1)))
        self.assertGreater(after, before)

    def test_hand_computed_fees(self):
        # v1: 499 + 10 * 12.75 = 626.5 -> 627 (half-up on the boundary)
        self.assertEqual(compute_fee_cents(10, "2026-01-10"), 627)
        # v2: 549 + 10 * 14.75 = 696.5 -> 697 (half-up on the boundary)
        self.assertEqual(compute_fee_cents(10, "2026-02-20"), 697)
        # v1: 499 + 11 * 12.75 = 639.25 -> 639
        self.assertEqual(compute_fee_cents(11, "2026-01-10"), 639)

    def test_money_is_int_never_float(self):
        for units in (0, 1, 10, 137, 400):
            fee = compute_fee_cents(units, "2026-02-20")
            self.assertIs(type(fee), int)

    def test_boundary_detection(self):
        # units % 4 == 2 lands exactly on a .5-cent boundary (both rates).
        self.assertTrue(is_half_cent_boundary(10, "2026-01-10"))
        self.assertTrue(is_half_cent_boundary(10, "2026-02-20"))
        self.assertFalse(is_half_cent_boundary(11, "2026-01-10"))
        self.assertFalse(is_half_cent_boundary(12, "2026-01-10"))


if __name__ == "__main__":
    unittest.main()
