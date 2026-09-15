"""
Meridian Commerce — Phase 3: Logging configuration

Structured (JSON-lines) logging for the classification pipeline, written to
both console and a log file. Deliberately excludes PII: we log ticket_id,
category/priority predictions, timing, and error types — never customer
email, phone, or raw message text.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # Any extra structured fields passed via logger.info(..., extra={...})
        for key in ("ticket_id", "event", "success", "predicted_category",
                    "predicted_priority", "latency_ms", "error_type",
                    "input_tokens", "output_tokens", "dry_run",
                    "final_priority", "decision_path", "triggered_rules",
                    "conflicting_signals", "is_fallback"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload)


def setup_logging(log_dir: str, log_level: str = "INFO") -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("meridian.classifier")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers.clear()  # avoid duplicate handlers on repeated setup calls

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)

    file_path = os.path.join(log_dir, "classification.jsonl")
    file_handler = logging.FileHandler(file_path)
    file_handler.setFormatter(JsonLineFormatter())
    logger.addHandler(file_handler)

    return logger
