"""
Pipeline wiring after the OpenRouter migration: `run_classify` (Phase 3) and
`run_respond` (Phase 5) must both build OpenRouterLLMClient from
OPENROUTER_API_KEY / MODEL_NAME, and user-facing messages must speak
OpenRouter. The database and the SDK are faked; nothing is written and no
network call is made.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import src.pipeline as pipeline
from src.ai.llm_client import OpenRouterLLMClient

from .openrouter_fakes import TEST_KEY, install_fake_openai


class RecordingLogger:
    def __init__(self):
        self.records = []

    def _rec(self, level, msg, *args, **kwargs):
        self.records.append((level, str(msg)))

    def info(self, msg, *a, **k): self._rec("info", msg)
    def warning(self, msg, *a, **k): self._rec("warning", msg)
    def error(self, msg, *a, **k): self._rec("error", msg)
    def debug(self, msg, *a, **k): self._rec("debug", msg)


def make_config(**overrides):
    base = dict(dry_run=True, response_dry_run=True, openrouter_api_key=TEST_KEY,
                model_name="openrouter/free", llm_max_tokens=256, llm_timeout_seconds=5.0,
                llm_max_retries=1, low_confidence_threshold=0.75,
                strong_negative_sentiment_threshold=-0.7, generate_internal_drafts=True)
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def no_db(monkeypatch):
    @contextmanager
    def fake_connection(config):
        yield None

    captured = {}

    def fake_response_batch(conn, tickets, dry_run, logger, config, generator):
        captured["generator"] = generator
        return {"dry_run": dry_run, "tickets_processed": 0}, []

    report = SimpleNamespace(
        metric_provenance="test", automated_response_eligible_rate=None,
        human_review_response_rate=None, blocked_response_rate=None, not_eligible_rate=None,
        response_status_distribution={}, response_type_distribution={},
        draft_generation_attempted=0, draft_generation_succeeded=0,
        draft_generation_success_rate=None, missing_context_rate=None, fallback_rate=None,
        notes=[])

    monkeypatch.setattr(pipeline, "get_connection", fake_connection)
    monkeypatch.setattr(pipeline, "fetch_tickets_for_response", lambda conn, limit: [])
    monkeypatch.setattr(pipeline, "response_batch", fake_response_batch)
    monkeypatch.setattr(pipeline, "compute_response_evaluation", lambda decisions: report)
    return captured


def test_phase5_run_respond_uses_openrouter_client(monkeypatch, no_db):
    latest = install_fake_openai(monkeypatch, [])
    pipeline.run_respond(make_config(), RecordingLogger(), limit=1, live=False)

    generator = no_db["generator"]
    assert generator is not None
    assert isinstance(generator._llm_client, OpenRouterLLMClient)
    assert latest().init_kwargs["base_url"] == "https://openrouter.ai/api/v1"


def test_phase5_without_key_warns_in_openrouter_terms(monkeypatch, no_db):
    install_fake_openai(monkeypatch, [])
    logger = RecordingLogger()
    pipeline.run_respond(make_config(openrouter_api_key=""), logger, limit=1, live=False)

    warnings = " ".join(m for lvl, m in logger.records if lvl == "warning")
    assert "OPENROUTER_API_KEY" in warnings
    assert "ANTHROPIC" not in warnings
    assert no_db["generator"] is None


def test_phase5_paid_model_is_refused_not_used(monkeypatch, no_db):
    install_fake_openai(monkeypatch, [])
    logger = RecordingLogger()
    pipeline.run_respond(make_config(model_name="openai/gpt-4o"), logger, limit=1, live=False)
    assert no_db["generator"] is None
    assert any(lvl == "error" for lvl, _ in logger.records)


def test_phase3_run_classify_without_key_exits_with_openrouter_message(monkeypatch, capsys):
    install_fake_openai(monkeypatch, [])
    with pytest.raises(SystemExit):
        pipeline.run_classify(make_config(openrouter_api_key=""), RecordingLogger(),
                              limit=1, live=False)
    out = capsys.readouterr().out
    assert "OPENROUTER_API_KEY" in out
    assert "ANTHROPIC" not in out
