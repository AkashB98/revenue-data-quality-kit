"""Validation: structural defects flagged, generated bundles clean."""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_bundle  # noqa: E402
from validation import validate_bundle  # noqa: E402


class TestValidation(unittest.TestCase):
    def test_generated_bundles_validate_clean(self):
        self.assertEqual(validate_bundle(generate_bundle()), [])
        self.assertEqual(validate_bundle(generate_bundle(clean=True)), [])

    def test_missing_sections(self):
        self.assertTrue(validate_bundle({}))
        self.assertTrue(validate_bundle({"ledger": []}))
        self.assertTrue(validate_bundle("not a dict"))

    def test_duplicate_ledger_id_flagged(self):
        bundle = copy.deepcopy(generate_bundle(clean=True))
        bundle["ledger"].append(dict(bundle["ledger"][0]))
        issues = validate_bundle(bundle)
        self.assertTrue(any("duplicate ledger charge_id" in i for i in issues))

    def test_bad_types_flagged(self):
        bundle = copy.deepcopy(generate_bundle(clean=True))
        bundle["ledger"][0]["units"] = 12.5       # float units: not allowed
        bundle["events"][0]["billed_fee_cents"] = "lots"
        bundle["events"][1]["arrival_date"] = "yesterday"
        issues = validate_bundle(bundle)
        self.assertEqual(len(issues), 3)

    def test_bool_is_not_int(self):
        bundle = copy.deepcopy(generate_bundle(clean=True))
        bundle["events"][0]["billed_fee_cents"] = True
        self.assertTrue(validate_bundle(bundle))

    def test_negative_money_flagged(self):
        bundle = copy.deepcopy(generate_bundle(clean=True))
        bundle["events"][0]["billed_fee_cents"] = -5
        self.assertTrue(validate_bundle(bundle))


if __name__ == "__main__":
    unittest.main()
