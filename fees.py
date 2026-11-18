"""Versioned fee schedules and fee recomputation — the headline logic.

SYNTHETIC DATA ONLY. The company, customers, and charges in this
project are fictional; no real billing data is used anywhere.

Money is integer cents everywhere in this project — never float.
A fee is first computed exactly in millicents (thousandths of a cent)
with integer arithmetic, then converted to cents with one documented
rounding rule:

  ROUNDING RULE: round-half-up. A fee whose exact value sits exactly
  on a half-cent boundary (…x.5 cents) rounds UP to the next cent.
  ``fee_cents = (fee_millicents + 500) // 1000`` for the non-negative
  fees this kit handles — pinned by unit tests and golden eval E2.

Fee schedules are versioned with effective dates. The version that
applies to a charge is the latest version whose effective date is on
or before the charge date — never the version current at billing or
report time. That distinction is the whole point of the headline
check: a biller that keeps using the old version after a schedule
change under- (or over-) charges every affected customer, quietly.

  v1  effective 2026-01-01  base 499c + 12.75c per unit
  v2  effective 2026-02-15  base 549c + 14.75c per unit
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

# Rates are stored as integers: base in cents, per-unit in millicents
# (12.75 cents = 12_750 millicents) so no float ever touches money.
FEE_SCHEDULE: List[Dict] = [
    {
        "version": "v1",
        "effective_from": "2026-01-01",
        "base_cents": 499,
        "per_unit_millicents": 12750,
    },
    {
        "version": "v2",
        "effective_from": "2026-02-15",
        "base_cents": 549,
        "per_unit_millicents": 14750,
    },
]

SCHEDULE_BY_VERSION: Dict[str, Dict] = {s["version"]: s for s in FEE_SCHEDULE}


def schedule_for_date(charge_date: str) -> Dict:
    """The schedule version effective on ``charge_date`` (ISO string)."""
    chosen: Optional[Dict] = None
    for entry in FEE_SCHEDULE:  # ordered by effective_from
        if entry["effective_from"] <= charge_date:
            chosen = entry
    if chosen is None:
        raise ValueError(f"no fee schedule effective on {charge_date}")
    return chosen


def schedule_by_version(version: str) -> Dict:
    return SCHEDULE_BY_VERSION[version]


def fee_millicents(units: int, schedule: Dict) -> int:
    """Exact fee in millicents: base + units * per-unit rate."""
    if units < 0:
        raise ValueError("units must be >= 0")
    return schedule["base_cents"] * 1000 + units * schedule["per_unit_millicents"]


def round_half_up(millicents: int) -> int:
    """Millicents -> cents, rounding half up (the documented rule)."""
    if millicents < 0:
        raise ValueError("millicents must be >= 0")
    return (millicents + 500) // 1000


def round_half_down(millicents: int) -> int:
    """Millicents -> cents, rounding half DOWN.

    Not the kit's rule — this exists so the checker can recognise the
    signature of a biller that rounded a half-cent boundary the wrong
    way: on an exact boundary it yields exactly one cent less than
    round-half-up, and everywhere else the two agree.
    """
    if millicents < 0:
        raise ValueError("millicents must be >= 0")
    return (millicents + 499) // 1000


def compute_fee_cents(units: int, charge_date: str,
                      schedule: Optional[Dict] = None) -> int:
    """Expected fee in integer cents for a charge.

    Uses the schedule version effective on ``charge_date`` unless an
    explicit ``schedule`` is given (the checker passes v1 explicitly
    to test the fee-version-bug hypothesis).
    """
    sched = schedule if schedule is not None else schedule_for_date(charge_date)
    return round_half_up(fee_millicents(units, sched))


def is_half_cent_boundary(units: int, charge_date: str,
                          schedule: Optional[Dict] = None) -> bool:
    """True when the exact fee sits exactly on a .5-cent boundary."""
    sched = schedule if schedule is not None else schedule_for_date(charge_date)
    return fee_millicents(units, sched) % 1000 == 500


def public_schedule() -> List[Dict]:
    """JSON-safe view of the fee schedule."""
    return [dict(s) for s in FEE_SCHEDULE]
