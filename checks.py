"""The checks: fee recomputation + completeness reconciliation.

Two families, one root-cause report:

  (a) FEE RECOMPUTATION (the headline). Every billing event's fee is
      recomputed from the fee-schedule version effective on its
      charge date and compared with what was billed. A mismatch is
      classified by testing hypotheses in order:
        1. FEE_VERSION_BUG — the billed amount equals the fee under
           the superseded v1 schedule (only possible for charges
           dated on/after the v2 effective date).
        2. ROUNDING_BOUNDARY — the exact fee sits on a .5-cent
           boundary and the billed amount equals round-half-DOWN,
           exactly one cent below the documented round-half-up.
        3. UNEXPLAINED_FEE_ERROR — anything else. The seeded dataset
           plants none of these; the category exists so a real
           mismatch is never silently forced into a known cause.

  (b) COMPLETENESS RECONCILIATION. Ledger charges are matched
      against billing events:
        MISSING   — a ledger charge with no event at all.
        DUPLICATE — a charge with more than one event. Counted per
                    affected charge; impact is the billed amount of
                    the extra copies (what was over-collected).
        LATE      — a charge whose event arrives after the lateness
                    SLA (arrival more than ``sla_days`` after the
                    charge date). Lateness is a completeness reason
                    code, not a separate freshness family.

  ATTRIBUTION PRIORITY (documented, pinned by tests and eval E4):
  when a charge qualifies for more than one completeness cause, it
  is attributed to exactly one, in this order:
        DUPLICATE  outranks  LATE  outranks  (fee causes are judged
        on the primary event independently).
  So the one seeded charge that is both duplicated and late counts
  as DUPLICATE only, and the recovered LATE count excludes it.

Dollar impact per cause (all integer cents):
  FEE_VERSION_BUG / ROUNDING_BOUNDARY / UNEXPLAINED_FEE_ERROR —
      sum of |billed - expected| over affected charges.
  DUPLICATE — sum of the billed amounts of the extra event copies.
  MISSING   — sum of the expected fees that were never billed.
  LATE      — sum of the billed amounts that arrived late (revenue
              delayed, not lost — the report keeps it separate).

This module never reads the generator's ground-truth planting
record: every cause is recovered from the ledger, the events, and
the fee schedule alone.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List

from fees import (compute_fee_cents, fee_millicents, is_half_cent_boundary,
                  round_half_down, schedule_by_version, schedule_for_date)
from generator import SLA_DAYS

CAUSES = ["DUPLICATE", "FEE_VERSION_BUG", "LATE", "MISSING",
          "ORPHAN_EVENT", "ROUNDING_BOUNDARY", "UNEXPLAINED_FEE_ERROR"]
V1_VERSION = "v1"
V2_EFFECTIVE = "2026-02-15"


def _classify_fee_mismatch(charge: Dict, billed: int, expected: int) -> str:
    units, charge_date = charge["units"], charge["charge_date"]
    if charge_date >= V2_EFFECTIVE:
        v1_fee = compute_fee_cents(units, charge_date,
                                   schedule=schedule_by_version(V1_VERSION))
        if billed == v1_fee and billed != expected:
            return "FEE_VERSION_BUG"
    if is_half_cent_boundary(units, charge_date):
        sched = schedule_for_date(charge_date)
        if billed == round_half_down(fee_millicents(units, sched)):
            return "ROUNDING_BOUNDARY"
    return "UNEXPLAINED_FEE_ERROR"


def build_report(bundle: Dict, sla_days: int = SLA_DAYS) -> Dict:
    """Root-cause report for a validated bundle (deterministic)."""
    ledger: List[Dict] = bundle["ledger"]
    events: List[Dict] = bundle["events"]
    by_id = {c["charge_id"]: c for c in ledger}

    events_by_charge: Dict[str, List[Dict]] = {}
    for event in events:
        events_by_charge.setdefault(event["charge_id"], []).append(event)
    for group in events_by_charge.values():
        group.sort(key=lambda e: e["event_id"])

    found: Dict[str, Dict] = {
        cause: {"cause": cause, "count": 0, "impact_cents": 0,
                "charge_ids": []}
        for cause in CAUSES
    }

    def record(cause: str, charge_id: str, impact: int) -> None:
        entry = found[cause]
        entry["count"] += 1
        entry["impact_cents"] += impact
        entry["charge_ids"].append(charge_id)

    clean_charges = 0
    for charge in ledger:
        cid = charge["charge_id"]
        group = events_by_charge.get(cid, [])
        expected = compute_fee_cents(charge["units"], charge["charge_date"])
        if not group:
            record("MISSING", cid, expected)
            continue

        primary = group[0]
        billed = primary["billed_fee_cents"]
        defective = False

        # (b) duplicates — highest attribution priority.
        if len(group) > 1:
            extra = sum(e["billed_fee_cents"] for e in group[1:])
            record("DUPLICATE", cid, extra)
            defective = True
        else:
            # (b) lateness — only reached when not a duplicate.
            arrival = date.fromisoformat(primary["arrival_date"])
            charge_day = date.fromisoformat(charge["charge_date"])
            if (arrival - charge_day).days > sla_days:
                record("LATE", cid, billed)
                defective = True

        # (a) fee recomputation on the primary event.
        if billed != expected:
            cause = _classify_fee_mismatch(charge, billed, expected)
            record(cause, cid, abs(billed - expected))
            defective = True

        if not defective:
            clean_charges += 1

    for orphan_id in sorted(set(events_by_charge) - set(by_id)):
        group = events_by_charge[orphan_id]
        record("ORPHAN_EVENT", orphan_id,
               sum(e["billed_fee_cents"] for e in group))

    causes = [found[c] for c in sorted(found) if found[c]["count"] > 0]
    for entry in causes:
        entry["charge_ids"] = sorted(entry["charge_ids"])
    total_findings = sum(e["count"] for e in causes)
    total_impact = sum(e["impact_cents"] for e in causes)

    return {
        "summary": {
            "ledger_charges": len(ledger),
            "billing_events": len(events),
            "clean_charges": clean_charges,
            "total_findings": total_findings,
            "total_impact_cents": total_impact,
            "sla_days": sla_days,
        },
        "causes": causes,
    }


def cause_map(report: Dict) -> Dict[str, Dict]:
    """Causes keyed by name, zero-filled for causes with no findings."""
    out = {cause: {"cause": cause, "count": 0, "impact_cents": 0,
                   "charge_ids": []} for cause in CAUSES}
    for entry in report["causes"]:
        out[entry["cause"]] = entry
    return out
