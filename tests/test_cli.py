"""CLI behaviour and the check gate's 0 / 1 / 2 exit codes."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_ERROR, EXIT_FAIL, EXIT_OK, main as cli_main  # noqa: E402
from generator import bundle_to_json, generate_bundle  # noqa: E402


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="revdq-cli-")
        cls.seeded = os.path.join(cls.tmp, "seeded.json")
        cls.clean = os.path.join(cls.tmp, "clean.json")
        cls.bad = os.path.join(cls.tmp, "bad.json")
        with open(cls.seeded, "w", encoding="utf-8") as fh:
            fh.write(bundle_to_json(generate_bundle()))
        with open(cls.clean, "w", encoding="utf-8") as fh:
            fh.write(bundle_to_json(generate_bundle(clean=True)))
        with open(cls.bad, "w", encoding="utf-8") as fh:
            fh.write('{"ledger": [{"charge_id": "X"}], "events": []}')

    def test_generate_writes_bundle(self):
        out_path = os.path.join(self.tmp, "gen.json")
        code, out, _ = _run(["generate", "--out", out_path])
        self.assertEqual(code, EXIT_OK)
        with open(out_path, encoding="utf-8") as fh:
            bundle = json.load(fh)
        self.assertEqual(len(bundle["ledger"]), 450)
        self.assertNotIn("_planted_ids", bundle)  # ground truth not shipped

    def test_generate_clean_flag(self):
        code, out, _ = _run(["generate", "--clean"])
        self.assertEqual(code, EXIT_OK)
        bundle = json.loads(out)
        self.assertEqual(len(bundle["events"]), len(bundle["ledger"]))
        self.assertTrue(bundle["meta"]["clean"])

    def test_report_matches_direct_computation(self):
        from checks import build_report
        code, out, _ = _run(["report", "--input", self.seeded])
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out), build_report(generate_bundle()))

    def test_check_exit_codes(self):
        self.assertEqual(_run(["check", "--input", self.seeded])[0], EXIT_FAIL)
        self.assertEqual(_run(["check", "--input", self.clean])[0], EXIT_OK)
        self.assertEqual(_run(["check", "--input", self.bad])[0], EXIT_ERROR)
        self.assertEqual(
            _run(["check", "--input", "/tmp/no-such-revdq-xyz.json"])[0],
            EXIT_ERROR)

    def test_check_rejects_malformed_json(self):
        path = os.path.join(self.tmp, "junk.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("this is not json")
        self.assertEqual(_run(["check", "--input", path])[0], EXIT_ERROR)
        self.assertEqual(_run(["report", "--input", path])[0], EXIT_ERROR)

    def test_schedules_lists_both_versions(self):
        code, out, _ = _run(["schedules"])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(out)
        versions = [s["version"] for s in payload["fee_schedule"]]
        self.assertEqual(versions, ["v1", "v2"])
        self.assertEqual(payload["rounding_rule"], "round-half-up")


if __name__ == "__main__":
    unittest.main()
