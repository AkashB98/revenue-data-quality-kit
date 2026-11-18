"""No-network enforcement: with sockets blocked, generating, validating,
recomputing and reporting must all still work. This kit has no serve
command and no network surface at all."""

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Blocker:
    def __init__(self, *a, **k):
        raise RuntimeError("network access blocked in hermetic test")


class TestNoNetwork(unittest.TestCase):
    def setUp(self):
        self._real_socket = socket.socket
        socket.socket = _Blocker
        import urllib.request as urlreq
        self._real_urlopen = urlreq.urlopen
        urlreq.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("network access blocked in hermetic test"))

    def tearDown(self):
        socket.socket = self._real_socket
        import urllib.request as urlreq
        urlreq.urlopen = self._real_urlopen

    def test_full_pipeline_offline(self):
        from checks import build_report
        from generator import PLANTED, generate_bundle
        from validation import validate_bundle
        bundle = generate_bundle()
        self.assertEqual(validate_bundle(bundle), [])
        report = build_report(bundle)
        self.assertEqual(report["summary"]["total_findings"],
                         sum(PLANTED.values()))

    def test_no_module_opens_sockets_at_import(self):
        for mod in ("generator", "fees", "checks", "validation", "cli", "demo"):
            sys.modules.pop(mod, None)
        import checks, cli, demo, fees, generator, validation  # noqa: F401
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
