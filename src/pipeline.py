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

Phase 5 (response decision & draft layer):
    python -m src.pipeline respond --limit 10              (dry run by default)
    python -m src.pipeline respond --limit 1500 --live      (writes to the DB)
    python -m src.pipeline respond-evaluate                 (reads response_status/response_type
                                                             back from the DB)

DRY_RUN behavior (all three phases): dry-run mode does the real work — calls
the LLM (Phases 3/5) or runs the real rule engine (Phase 4), logs the result —
but never issues a database UPDATE. Going live requires BOTH the relevant
DRY_RUN flag set to false in config AND --live on the command line; either
alone keeps you in dry run. This double-confirmation is deliberate and is
preserved unchanged across Phases 3, 4, and 5.

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
from .ai.llm_client import OpenRouterLLMClient, LLMAuthError
from .config import load_config
from .database.connection import get_connection
from .database.tickets import (
    count_classified,
    count_phase4_decided,
    count_phase5_processed,
    fetch_evaluation_data,
    fetch_phase4_results,
    fetch_phase5_results,
    fetch_ticket_batch,
    fetch_tickets_for_response,
    fetch_tickets_for_rules,
    update_phase4_decision,
    update_phase5_response,
    update_ticket_classification,
)
from .evaluation.metrics import compute_metrics
from .evaluation.analytics import fetch_analytics, summarize_analytics, validate_analytics
from .evaluation.response_metrics import (
    compute_response_evaluation,
    compute_response_evaluation_from_db,
)
from .evaluation.rules_metrics import compute_rules_evaluation, compute_rules_evaluation_from_db
from .logging_config import setup_logging
from .response.engine import safe_decide_response
from .response.generator import ResponseGenerator
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
    llm_client = OpenRouterLLMClient(
        api_key=config.openrouter_api_key,
        model=config.model_name,
        max_tokens=config.llm_max_tokens,
        timeout_seconds=config.llm_timeout_seconds,
        max_retries=config.llm_max_retries,
    )
    except LLMAuthError as e:
        logger.error(f"Cannot start: {e}", extra={"event": "config_error"})
        print(f"\nCannot start classification run: {e}")
        print("Set OPENROUTER_API_KEY in your .env file (see .env.example) and try again.")
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


def response_batch(conn, tickets: list, dry_run: bool, logger, config,
                    generator) -> tuple:
    """Core Phase 5 batch loop, independent of CLI/config wiring so it can be
    unit-tested with a fake connection and a FakeLLMClient. `generator` may
    be None to run the decision layer with no LLM calls at all."""
    decisions = []

    for row in tickets:
        decision = safe_decide_response(
            row,
            generator=generator,
            low_confidence_threshold=config.low_confidence_threshold,
            strong_negative_sentiment_threshold=config.strong_negative_sentiment_threshold,
            generate_internal_drafts=config.generate_internal_drafts,
        )
        decisions.append(decision)

        logger.info(
            f"Ticket {decision.ticket_id}: {decision.response_status}"
            f"{' (customer-facing)' if decision.customer_facing else ''}",
            extra={
                "event": "response_fallback" if decision.is_fallback else "response_decision",
                "ticket_id": decision.ticket_id,
                "success": not decision.is_fallback,
                "response_status": decision.response_status,
                "response_type": decision.response_type,
                "customer_facing": decision.customer_facing,
                "requires_human_review": decision.requires_human_review,
                "has_draft": decision.response_draft is not None,
                "dry_run": dry_run,
            },
        )
        # Draft TEXT is deliberately never logged — it can contain the
        # customer's own words echoed back, and the log is not the place for
        # message content. Only whether a draft exists is recorded.

        if not dry_run:
            update_phase5_response(
                conn, ticket_id=decision.ticket_id,
                response_status=decision.response_status,
                response_type=decision.response_type,
                response_draft=decision.response_draft,
            )

    summary = {
        "dry_run": dry_run,
        "tickets_processed": len(decisions),
        "n_draft_generated": sum(1 for d in decisions if d.response_status == "DRAFT_GENERATED"),
        "n_human_review_draft": sum(1 for d in decisions if d.response_status == "HUMAN_REVIEW_DRAFT"),
        "n_blocked": sum(1 for d in decisions if d.response_status == "BLOCKED"),
        "n_not_eligible": sum(1 for d in decisions if d.response_status == "NOT_ELIGIBLE"),
        "n_fallback": sum(1 for d in decisions if d.is_fallback),
    }
    return summary, decisions


def run_respond(config, logger, limit: int, live: bool):
    # Same double-confirmation safety rule as Phases 3 and 4, preserved
    # unchanged: going live requires BOTH RESPONSE_DRY_RUN=false in config
    # AND --live on the command line.
    dry_run = config.response_dry_run or not live
    logger.info(
        f"Starting response run: limit={limit}, dry_run={dry_run}",
        extra={"event": "run_start", "dry_run": dry_run},
    )

    # The response layer degrades honestly without credentials: it still
    # makes real eligibility/routing decisions, but produces no drafts and
    # says so, rather than failing outright or pretending drafts exist.
    generator = None
    if config.openrouter_api_key:
        try:
            llm_client = OpenRouterLLMClient(
    api_key=config.openrouter_api_key,
    model=config.model_name,
    max_tokens=config.llm_max_tokens,
    timeout_seconds=config.llm_timeout_seconds,
    max_retries=config.llm_max_retries,
)
            generator = ResponseGenerator(llm_client)
        except LLMAuthError as e:
            logger.error(f"LLM client unavailable: {e}", extra={"event": "config_error"})
    else:
        logger.warning(
            "No ANTHROPIC_API_KEY configured — running the response layer in "
            "decision-only mode (eligibility and routing are real; no drafts will be generated).",
            extra={"event": "config_warning"},
        )

    with get_connection(config) as conn:
        tickets = fetch_tickets_for_response(conn, limit=limit)
        logger.info(f"Fetched {len(tickets)} tickets for response decisioning",
                    extra={"event": "batch_fetched"})
        summary, decisions = response_batch(conn, tickets, dry_run, logger, config, generator)

    eval_report = compute_response_evaluation(decisions)
    summary["generator_available"] = generator is not None
    summary["evaluation"] = {
        "metric_provenance": eval_report.metric_provenance,
        "automated_response_eligible_rate": eval_report.automated_response_eligible_rate,
        "human_review_response_rate": eval_report.human_review_response_rate,
        "blocked_response_rate": eval_report.blocked_response_rate,
        "not_eligible_rate": eval_report.not_eligible_rate,
        "response_status_distribution": eval_report.response_status_distribution,
        "response_type_distribution": eval_report.response_type_distribution,
        "draft_generation_attempted": eval_report.draft_generation_attempted,
        "draft_generation_succeeded": eval_report.draft_generation_succeeded,
        "draft_generation_success_rate": eval_report.draft_generation_success_rate,
        "missing_context_rate": eval_report.missing_context_rate,
        "fallback_rate": eval_report.fallback_rate,
        "notes": eval_report.notes,
    }

    print(json.dumps(summary, indent=2, default=str))
    return summary


def run_respond_evaluate(config, logger):
    with get_connection(config) as conn:
        n_processed = count_phase5_processed(conn)
        rows = fetch_phase5_results(conn)

    if not rows:
        print("No Phase 5 response decisions found (response_status IS NOT NULL). "
              "Run `respond --live` on at least a few tickets first.")
        return None

    report = compute_response_evaluation_from_db(rows)

    print(f"[{report.metric_provenance}] Evaluated {report.n_processed} tickets "
          f"({n_processed} total processed in DB)")
    print(f"Automated response eligible rate: {report.automated_response_eligible_rate:.4f}  "
          f"(share of ALL processed with an approved customer-facing draft)")
    print(f"Human-review response rate:       {report.human_review_response_rate:.4f}")
    print(f"Blocked response rate:            {report.blocked_response_rate:.4f}")
    print(f"Not-eligible rate:                {report.not_eligible_rate:.4f}")
    print(f"\nResponse status distribution: {report.response_status_distribution}")
    print(f"Response type distribution:   {report.response_type_distribution}")
    if report.draft_generation_success_rate is not None:
        print(f"Draft generation success rate: {report.draft_generation_success_rate:.4f} "
              f"({report.draft_generation_succeeded}/{report.draft_generation_attempted} attempted)")
    for note in report.notes:
        print(f"\nNOTE: {note}")

    return report


def run_analytics(config, logger):
    """Phase 6: READ-ONLY. Reads the analytical views, independently validates
    what can be cross-checked, and prints a summary. Issues no writes of any
    kind — there is deliberately no --live flag on this command, because
    there is nothing for it to mutate."""
    logger.info("Starting analytics validation (read-only)", extra={"event": "run_start"})

    with get_connection(config) as conn:
        snapshot = fetch_analytics(conn)

    issues = validate_analytics(snapshot)
    summary = summarize_analytics(snapshot, issues)

    print(json.dumps(summary, indent=2, default=str))

    if issues:
        logger.warning(f"Analytics validation found {len(issues)} issue(s)",
                        extra={"event": "analytics_issues"})
        for issue in issues:
            logger.warning(f"[{issue.severity}] {issue.check}: {issue.detail}",
                            extra={"event": "analytics_issue"})
    else:
        logger.info("Analytics validation passed — no inconsistencies found",
                     extra={"event": "analytics_ok"})

    return summary


def main():
    parser = argparse.ArgumentParser(description="Meridian Commerce Phase 3/4/5 pipeline")
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

    respond_parser = subparsers.add_parser("respond", help="Run the Phase 5 response-decision layer on a batch of tickets")
    respond_parser.add_argument("--limit", type=int, default=None,
                                 help="Number of tickets to process (default: RESPONSE_BATCH_SIZE from config)")
    respond_parser.add_argument("--live", action="store_true",
                                 help="Actually write response decisions to the database (default: dry run)")

    subparsers.add_parser("respond-evaluate", help="Compute Phase 5 response metrics from the database")

    subparsers.add_parser("analytics", help="Phase 6: read-only analytics validation and summary")

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
    elif args.command == "respond":
        limit = args.limit if args.limit is not None else config.response_batch_size
        run_respond(config, logger, limit=limit, live=args.live)
    elif args.command == "respond-evaluate":
        run_respond_evaluate(config, logger)
    elif args.command == "analytics":
        run_analytics(config, logger)


if __name__ == "__main__":
    main()
