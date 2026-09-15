# Phase 4 Evaluation Report

**Project:** AI-Powered Customer Support Automation System — Meridian Commerce
**Date:** 2026-09-14

Every number below is labeled **REAL** (from the actual database), **SIMULATED**
(from hand-built fixture data, illustrative only), or **NOT AVAILABLE**. None
is fabricated.

> **Phase 4.1 note:** the field formerly named `escalation_rate` is now
> `urgent_human_review_rate` — same computation
> (`recommended_action == "HUMAN_REVIEW_URGENT"` divided by **all** processed
> tickets, not just the human-reviewed ones), clearer name. See
> `PHASE4_SUMMARY.md` § "Phase 4.1 Cleanup Pass" for the full rationale.
> Numeric values below are unchanged from the original Phase 4 run.

---

## REAL — Full dataset, dry-run, current database state

All 1,500 real tickets, processed through the real rule engine in dry-run
mode (no writes):

```json
{
  "dry_run": true,
  "tickets_processed": 1500,
  "n_automated": 0,
  "n_human_review": 1500,
  "n_fallback": 0,
  "evaluation": {
    "metric_provenance": "REAL (in-memory batch run)",
    "automated_rate": 0.0,
    "human_review_rate": 1.0,
    "urgent_human_review_rate": 0.030666666666666665,
    "priority_distribution": { "Medium": 1454, "High": 46 },
    "rule_frequency": {
      "base_category_priority": 1500,
      "missing_classification": 1500,
      "high_value_vip_order_priority": 46
    },
    "multi_rule_frequency": 1.0,
    "conflict_frequency": 0.0,
    "fallback_frequency": 0.0
  }
}
```

**Why this looks the way it does:** every one of the 1,500 real tickets has
`ai_predicted_category IS NULL`, because Phase 3 never classified any real
ticket (no `ANTHROPIC_API_KEY` was available in this environment — same
limitation carried forward from Phase 3, re-confirmed here). The
`missing_classification` rule correctly and unconditionally routes all of
them to Human Review. This is the rule engine behaving exactly as designed
under genuinely incomplete upstream information — not a bug, and not
something to paper over.

The 46 tickets (3.07%) elevated to `High` priority are **real** VIP
customers with **real** orders above the $450 (≈90th percentile) threshold.
Spot-checked directly: customer 721 (VIP) with order 3480 ($595.88) is one
of them — confirmed by joining `customers` and `orders` directly, not
inferred.

`decisions_by_category` / `_by_sentiment_bucket` / `_by_confidence_bucket`
are **NOT AVAILABLE** here for the same reason — there is no
`ai_predicted_category` to break down by.

---

## REAL — Database verification (one representative ticket, then a second demonstration)

See `PHASE4_SUMMARY.md` §M for the full step-by-step. Summary:

- `ticket_id=1`, in its real, untouched state: dry-run confirmed zero writes
  (checked twice — once via a 10-ticket batch, once specifically with
  `RULES_DRY_RUN=false` but no `--live`, confirming the double-confirmation
  safety rule holds). A live write then produced `Human Review`/`Medium`,
  verified by reading the row before and after: only `decision_path`,
  `final_priority`, `rule_decision_at` changed. Reverted afterward.
- `ticket_id=2`: manually seeded with **test** (not real-LLM) AI field
  values to demonstrate the Automated path — real DB join data (a genuine
  VIP customer, a genuine $595.88 order) combined with the seeded test
  classification to produce `Automated`/`High`. Verified and reverted.
- Final state confirmed: `classified=0, phase4_decided=0` — the database is
  back to precisely where Phase 3 left it.

---

## SIMULATED — Fixture data illustrating the fuller range of engine behavior

**Not real tickets. Not real AI output.** Twelve hand-built examples, run
through the same real, unmodified `evaluate()` function, to show what Phase
4 will actually do once Phase 3 produces real classifications:

| ticket_id | category | decision_path | priority | recommended_action | triggered_rules |
|---|---|---|---|---|---|
| 9001 | Order Status Inquiry | Automated | Low | AUTO_RESOLVE | base_category_priority |
| 9002 | Product Question | Automated | Low | AUTO_RESOLVE | base_category_priority |
| 9003 | Delivery Delay | Automated | Medium | AUTO_RESOLVE | base_category_priority |
| 9004 | Refund Request | Human Review | Medium | HUMAN_REVIEW_STANDARD | base_category_priority, low_confidence |
| 9005 | Damaged Product | Automated | High | AUTO_RESOLVE | base_category_priority |
| 9006 | Payment Problem | Human Review | High | HUMAN_REVIEW_URGENT | base_category_priority, sensitive_category |
| 9007 | Account Problem | Human Review | Medium | HUMAN_REVIEW_STANDARD | base_category_priority, sensitive_category |
| 9008 | Complaint (sentiment -0.85) | Human Review | Urgent | HUMAN_REVIEW_URGENT | base_category_priority, strong_negative_sentiment_priority, sensitive_category, strong_negative_sentiment_review |
| 9009 | Complaint (sentiment +0.5) | Human Review | Urgent | HUMAN_REVIEW_URGENT | base_category_priority, sensitive_category, sentiment_category_conflict |
| 9010 | Refund Request (no order) | Human Review | Medium | HUMAN_REVIEW_STANDARD | base_category_priority, missing_order_context |
| 9011 | Delivery Delay (VIP, $550) | Automated | High | AUTO_RESOLVE | base_category_priority, high_value_vip_order_priority |
| 9012 | Missing Item | Automated | High | AUTO_RESOLVE | base_category_priority |

```json
{
  "metric_provenance": "SIMULATED (fixture data, not real tickets)",
  "n_processed": 12,
  "automated_rate": 0.5,
  "human_review_rate": 0.5,
  "urgent_human_review_rate": 0.25,
  "priority_distribution": {"Low": 2, "Medium": 4, "High": 4, "Urgent": 2},
  "multi_rule_frequency": 0.5833333333333334,
  "conflict_frequency": 0.16666666666666666
}
```

Notice ticket 9008 and 9009 both land on `Urgent`/`Human Review` but for
genuinely different reasons — 9008 via strongly negative sentiment, 9009 via
a category/sentiment conflict — and both get fully reported in
`triggered_rules`, not collapsed into a single opaque "flagged" bit. That's
the auditability requirement working as intended.

---

## NOT AVAILABLE

- Any accuracy/precision/recall comparison of Phase 4 decisions against a
  "correct" human decision — no such labeled dataset exists, and building
  one is out of scope for this phase.
- Real category/sentiment/confidence breakdowns of Phase 4 decisions — see
  above, contingent on Phase 3 actually running.
- Any cost/efficiency projection (e.g. "X% reduction in agent workload") —
  would require operational baseline data this project doesn't have.

## Limitations

See `PHASE4_SUMMARY.md` §O for the full list. In short: everything here is
bottlenecked on Phase 3 never having classified a real ticket, and the two
key thresholds (confidence, sentiment) are principled defaults, not
empirically tuned ones.
