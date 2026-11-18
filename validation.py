"""Bundle validation — the data-quality gate before any check runs.

Reports issues and never raises on bad data, so the CLI can map a
malformed bundle to exit code 2 distinctly from "defects found"
(exit 1). Structural problems only: missing sections, wrong types,
duplicate ledger ids, unparseable dates, negative money. Whether the
*billing* is right is checks.py's job, not this module's.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_bundle(bundle) -> List[str]:
    issues: List[str] = []
    if not isinstance(bundle, dict):
        return ["bundle must be a JSON object"]
    for key in ("ledger", "events"):
        if key not in bundle:
            issues.append(f"missing required section: {key}")
    if issues:
        return issues
    ledger, events = bundle["ledger"], bundle["events"]
    if not isinstance(ledger, list) or not isinstance(events, list):
        return ["ledger and events must be arrays"]

    seen_ids = set()
    for i, charge in enumerate(ledger):
        if not isinstance(charge, dict):
            issues.append(f"ledger[{i}] is not an object")
            continue
        cid = charge.get("charge_id")
        if not isinstance(cid, str) or not cid:
            issues.append(f"ledger[{i}] has no charge_id")
        elif cid in seen_ids:
            issues.append(f"duplicate ledger charge_id: {cid}")
        else:
            seen_ids.add(cid)
        try:
            date.fromisoformat(charge.get("charge_date", ""))
        except (TypeError, ValueError):
            issues.append(f"{cid}: bad charge_date {charge.get('charge_date')!r}")
        if not _is_int(charge.get("units")) or charge.get("units", -1) < 0:
            issues.append(f"{cid}: units must be a non-negative integer")

    seen_events = set()
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            issues.append(f"events[{i}] is not an object")
            continue
        eid = event.get("event_id")
        if not isinstance(eid, str) or not eid:
            issues.append(f"events[{i}] has no event_id")
        elif eid in seen_events:
            issues.append(f"duplicate event_id: {eid}")
        else:
            seen_events.add(eid)
        if not isinstance(event.get("charge_id"), str):
            issues.append(f"{eid}: charge_id must be a string")
        try:
            date.fromisoformat(event.get("arrival_date", ""))
        except (TypeError, ValueError):
            issues.append(f"{eid}: bad arrival_date {event.get('arrival_date')!r}")
        if not _is_int(event.get("billed_fee_cents")):
            issues.append(f"{eid}: billed_fee_cents must be integer cents")
        elif event["billed_fee_cents"] < 0:
            issues.append(f"{eid}: billed_fee_cents must be >= 0")
    return issues
