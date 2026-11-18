"""CLI: generate | schedules | report | check | demo.

SYNTHETIC DATA ONLY — every bundle handled here is fabricated sample
data for a fictional usage-billing company.

Exit codes:
  check : 0 = no findings, 1 = findings present (the seeded dataset
          exits 1 BY DESIGN — it plants defects so the checker has
          something real to find; a --clean bundle exits 0),
          2 = usage / IO / validation error
  others: 0 = success, 2 = usage / IO error
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checks import build_report  # noqa: E402
from fees import public_schedule  # noqa: E402
from generator import bundle_to_json, generate_bundle  # noqa: E402
from validation import validate_bundle  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def canonical(payload) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def load_bundle(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _load_or_error(path: str):
    try:
        return load_bundle(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def _validated_or_error(path: str):
    bundle = _load_or_error(path)
    if bundle is None:
        return None
    issues = validate_bundle(bundle)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}", file=sys.stderr)
        return None
    return bundle


def _write_out(args, text: str, summary: str) -> int:
    if getattr(args, "out", None):
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(summary)
    else:
        print(text, end="")
    return EXIT_OK


def cmd_generate(args) -> int:
    bundle = generate_bundle(days=args.days, seed=args.seed, clean=args.clean)
    text = bundle_to_json(bundle)
    kind = "clean" if args.clean else "seeded"
    return _write_out(args, text,
                      f"generated {kind} bundle: {len(bundle['ledger'])} "
                      f"ledger charges, {len(bundle['events'])} billing "
                      f"events (seed={args.seed}) -> {args.out}")


def cmd_schedules(args) -> int:
    payload = {"count": len(public_schedule()),
               "fee_schedule": public_schedule(),
               "rounding_rule": "round-half-up"}
    return _write_out(args, canonical(payload),
                      f"{len(public_schedule())} fee schedule versions "
                      f"-> {args.out}")


def cmd_report(args) -> int:
    bundle = _validated_or_error(args.input)
    if bundle is None:
        return EXIT_ERROR
    return _write_out(args, canonical(build_report(bundle)),
                      f"report -> {args.out}")


def cmd_check(args) -> int:
    bundle = _load_or_error(args.input)
    if bundle is None:
        return EXIT_ERROR
    issues = validate_bundle(bundle)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}")
        print(f"check FAIL (data quality): {len(issues)} issue(s)")
        return EXIT_ERROR
    report = build_report(bundle)
    summary = report["summary"]
    print(f"ledger_charges={summary['ledger_charges']} "
          f"billing_events={summary['billing_events']} "
          f"clean_charges={summary['clean_charges']} "
          f"findings={summary['total_findings']} "
          f"impact_cents={summary['total_impact_cents']}")
    for entry in report["causes"]:
        print(f"  {entry['cause']}: count={entry['count']} "
              f"impact_cents={entry['impact_cents']}")
    if summary["total_findings"]:
        print("check FAIL: billing defects found")
        return EXIT_FAIL
    print("check PASS")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="revenue-data-quality-kit",
        description="Revenue/billing data-quality checks against a "
                    "ledger of expected charges (synthetic data).")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate a synthetic billing bundle")
    g.add_argument("--days", type=int, default=90)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--clean", action="store_true",
                   help="plant no defects (check exits 0 on this bundle)")
    g.add_argument("--out", default=None)
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("schedules", help="list the versioned fee schedules")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_schedules)

    r = sub.add_parser("report", help="root-cause report (JSON)")
    r.add_argument("--input", required=True)
    r.add_argument("--out", default=None)
    r.set_defaults(func=cmd_report)

    c = sub.add_parser("check", help="CI gate: exit 0 clean / 1 findings / 2 error")
    c.add_argument("--input", required=True)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
