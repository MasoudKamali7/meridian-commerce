"""
Meridian Commerce — Phase 3/4: Pipeline (CLI entry point)

Phase 3 (AI classification):
    python -m src.pipeline classify --limit 10          (dry run by default)
    python -m src.pipeline classify --limit 100 --live   (writes to the DB)
    python -m src.pipeline evaluate                       (reads ai_predicted_category
                                                            vs. category, writes a report)

Phase 4 (deterministic business rules):
    python -m src.pipeline rules --limit 10               (dry run by default)
    python -m src.pipeline rules --limit 1500 --live       (writes to the DB)
    python -m src.pipeline rules-evaluate                  (reads decision_path/final_priority
                                                            back from the DB, reports what's
                                                            recoverable — see rules_metrics.py
                                                            for what isn't)

DRY_RUN behavior (both phases): dry-run mode does the real work — calls the
LLM (Phase 3) or runs the real rule engine (Phase 4), logs the result — but
never issues a database UPDATE. Going live requires BOTH the relevant
DRY_RUN flag set to false in config AND --live on the command line; either
alone keeps you in dry run. This double-confirmation is deliberate and is
preserved unchanged from Phase 3 into Phase 4, per the Phase 4 brief's
explicit instruction not to weaken it.

Cost tracking (Phase 3 only): token usage is recorded from the API's own
`usage` field on every call (never estimated). A dollar cost is only
reported if the operator supplies current per-token pricing via
INPUT_TOKEN_PRICE_PER_MILLION / OUTPUT_TOKEN_PRICE_PER_MILLION — this
project does not hard-code a price, since published pricing can change and
an outdated hard-coded figure would be a fabricated cost estimate.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .ai.classifier import TicketClassifier
from .ai.llm_client import AnthropicLLMClient, LLMAuthError
from .config import load_config
from .database.connection import get_connection
from .database.tickets import (
    count_classified,
    count_phase4_decided,
    fetch_evaluation_data,
    fetch_phase4_results,
    fetch_ticket_batch,
    fetch_tickets_for_rules,
    update_phase4_decision,
    update_ticket_classification,
)
from .evaluation.metrics import compute_metrics
from .evaluation.rules_metrics import compute_rules_evaluation, compute_rules_evaluation_from_db
from .logging_config import setup_logging
from .rules.engine import safe_evaluate
from .rules.models import TicketContext


def classify_batch(conn, classifier: TicketClassifier, tickets: list, dry_run: bool, logger) -> dict:
    """Core batch-classification loop, independent of CLI/config wiring so it
    can be unit-tested with a fake connection and a fake classifier."""
    total_input_tokens = 0
    total_output_tokens = 0
    n_success = 0
    n_failed = 0
    failures_by_type = {}

    for ticket in tickets:
        result = classifier.classify(ticket["ticket_id"], ticket["message_text"])

        if result.success:
            n_success += 1
            total_input_tokens += result.input_tokens or 0
            total_output_tokens += result.output_tokens or 0
            logger.info(
                f"Ticket {result.ticket_id} classified successfully",
                extra={
                    "event": "classification_success",
                    "ticket_id": result.ticket_id,
                    "success": True,
                    "predicted_category": result.validated.category,
                    "predicted_priority": result.validated.priority,
                    "latency_ms": round(result.latency_ms, 1) if result.latency_ms else None,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "dry_run": dry_run,
                },
            )
            if not dry_run:
                update_ticket_classification(
                    conn,
                    ticket_id=result.ticket_id,
                    category=result.validated.category,
                    confidence=result.validated.confidence,
                    sentiment_score=result.validated.sentiment_score,
                )
        else:
            n_failed += 1
            failures_by_type[result.error_type] = failures_by_type.get(result.error_type, 0) + 1
            logger.warning(
                f"Ticket {result.ticket_id} classification failed: {result.error_type}",
                extra={
                    "event": "classification_failure",
                    "ticket_id": result.ticket_id,
                    "success": False,
                    "error_type": result.error_type,
                    "latency_ms": round(result.latency_ms, 1) if result.latency_ms else None,
                    "dry_run": dry_run,
                },
            )
            # Deliberately no DB write here — a failed prediction must
            # never corrupt the original ticket.

    return {
        "dry_run": dry_run,
        "tickets_attempted": len(tickets),
        "n_success": n_success,
        "n_failed": n_failed,
        "failures_by_type": failures_by_type,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    }


def run_classify(config, logger, limit: int, live: bool):
    # Safety rule (deliberate, not accidental): going live requires BOTH the
    # --live CLI flag AND DRY_RUN=false in config. Either one alone keeps you
    # in dry run. This double-confirmation exists so a stale DRY_RUN=false
    # left in a shared .env can't silently cause a live run just because
    # someone forgot to also drop --live, and vice versa.
    dry_run = config.dry_run or not live
    logger.info(
        f"Starting classification run: limit={limit}, dry_run={dry_run}",
        extra={"event": "run_start", "dry_run": dry_run},
    )

    if not dry_run:
        problems = config.validate_for_live_run()
        if problems:
            for p in problems:
                logger.error(p, extra={"event": "config_error"})
            print("\nCannot run live: missing required configuration:")
            for p in problems:
                print(f"  - {p}")
            sys.exit(1)

    try:
        llm_client = AnthropicLLMClient(
            api_key=config.anthropic_api_key,
            model=config.model_name,
            max_tokens=config.llm_max_tokens,
            timeout_seconds=config.llm_timeout_seconds,
            max_retries=config.llm_max_retries,
        )
    except LLMAuthError as e:
        logger.error(f"Cannot start: {e}", extra={"event": "config_error"})
        print(f"\nCannot start classification run: {e}")
        print("Set ANTHROPIC_API_KEY in your .env file (see .env.example) and try again.")
        sys.exit(1)

    classifier = TicketClassifier(llm_client)

    with get_connection(config) as conn:
        tickets = fetch_ticket_batch(conn, limit=limit)
        logger.info(f"Fetched {len(tickets)} tickets to classify",
                    extra={"event": "batch_fetched"})
        summary = classify_batch(conn, classifier, tickets, dry_run, logger)

    input_price = os.getenv("INPUT_TOKEN_PRICE_PER_MILLION")
    output_price = os.getenv("OUTPUT_TOKEN_PRICE_PER_MILLION")
    if input_price and output_price and summary["n_success"] > 0:
        cost = (summary["total_input_tokens"] * float(input_price) +
                summary["total_output_tokens"] * float(output_price)) / 1_000_000
        summary["estimated_cost_usd"] = round(cost, 4)
    else:
        summary["estimated_cost_usd"] = None
        summary["cost_note"] = (
            "No per-token pricing configured (INPUT_TOKEN_PRICE_PER_MILLION / "
            "OUTPUT_TOKEN_PRICE_PER_MILLION) — reporting token counts only, "
            "not an invented dollar figure."
        )

    print(json.dumps(summary, indent=2))
    return summary


def run_evaluate(config, logger):
    with get_connection(config) as conn:
        n_classified = count_classified(conn)
        rows = fetch_evaluation_data(conn)

    if not rows:
        print("No classified tickets found (ai_predicted_category IS NOT NULL). "
              "Run `classify --live` on at least a few tickets first.")
        return None

    ground_truth = [r["ground_truth_category"] for r in rows]
    predicted = [r["ai_predicted_category"] for r in rows]

    report = compute_metrics(ground_truth, predicted)

    print(f"Evaluated {report.n_evaluated} tickets ({n_classified} total classified in DB)")
    print(f"Overall accuracy: {report.accuracy:.4f}")
    print(f"Macro F1:         {report.macro_f1:.4f}")
    print("\nPer-category:")
    for cat, m in report.per_category.items():
        print(f"  {cat:25s} precision={m['precision']:.3f} recall={m['recall']:.3f} "
              f"f1={m['f1']:.3f} support={m['support']}")

    return report


def rules_batch(conn, tickets: list, dry_run: bool, logger, config) -> dict:
    """Core Phase 4 batch loop, independent of CLI/config wiring so it can be
    unit-tested with a fake connection. Returns the summary dict AND the raw
    (Decision, TicketContext) pairs, so the caller can run the fuller
    in-memory evaluation (rule frequency, conflicts, fallbacks) that isn't
    recoverable from the database afterward."""
    decisions = []
    contexts_by_id = {}

    for row in tickets:
        decision = safe_evaluate(
            row,
            low_confidence_threshold=config.low_confidence_threshold,
            strong_negative_sentiment_threshold=config.strong_negative_sentiment_threshold,
            high_value_order_threshold=config.high_value_order_threshold,
        )
        decisions.append(decision)
        # Keep the context for evaluation breakdowns, when validation succeeded
        if not decision.is_fallback:
            contexts_by_id[decision.ticket_id] = TicketContext.model_validate(row)

        logger.info(
            f"Ticket {decision.ticket_id}: {decision.decision_path} / {decision.final_priority}",
            extra={
                "event": "rules_fallback" if decision.is_fallback else "rules_decision",
                "ticket_id": decision.ticket_id,
                "success": not decision.is_fallback,
                "final_priority": decision.final_priority,
                "decision_path": decision.decision_path,
                "triggered_rules": decision.triggered_rules,
                "conflicting_signals": decision.conflicting_signals,
                "is_fallback": decision.is_fallback,
                "dry_run": dry_run,
            },
        )

        if not dry_run:
            update_phase4_decision(
                conn, ticket_id=decision.ticket_id,
                final_priority=decision.final_priority,
                decision_path=decision.decision_path,
            )

    summary = {
        "dry_run": dry_run,
        "tickets_processed": len(decisions),
        "n_automated": sum(1 for d in decisions if d.decision_path == "Automated"),
        "n_human_review": sum(1 for d in decisions if d.decision_path == "Human Review"),
        "n_fallback": sum(1 for d in decisions if d.is_fallback),
    }
    return summary, decisions, contexts_by_id


def run_rules(config, logger, limit: int, live: bool):
    # Same double-confirmation safety rule as `classify` — preserved
    # deliberately, per the Phase 4 brief's explicit instruction not to
    # weaken it: going live requires BOTH RULES_DRY_RUN=false in config AND
    # --live on the command line.
    dry_run = config.rules_dry_run or not live
    logger.info(
        f"Starting rules run: limit={limit}, dry_run={dry_run}",
        extra={"event": "run_start", "dry_run": dry_run},
    )

    with get_connection(config) as conn:
        tickets = fetch_tickets_for_rules(conn, limit=limit)
        logger.info(f"Fetched {len(tickets)} tickets for rule evaluation",
                    extra={"event": "batch_fetched"})
        summary, decisions, contexts_by_id = rules_batch(conn, tickets, dry_run, logger, config)

    eval_report = compute_rules_evaluation(
        decisions, confidence_threshold=config.low_confidence_threshold,
        contexts_by_ticket_id=contexts_by_id,
    )
    summary["evaluation"] = {
        "metric_provenance": eval_report.metric_provenance,
        "automated_rate": eval_report.automated_rate,
        "human_review_rate": eval_report.human_review_rate,
        "urgent_human_review_rate": eval_report.urgent_human_review_rate,
        "priority_distribution": eval_report.priority_distribution,
        "rule_frequency": eval_report.rule_frequency,
        "multi_rule_frequency": eval_report.multi_rule_frequency,
        "conflict_frequency": eval_report.conflict_frequency,
        "fallback_frequency": eval_report.fallback_frequency,
    }

    print(json.dumps(summary, indent=2, default=str))
    return summary


def run_rules_evaluate(config, logger):
    with get_connection(config) as conn:
        n_decided = count_phase4_decided(conn)
        rows = fetch_phase4_results(conn)

    if not rows:
        print("No Phase 4 decisions found (decision_path IS NOT NULL). "
              "Run `rules --live` on at least a few tickets first.")
        return None

    report = compute_rules_evaluation_from_db(rows, confidence_threshold=config.low_confidence_threshold)

    print(f"[{report.metric_provenance}] Evaluated {report.n_processed} tickets "
          f"({n_decided} total decided in DB)")
    print(f"Automated rate:    {report.automated_rate:.4f}")
    print(f"Human review rate: {report.human_review_rate:.4f}")
    print(f"Urgent human-review rate: {report.urgent_human_review_rate:.4f}  "
          f"(share of ALL processed tickets that are both Human Review AND High/Urgent priority)")
    print(f"\nPriority distribution: {report.priority_distribution}")
    print(f"Decisions by category: {report.decisions_by_category}")
    print(f"Decisions by sentiment bucket: {report.decisions_by_sentiment_bucket}")
    print(f"Decisions by confidence bucket: {report.decisions_by_confidence_bucket}")
    for note in report.notes:
        print(f"\nNOTE: {note}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Meridian Commerce Phase 3/4 pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify_parser = subparsers.add_parser("classify", help="Classify a batch of tickets (Phase 3)")
    classify_parser.add_argument("--limit", type=int, default=None,
                                  help="Number of tickets to classify (default: BATCH_SIZE from config)")
    classify_parser.add_argument("--live", action="store_true",
                                  help="Actually write results to the database (default: dry run)")

    subparsers.add_parser("evaluate", help="Compute Phase 3 classification metrics")

    rules_parser = subparsers.add_parser("rules", help="Run the Phase 4 business-rule engine on a batch of tickets")
    rules_parser.add_argument("--limit", type=int, default=None,
                               help="Number of tickets to process (default: RULES_BATCH_SIZE from config)")
    rules_parser.add_argument("--live", action="store_true",
                               help="Actually write decisions to the database (default: dry run)")

    subparsers.add_parser("rules-evaluate", help="Compute Phase 4 decision metrics from the database")

    args = parser.parse_args()
    config = load_config()
    logger = setup_logging(config.log_dir, config.log_level)

    if args.command == "classify":
        limit = args.limit if args.limit is not None else config.batch_size
        run_classify(config, logger, limit=limit, live=args.live)
    elif args.command == "evaluate":
        run_evaluate(config, logger)
    elif args.command == "rules":
        limit = args.limit if args.limit is not None else config.rules_batch_size
        run_rules(config, logger, limit=limit, live=args.live)
    elif args.command == "rules-evaluate":
        run_rules_evaluate(config, logger)


if __name__ == "__main__":
    main()
