"""Deterministic synthetic billing generator — a fictional usage-billing
company ("Meridian Metering", invented for this project).

SYNTHETIC DATA ONLY. No real company, customer, or billing data is
ever used. Everything is fabricated from a seeded PRNG so the same
seed always yields the same bundle, byte-for-byte.

The model has two sides:

  * the LEDGER — expected charges, the source of truth. One row per
    charge: charge_id, customer_id, charge_date, units. What each
    charge *should* cost is never stored on the ledger; it is always
    recomputed from the versioned fee schedule (see fees.py).
  * BILLING EVENTS — what the biller actually emitted. One row per
    event: event_id, charge_id, arrival_date, billed_fee_cents.
    Events are derived from the ledger, mostly faithfully — plus a
    small set of planted defects, each carrying one reason code.

Planted defects (seed 42, pinned by tests and golden evals):

  FEE_VERSION_BUG    12 charges dated on/after the v2 effective date
                     (2026-02-15) billed at the old v1 rate.
  ROUNDING_BOUNDARY   3 charges whose exact fee sits on a .5-cent
                     boundary, billed one cent low (rounded down
                     instead of the documented round-half-up).
  DUPLICATE           8 charges billed twice. Exactly ONE of them is
                     also late; by the documented attribution priority
                     (DUPLICATE outranks LATE) it counts only as a
                     duplicate.
  MISSING             6 ledger charges with no billing event at all.
  LATE                5 charges whose single event arrives after the
                     lateness SLA (arrival more than 3 days after the
                     charge date), excluding the duplicate-and-late
                     charge above.

The defect sets are disjoint except for the one intentional
duplicate-and-late overlap, so the checker's recovered counts can be
compared exactly against the planted counts — that comparison is the
golden eval. ``generate_bundle(clean=True)`` plants nothing: one
on-time, fee-correct event per ledger charge.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Dict, List, Set

START_DATE = date(2026, 1, 1)
DEFAULT_SEED = 42
DEFAULT_DAYS = 90
CHARGES_PER_DAY = 5
SLA_DAYS = 3  # an event is late when arrival > charge_date + SLA_DAYS

CUSTOMERS = [f"CUST-{i:03d}" for i in range(1, 16)]
PLANS = ["starter", "growth", "scale"]

# Planted defect counts (seeded variant only).
PLANTED = {
    "FEE_VERSION_BUG": 12,
    "ROUNDING_BOUNDARY": 3,
    "DUPLICATE": 8,
    "MISSING": 6,
    "LATE": 5,
}
V2_EFFECTIVE = "2026-02-15"


def _pick_spaced(candidates: List[Dict], count: int,
                 used: Set[str]) -> List[Dict]:
    """Pick ``count`` items spread evenly over ``candidates``.

    Deterministic: indexes are evenly spaced over the candidate list
    in ledger order, skipping anything already in ``used``. Picked
    charge_ids are added to ``used`` so defect sets stay disjoint.
    """
    pool = [c for c in candidates if c["charge_id"] not in used]
    if len(pool) < count:
        raise ValueError(f"need {count} candidates, only {len(pool)} available")
    if count == 1:
        picks = [pool[len(pool) // 2]]
    else:
        idxs = sorted({round(i * (len(pool) - 1) / (count - 1))
                       for i in range(count)})
        # Top up if rounding collapsed two picks onto one index.
        j = 0
        while len(idxs) < count and j < len(pool):
            if j not in idxs:
                idxs.append(j)
                idxs.sort()
            j += 1
        picks = [pool[i] for i in idxs[:count]]
    for p in picks:
        used.add(p["charge_id"])
    return picks


def generate_ledger(days: int = DEFAULT_DAYS, seed: int = DEFAULT_SEED,
                    start: date = START_DATE) -> List[Dict]:
    """The expected-charges ledger: ``days`` x 5 charges, deterministic."""
    if days < 0:
        raise ValueError("days must be >= 0")
    rng = random.Random(seed)
    ledger: List[Dict] = []
    n = 0
    for d in range(days):
        charge_date = start + timedelta(days=d)
        for _ in range(CHARGES_PER_DAY):
            n += 1
            ledger.append({
                "charge_id": f"CHG-{n:04d}",
                "customer_id": CUSTOMERS[rng.randrange(len(CUSTOMERS))],
                "charge_date": charge_date.isoformat(),
                "units": rng.randint(10, 400),
                "plan": PLANS[rng.randrange(len(PLANS))],
            })
    return ledger


def generate_bundle(days: int = DEFAULT_DAYS, seed: int = DEFAULT_SEED,
                    clean: bool = False) -> Dict:
    """A full bundle: fee schedule, ledger, and derived billing events.

    With ``clean=False`` (default) the planted defects described in
    the module docstring are applied. With ``clean=True`` every
    ledger charge gets exactly one on-time, fee-correct event.
    """
    from fees import (compute_fee_cents, is_half_cent_boundary,
                      public_schedule, schedule_by_version)

    ledger = generate_ledger(days=days, seed=seed)
    by_id = {c["charge_id"]: c for c in ledger}

    missing: Set[str] = set()
    duplicate: Set[str] = set()
    late: Set[str] = set()
    version_bug: Set[str] = set()
    rounding: Set[str] = set()
    dup_and_late_id = None

    if not clean:
        used: Set[str] = set()
        missing = {c["charge_id"] for c in
                   _pick_spaced(ledger, PLANTED["MISSING"], used)}
        dup_picks = _pick_spaced(ledger, PLANTED["DUPLICATE"], used)
        duplicate = {c["charge_id"] for c in dup_picks}
        dup_and_late_id = dup_picks[0]["charge_id"]
        late = {c["charge_id"] for c in
                _pick_spaced(ledger, PLANTED["LATE"], used)}
        after_v2 = [c for c in ledger if c["charge_date"] >= V2_EFFECTIVE]
        version_bug = {c["charge_id"] for c in
                       _pick_spaced(after_v2, PLANTED["FEE_VERSION_BUG"], used)}
        boundary = [c for c in ledger
                    if is_half_cent_boundary(c["units"], c["charge_date"])]
        rounding = {c["charge_id"] for c in
                    _pick_spaced(boundary, PLANTED["ROUNDING_BOUNDARY"], used)}

    v1 = schedule_by_version("v1")
    events: List[Dict] = []
    seq = 0

    def _emit(charge: Dict, billed_fee_cents: int, arrival: date) -> None:
        nonlocal seq
        seq += 1
        events.append({
            "event_id": f"EVT-{seq:04d}",
            "charge_id": charge["charge_id"],
            "customer_id": charge["customer_id"],
            "arrival_date": arrival.isoformat(),
            "billed_fee_cents": billed_fee_cents,
        })

    for charge in ledger:
        cid = charge["charge_id"]
        if cid in missing:
            continue
        charge_day = date.fromisoformat(charge["charge_date"])
        expected = compute_fee_cents(charge["units"], charge["charge_date"])
        billed = expected
        if cid in version_bug:
            billed = compute_fee_cents(charge["units"], charge["charge_date"],
                                       schedule=v1)
        elif cid in rounding:
            billed = expected - 1  # boundary rounded down, not half-up
        is_late = cid in late or cid == dup_and_late_id
        arrival = charge_day + timedelta(days=8 if is_late else 1)
        _emit(charge, billed, arrival)
        if cid in duplicate:
            second_arrival = charge_day + timedelta(days=8 if is_late else 2)
            _emit(charge, billed, second_arrival)

    return {
        "meta": {
            "dataset": "synthetic usage-billing bundle (fictional company)",
            "seed": seed,
            "days": days,
            "clean": bool(clean),
            "sla_days": SLA_DAYS,
            "planted": {} if clean else dict(PLANTED),
        },
        "fee_schedule": public_schedule(),
        "ledger": ledger,
        "events": events,
        "_planted_ids": {  # ground truth for tests/evals ONLY; checks.py
            # never reads this — it recovers causes from the data itself.
            "missing": sorted(missing),
            "duplicate": sorted(duplicate),
            "late": sorted(late),
            "version_bug": sorted(version_bug),
            "rounding": sorted(rounding),
            "duplicate_and_late": dup_and_late_id,
        } if not clean else {
            "missing": [], "duplicate": [], "late": [],
            "version_bug": [], "rounding": [], "duplicate_and_late": None,
        },
    }


def public_bundle(bundle: Dict) -> Dict:
    """The bundle as written to disk: ground-truth internals stripped."""
    return {k: v for k, v in bundle.items() if not k.startswith("_")}


def bundle_to_json(bundle: Dict) -> str:
    import json
    return json.dumps(public_bundle(bundle), indent=2, sort_keys=True) + "\n"
