# revenue-data-quality-kit

**Revenue and billing data quality, checked the way a billing team actually needs it: every received charge recomputed against a versioned fee schedule, the ledger reconciled against what was really billed, and a root-cause report that prices each failure in dollars.**

Usage billing fails quietly. A fee schedule changes on a known date, but the biller keeps applying the old rate. A rounding rule is implemented one cent off, but only on exact half-cent boundaries, so it hides for weeks. Events arrive twice, arrive late, or never arrive — and the monthly revenue number is wrong in four different directions at once, with no way to say *why*. This project is the data-quality answer to that mess: a **ledger of expected charges** as the source of truth, **fee recomputation** against the schedule version effective on each charge's own date as the headline check, completeness reconciliation as the supporting check, and a deterministic **root-cause report** — per-cause counts and dollar impact — pinned by tests and golden evals so the recovery of every planted defect is exact, not approximate.

> **Synthetic data only.** Every figure is fabricated by a seeded generator for a fictional usage-billing company (**Meridian Metering**). No real company, customer, or billing data is used anywhere in this project.

Stdlib-only Python. Zero network, zero API keys, zero external dependencies. Money is **integer cents everywhere — never float** — computed exactly in millicents and converted with one documented rule: **round-half-up** (a fee sitting exactly on a .5-cent boundary rounds up; the rule is stated here, implemented in one place, and pinned by a test).

## Quickstart

```bash
# 1. Generate the synthetic bundle (ledger + billing events, seed 42)
python3 cli.py generate --out bundle.json

# 2. List the versioned fee schedules and the rounding rule
python3 cli.py schedules

# 3. Root-cause report: per-cause counts + dollar impact (JSON)
python3 cli.py report --input bundle.json

# 4. CI gate: exit 1 BY DESIGN on the seeded bundle (it plants defects
#    so the checker has something real to find), exit 2 on bad input
python3 cli.py check --input bundle.json

# 5. The clean variant plants nothing — and the gate passes
python3 cli.py generate --clean --out clean.json
python3 cli.py check --input clean.json   # exit 0

# 6. One-command end-to-end demo (generate -> recompute -> reconcile)
python3 demo.py
```

## The seeded dataset at a glance (seed 42, 90 days, 2026-01-01 → 2026-03-31)

A ledger of **450 expected charges** for **15 fictional customers** (5 charges a day for 90 days), worth **$15,024.28** at the correct fees. The biller emitted **452 events** totalling **$15,142.88** — a net over-billing that conceals five distinct planted defects pulling in different directions. The checker recovers every one of them, exactly:

| Root cause | Charges | Dollar impact | What happened |
|---|---|---|---|
| Fee version bug | 12 | $66.02 under-billed | Charges dated on/after the v2 effective date (2026-02-15) billed at the old v1 rate |
| Rounding boundary | 3 | $0.03 under-billed | Exact .5-cent fees rounded down instead of half-up — one cent each |
| Duplicate | 8 | $294.25 over-collected | Charges billed twice; the extra copies' billed amounts |
| Missing | 6 | $109.60 never billed | Ledger charges with no billing event at all |
| Late | 5 | $152.99 delayed | Events arriving after the 3-day lateness SLA (a completeness reason code, not a separate freshness family) |

**34 findings, 416 clean charges, $622.89 total impact.** One charge is both duplicated *and* late; by the documented attribution priority (**DUPLICATE outranks LATE**) it counts once, under DUPLICATE — which is why LATE reads 5 and not 6. The three-cent rounding row is the point of the exercise: a per-event error too small to trip any aggregate threshold, found anyway because every fee is recomputed, and priced honestly at three cents instead of being rounded up into a scarier story. These numbers are pinned by golden evals, so any change to the generator, the schedules, or the checker shows up as an eval failure, not a surprise.

## How it works

**Versioned fee schedules.** Two versions live in `fees.py` as pure integer data — **v1** effective 2026-01-01 (base 499¢ + 12.75¢ per unit) and **v2** effective 2026-02-15 (base 549¢ + 14.75¢ per unit). The version that prices a charge is the one effective on the *charge date*, never the one current at billing or report time. Rates are stored in millicents so the exact fee is integer arithmetic end to end; the single conversion to cents applies round-half-up.

**Fee recomputation (the headline check).** For every charge that was billed, the expected fee is recomputed from the schedule and compared with the billed amount. A mismatch is classified by testing hypotheses in order: does the billed amount equal the fee under the superseded v1 schedule (→ `FEE_VERSION_BUG`)? Does the exact fee sit on a .5-cent boundary with the billed amount equal to round-half-*down* (→ `ROUNDING_BOUNDARY`)? Anything else lands in `UNEXPLAINED_FEE_ERROR` — a category the seeded data never triggers, kept so a real-world mismatch is reported honestly rather than forced into a known cause.

**Completeness reconciliation (the supporting check).** Ledger charges are matched against events: no event → `MISSING`; more than one → `DUPLICATE` (impact = the extra copies' billed amounts); arrival more than 3 days after the charge date → `LATE`. Events pointing at no ledger charge are reported as `ORPHAN_EVENT`. Attribution is single-cause per charge with the priority **DUPLICATE > LATE**, documented here and pinned by eval E4; fee causes are judged on the primary event independently.

**The root-cause report.** One deterministic JSON document: per-cause counts, dollar impact in integer cents, and the affected charge ids, plus summary totals. It contains no timestamps and no randomness — the same bundle produces the same report byte for byte (md5 `1d2a933cd64768445822e0d2906b3a04`, verified identical across 3 runs). The checker recovers causes from the ledger, the events, and the schedule alone; the generator's planting record is stripped from the written bundle and never read by the checks (a test corrupts it and asserts the report does not change).

**Data quality first.** `validation.py` runs before any check: required sections, duplicate ledger/event ids, parseable dates, integer non-negative cents, int/bool traps. It reports issues and never raises on bad data, so the `check` gate maps malformed input to exit code 2, distinctly from defects found (exit 1) and clean (exit 0).

## Architecture

| Module | Job |
|---|---|
| `fees.py` | The versioned fee schedules (v1/v2, effective dates), exact millicent fee computation, and the round-half-up rule — the single source of truth every recomputation derives from |
| `generator.py` | Deterministic synthetic bundle (seed 42): 450-charge ledger over 90 days + billing events derived from it with five planted defect families; `--clean` variant plants nothing |
| `checks.py` | Fee recomputation with hypothesis classification (version bug / rounding boundary / unexplained) + completeness reconciliation (missing / duplicate / late) with documented attribution priority; builds the root-cause report |
| `validation.py` | Structural gate: sections, duplicate ids, date parsing, integer-cents and range checks — reports issues, never raises on bad data |
| `cli.py` | `generate` (seeded or `--clean`) / `schedules` / `report` (JSON root-cause report) / `check` (CI exit 0 clean / 1 findings / 2 error) / `demo` |
| `demo.py` | End-to-end run with asserts: determinism, exact planted-cause recovery, attribution priority, clean-variant zero findings, check exit codes |
| `fixtures/` | The full seeded bundle (`sample_bundle.json`) with pinned totals |

## Evals

`python3 evals/run_evals.py` → **10/10 golden evals**, report committed at `evals/eval_report.json` (md5 `6b69070e554a2f8e303262dc760bdbe9`, byte-identical across 3 verified runs):

- **E1** determinism — bundle JSON and root-cause report pinned by md5 (seed 42)
- **E2** rounding rule hand-computed — half-up on exact boundaries, in both schedule versions
- **E3** exact planted-cause recovery — counts 12/3/8/6/5 *and* the exact charge ids per cause; zero unexplained, zero orphans
- **E4** attribution priority — the duplicate-and-late charge counts under DUPLICATE only
- **E5** dollar impacts pinned per cause (total $622.89)
- **E6** version-bug charges billed at exactly the v1 schedule, all dated on/after 2026-02-15
- **E7** clean variant — zero findings, all 450 charges clean
- **E8** CLI `check` exit codes 1 / 0 / 2 (seeded by design / clean / missing file)
- **E9** validation flags planted structural defects; generated bundles validate clean
- **E10** bundled fixture pinned (450 charges, 452 events, identical report)

Unit tests: `python3 -m unittest discover -s tests` → **50 hermetic tests**, including a no-network enforcement test (sockets stubbed), hand-computed fees in both schedule versions, the rounding boundary in both directions, planted-defect anatomy (disjoint sets, the one intentional overlap), exact recovery with the ground-truth record corrupted, CLI exit codes, and validation defects.

## Development loop — what the checks actually caught

1. **The checker nearly graded its own homework.** The first design let the report builder read the generator's planting record to "confirm" its findings — which would have made exact recovery a tautology. The planting record is now stripped from the written bundle, and a unit test corrupts it in memory and asserts the report is unchanged: recovery has to come from recomputation and reconciliation, or it does not count.
2. **Attribution had to be decided before it could be tested.** The first reconciliation draft counted the duplicate-and-late charge under *both* causes, inflating LATE to 6 and making "exact recovery" ambiguous — is the planted LATE count 5 or 6? The fix was a documented priority (DUPLICATE outranks LATE), a generator that plants exactly one overlap on purpose, and an eval that pins the outcome. Ambiguous attribution is how real billing reports end up double-counting the same dollars.
3. **A one-cent error class needs a hypothesis, not a threshold.** An early classifier bucketed every small fee delta as "rounding". That would also have swallowed a genuine one-cent version or data error. The classifier now requires the full signature — exact fee on a .5-cent boundary *and* billed equal to round-half-down — and anything else falls through to `UNEXPLAINED_FEE_ERROR` instead of being explained away.

## POC framing

Framed as a proof of concept for a client with usage-based billing, this kit is the first two weeks of the engagement, made inspectable:

- **Week 1 — reconcile one period.** Point the checks at one month of the client's ledger and billing export (the bundle format is the contract: charge id, date, units in; event id, charge id, arrival, billed cents in). The deliverable is the root-cause report: how much revenue each failure mode is worth, ranked — the version bug and the duplicates pay for the engagement; the three-cent rounding row proves the recomputation is per-event, not sampled.
- **Week 2 — gate the pipeline.** Wire `check` into the billing run as a CI-style gate: exit 1 blocks the invoice batch with the report attached, exit 2 means the export itself is malformed. Schedule changes become data (a new version row with an effective date), never code changes, so the next rate change is reviewed in a diff instead of discovered in a refund queue.
- **What production adds** (out of scope here, named honestly): ingestion from the real billing and metering systems, partial payments/refunds/credits, tax and proration rules, multi-currency rounding law, and an alerting path for `UNEXPLAINED_FEE_ERROR` — the category that matters most once the known causes are fixed.

## Scope and honest limits

- **Synthetic data only.** The defect mix (34 of 450 charges) is far denser than a healthy production bill run; it exists so every cause is exercised and exactly recoverable. Real rates would be noisier and the unexplained category would do real work.
- **One fee shape.** Fees are base + per-unit with two schedule versions. No tiers, proration, discounts, taxes, credits, or refunds — each is a real billing behaviour this kit does not model, and the report says nothing about them.
- **Lateness is a reason code, not a freshness system.** The SLA is a flat 3 days from charge date; there are no business-day calendars, no per-plan SLAs, and late impact is billed amount *delayed*, kept separate from amounts lost or over-collected.
- **Counts are per affected charge.** A charge billed three times would still count once under DUPLICATE (its impact would carry both extra copies). That convention is documented because changing it silently would change every number in the report.

## Why this project

It takes the author's day-job craft — marketing and portfolio analytics: reconciling what a system *should* have produced against what it *did*, in GA4, tag, and revenue reporting — and rebuilds it as a data-quality engineering artifact: a ledger as source of truth, fees recomputed from versioned definitions, causes attributed by a stated priority, and every dollar of impact traced to named charges. The same discipline a forward-deployed engineer brings to a customer problem: make the logic inspectable, make the outputs reproducible, and make the failure modes exit codes.
