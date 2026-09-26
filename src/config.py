"""
Meridian Commerce — Phase 3: Configuration

Loads all settings from environment variables (via a local .env file, never
committed — see .gitignore). No credentials or connection details are
hard-coded anywhere in this project.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root if present. In production/CI, real
# environment variables take precedence and .env is typically absent.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


# ----------------------------------------------------------------------------
# Approved controlled vocabularies (Phase 1 — must match sql/01_schema.sql
# CHECK constraints exactly). Centralized here so every module (prompts,
# validation, evaluation) references the same single source of truth.
# ----------------------------------------------------------------------------
APPROVED_CATEGORIES = [
    "Refund Request", "Missing Item", "Damaged Product", "Delivery Delay",
    "Order Status Inquiry", "Product Question", "Payment Problem",
    "Account Problem", "Complaint", "Other",
]

APPROVED_PRIORITIES = ["Low", "Medium", "High", "Urgent"]

# Ordinal ranking so "take the most severe triggered rule" is a well-defined
# max() rather than an ambiguous set of relative bumps.
PRIORITY_ORDER = {"Low": 0, "Medium": 1, "High": 2, "Urgent": 3}

# Base category -> priority mapping. This is the SAME mapping Phase 2 used
# to generate the historical (ground-truth) tickets.priority values — reused
# here deliberately for consistency, but note the purpose is different:
# Phase 2 used it to fabricate plausible historical data; Phase 4 uses it as
# the deterministic starting point for a live operational decision.
CATEGORY_BASE_PRIORITY = {
    "Order Status Inquiry": "Low", "Product Question": "Low", "Other": "Low",
    "Delivery Delay": "Medium", "Refund Request": "Medium", "Account Problem": "Medium",
    "Damaged Product": "High", "Missing Item": "High", "Payment Problem": "High",
    "Complaint": "Urgent",
}

# Categories inherently order-specific — used by the rule engine to detect
# "category implies an order, but no order is linked" as a conflicting/
# incomplete-information signal.
ORDER_DEPENDENT_CATEGORIES = ["Refund Request", "Missing Item", "Damaged Product", "Delivery Delay"]

# Categories judged too consequential (financial, security, or relationship
# risk) to fully automate at this stage of the project, regardless of
# classification confidence. This is a deliberate, conservative starting
# list — see PHASE4_SUMMARY.md for the reasoning per category.
SENSITIVE_CATEGORIES = ["Payment Problem", "Account Problem", "Complaint"]


@dataclass
class Config:
    # --- Database ---
    db_host: str = field(default_factory=lambda: os.getenv("DB_HOST", "localhost"))
    db_port: str = field(default_factory=lambda: os.getenv("DB_PORT", "5432"))
    db_name: str = field(default_factory=lambda: os.getenv("DB_NAME", "meridian_commerce"))
    db_user: str = field(default_factory=lambda: os.getenv("DB_USER", "meridian_app"))
    db_password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", ""))

    # --- LLM provider ---
    openrouter_api_key: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "")
    )
    model_name: str = field(
    default_factory=lambda: os.getenv("MODEL_NAME", "openrouter/free")
)
    llm_max_tokens: int = field(default_factory=lambda: _get_int("LLM_MAX_TOKENS", 1024))
    llm_timeout_seconds: float = field(default_factory=lambda: _get_float("LLM_TIMEOUT_SECONDS", 30.0))
    llm_max_retries: int = field(default_factory=lambda: _get_int("LLM_MAX_RETRIES", 3))

    # --- Pipeline behavior ---
    dry_run: bool = field(default_factory=lambda: _get_bool("DRY_RUN", True))
    batch_size: int = field(default_factory=lambda: _get_int("BATCH_SIZE", 10))

    # --- Logging ---
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_dir: str = field(default_factory=lambda: os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs")))

    # --- Phase 4: rule engine thresholds ---
    # IMPORTANT — these are BUSINESS-RULE ASSUMPTIONS / INITIAL THRESHOLDS,
    # not calibrated values. Two different kinds of "grounded" are mixed
    # together in this codebase and should not be confused:
    #   - HIGH_VALUE_ORDER_THRESHOLD is grounded in REAL Phase 2 order data
    #     (an actual percentile), so it reflects this business's real order
    #     value distribution — but it's still a business judgment call
    #     about what counts as "high value," not something calibrated
    #     against outcomes.
    #   - LOW_CONFIDENCE_THRESHOLD and STRONG_NEGATIVE_SENTIMENT_THRESHOLD
    #     have NO empirical grounding at all yet, because Phase 3 has never
    #     produced a real classification in this environment — there is no
    #     confidence-vs-actual-accuracy or sentiment-vs-actual-outcome data
    #     to calibrate against. They are conservative starting assumptions.
    # Calibration path: once Phase 3 runs against real tickets and produces
    # ai_predicted_category/classification_confidence/sentiment_score at
    # scale, these thresholds should be revisited against the real
    # precision/recall each one implies (e.g., "what confidence cutoff
    # actually separates correct from incorrect classifications?") rather
    # than left at these initial values indefinitely. All three remain
    # overridable via environment variable in the meantime.
    high_value_order_threshold: float = field(
        default_factory=lambda: _get_float("HIGH_VALUE_ORDER_THRESHOLD", 450.0))
    low_confidence_threshold: float = field(
        default_factory=lambda: _get_float("LOW_CONFIDENCE_THRESHOLD", 0.75))
    strong_negative_sentiment_threshold: float = field(
        default_factory=lambda: _get_float("STRONG_NEGATIVE_SENTIMENT_THRESHOLD", -0.7))
    rules_dry_run: bool = field(default_factory=lambda: _get_bool("RULES_DRY_RUN", True))
    rules_batch_size: int = field(default_factory=lambda: _get_int("RULES_BATCH_SIZE", 10))

    # --- Phase 5: response decision layer ---
    # Same double-confirmation safety model as Phases 3 and 4: going live
    # requires RESPONSE_DRY_RUN=false AND --live together.
    response_dry_run: bool = field(default_factory=lambda: _get_bool("RESPONSE_DRY_RUN", True))
    response_batch_size: int = field(default_factory=lambda: _get_int("RESPONSE_BATCH_SIZE", 10))
    # Whether to produce internal-only drafts for human-review tickets.
    # Off by default would waste the agent-assist value; on by default costs
    # LLM calls on tickets a human handles anyway — configurable either way.
    generate_internal_drafts: bool = field(
        default_factory=lambda: _get_bool("GENERATE_INTERNAL_DRAFTS", True))

    def validate_for_live_run(self) -> list:
        """Returns a list of problems that would prevent a real (non-dry-run)
        LLM call. Called explicitly before any live API usage — never
        silently proceeds with missing credentials."""
        problems = []
        if not self.anthropic_api_key:
            problems.append(
                "ANTHROPIC_API_KEY is not set. Set it in a local .env file "
                "(see .env.example) or as a real environment variable."
            )
        if not self.db_password:
            problems.append("DB_PASSWORD is not set.")
        return problems


def load_config() -> Config:
    return Config()
