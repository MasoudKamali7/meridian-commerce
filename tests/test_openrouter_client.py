"""
Unit tests for OpenRouterLLMClient and the OpenRouter configuration.

Fully offline: the OpenAI SDK class is replaced with FakeOpenAI (see
openrouter_fakes.py) and no real OPENROUTER_API_KEY is ever needed.
"""

from pathlib import Path

import pytest

from src.ai.llm_client import (
    DEFAULT_FREE_MODEL,
    OPENROUTER_BASE_URL,
    LLMAPIError,
    LLMAuthError,
    LLMClient,
    LLMConfigError,
    LLMMalformedResponseError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    OpenRouterLLMClient,
    is_free_openrouter_model,
)

from .openrouter_fakes import (
    TEST_KEY,
    auth_error,
    bad_request_error,
    connection_error,
    install_fake_openai,
    payment_required_error,
    rate_limit_error,
    server_error,
    text_only_response,
    timeout_error,
    tool_call_response,
)

TOOL = {
    "name": "demo_tool",
    "description": "demo",
    "input_schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    },
}


def make_client(**overrides):
    kwargs = dict(api_key=TEST_KEY, model=DEFAULT_FREE_MODEL, max_tokens=256,
                  timeout_seconds=12.5, max_retries=3)
    kwargs.update(overrides)
    return OpenRouterLLMClient(**kwargs)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
def test_client_initializes_openai_sdk_against_openrouter(monkeypatch):
    latest = install_fake_openai(monkeypatch, [])
    make_client()
    sdk = latest()
    assert OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"
    assert sdk.init_kwargs["base_url"] == OPENROUTER_BASE_URL
    assert sdk.init_kwargs["api_key"] == TEST_KEY
    assert sdk.init_kwargs["timeout"] == 12.5
    assert sdk.init_kwargs["max_retries"] == 0      # retries owned by our loop


def test_default_model_is_openrouter_free(monkeypatch):
    install_fake_openai(monkeypatch, [tool_call_response("demo_tool", {"answer": "x"})])
    client = OpenRouterLLMClient(api_key=TEST_KEY)
    client.classify("sys", "user", TOOL)
    assert DEFAULT_FREE_MODEL == "openrouter/free"
    assert client._model == "openrouter/free"


@pytest.mark.parametrize("bad_key", ["", None, "   "])
def test_missing_openrouter_api_key_raises_auth_error(monkeypatch, bad_key):
    latest = install_fake_openai(monkeypatch, [])
    with pytest.raises(LLMAuthError) as exc:
        make_client(api_key=bad_key)
    assert "OPENROUTER_API_KEY" in str(exc.value)
    assert exc.value.error_type == "auth_error"


@pytest.mark.parametrize("paid_model", ["openai/gpt-4o", "some-vendor/some-model", ""])
def test_non_free_model_is_refused(monkeypatch, paid_model):
    install_fake_openai(monkeypatch, [])
    with pytest.raises(LLMConfigError) as exc:
        make_client(model=paid_model)
    assert exc.value.error_type == "config_error"
    assert "free" in str(exc.value)


def test_explicit_free_variant_is_accepted(monkeypatch):
    install_fake_openai(monkeypatch, [])
    make_client(model="meta-llama/llama-3.3-70b-instruct:free")


def test_free_model_helper():
    assert is_free_openrouter_model("openrouter/free")
    assert is_free_openrouter_model("vendor/model:free")
    assert not is_free_openrouter_model("vendor/model")
    assert not is_free_openrouter_model(None)
    assert not is_free_openrouter_model("  ")


# ---------------------------------------------------------------------------
# Valid structured tool response
# ---------------------------------------------------------------------------
def test_valid_tool_response_is_parsed_with_usage_and_latency(monkeypatch):
    latest = install_fake_openai(monkeypatch, [
        tool_call_response("demo_tool", {"answer": "42"}, prompt_tokens=111,
                           completion_tokens=22, model="vendor/m:free")])
    client = make_client()
    result = client.classify("system text", "user text", TOOL)

    assert isinstance(result, LLMResponse)
    assert result.tool_input == {"answer": "42"}
    assert result.input_tokens == 111
    assert result.output_tokens == 22
    assert result.latency_ms >= 0
    assert result.raw_stop_reason == "tool_calls"
    assert result.model == "vendor/m:free"


def test_request_forces_the_named_function_tool(monkeypatch):
    latest = install_fake_openai(monkeypatch, [tool_call_response("demo_tool", {"answer": "a"})])
    client = make_client()
    client.classify("system text", "user text", TOOL)
    call = latest().calls[0]

    assert call["model"] == "openrouter/free"
    assert call["max_tokens"] == 256
    assert call["messages"] == [{"role": "system", "content": "system text"},
                                {"role": "user", "content": "user text"}]
    assert call["tools"] == [{"type": "function", "function": {
        "name": "demo_tool", "description": "demo", "parameters": TOOL["input_schema"]}}]
    assert call["tool_choice"] == {"type": "function", "function": {"name": "demo_tool"}}


def test_missing_usage_reports_zero_tokens_not_invented_numbers(monkeypatch):
    resp = tool_call_response("demo_tool", {"answer": "a"})
    resp.usage = None
    install_fake_openai(monkeypatch, [resp])
    result = make_client().classify("s", "u", TOOL)
    assert result.input_tokens == 0 and result.output_tokens == 0


def test_generate_structured_uses_the_same_forced_tool_path(monkeypatch):
    latest = install_fake_openai(monkeypatch, [tool_call_response("demo_tool", {"answer": "b"})])
    result = make_client().generate_structured("s", "u", TOOL)
    assert result.tool_input == {"answer": "b"}
    assert latest().calls[0]["tool_choice"]["function"]["name"] == "demo_tool"


def test_base_interface_generate_structured_delegates_to_classify():
    class Minimal(LLMClient):
        def __init__(self):
            self.seen = None

        def classify(self, system_prompt, user_prompt, tool_schema):
            self.seen = (system_prompt, user_prompt, tool_schema["name"])
            return LLMResponse({"ok": True}, 1, 1, 1.0, "tool_use")

    c = Minimal()
    assert c.generate_structured("s", "u", TOOL).tool_input == {"ok": True}
    assert c.seen == ("s", "u", "demo_tool")


# ---------------------------------------------------------------------------
# Malformed tool responses (retried, then surfaced as malformed_response)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_response", [
    "no_choices", "text_only", "wrong_tool", "empty_args", "invalid_json", "json_list",
])
def test_malformed_tool_response_raises_after_retries(monkeypatch, bad_response):
    def build():
        if bad_response == "no_choices":
            r = tool_call_response("demo_tool", {"answer": "a"})
            r.choices = []
            return r
        if bad_response == "text_only":
            return text_only_response()
        if bad_response == "wrong_tool":
            return tool_call_response("other_tool", {"answer": "a"})
        if bad_response == "empty_args":
            return tool_call_response("demo_tool", "")
        if bad_response == "invalid_json":
            return tool_call_response("demo_tool", "{not json")
        return tool_call_response("demo_tool", "[1, 2, 3]")

    latest = install_fake_openai(monkeypatch, [build(), build(), build()])
    client = make_client(max_retries=3)
    with pytest.raises(LLMMalformedResponseError) as exc:
        client.classify("s", "u", TOOL)
    assert exc.value.error_type == "malformed_response"
    assert len(latest().calls) == 3


def test_malformed_then_valid_recovers_on_retry(monkeypatch):
    latest = install_fake_openai(monkeypatch, [
        text_only_response(), tool_call_response("demo_tool", {"answer": "ok"})])
    result = make_client().classify("s", "u", TOOL)
    assert result.tool_input == {"answer": "ok"}
    assert len(latest().calls) == 2


# ---------------------------------------------------------------------------
# Error mapping and retry policy
# ---------------------------------------------------------------------------
def test_authentication_error_is_not_retried_and_key_is_redacted(monkeypatch):
    latest = install_fake_openai(monkeypatch, [auth_error(f"bad key {TEST_KEY}")])
    with pytest.raises(LLMAuthError) as exc:
        make_client().classify("s", "u", TOOL)
    assert exc.value.error_type == "auth_error"
    assert len(latest().calls) == 1
    assert TEST_KEY not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)


def test_timeout_is_retried_then_raised(monkeypatch):
    latest = install_fake_openai(monkeypatch, [timeout_error(), timeout_error(), timeout_error()])
    with pytest.raises(LLMTimeoutError) as exc:
        make_client(max_retries=3).classify("s", "u", TOOL)
    assert exc.value.error_type == "timeout"
    assert len(latest().calls) == 3


def test_rate_limit_is_retried_then_raised(monkeypatch):
    latest = install_fake_openai(monkeypatch, [rate_limit_error(), rate_limit_error()])
    with pytest.raises(LLMRateLimitError) as exc:
        make_client(max_retries=2).classify("s", "u", TOOL)
    assert exc.value.error_type == "rate_limit"
    assert len(latest().calls) == 2


def test_rate_limit_then_success_recovers(monkeypatch):
    install_fake_openai(monkeypatch, [rate_limit_error(),
                                      tool_call_response("demo_tool", {"answer": "ok"})])
    assert make_client().classify("s", "u", TOOL).tool_input == {"answer": "ok"}


def test_server_error_is_retried_as_api_error(monkeypatch):
    latest = install_fake_openai(monkeypatch, [server_error(), server_error(), server_error()])
    with pytest.raises(LLMAPIError) as exc:
        make_client(max_retries=3).classify("s", "u", TOOL)
    assert exc.value.error_type == "api_error"
    assert "status=500" in str(exc.value)
    assert len(latest().calls) == 3


def test_connection_error_is_api_error(monkeypatch):
    install_fake_openai(monkeypatch, [connection_error()])
    with pytest.raises(LLMAPIError):
        make_client(max_retries=1).classify("s", "u", TOOL)


def test_bad_request_fails_fast_without_burning_quota(monkeypatch):
    latest = install_fake_openai(monkeypatch, [bad_request_error()])
    with pytest.raises(LLMAPIError) as exc:
        make_client(max_retries=3).classify("s", "u", TOOL)
    assert "status=400" in str(exc.value)
    assert len(latest().calls) == 1


def test_payment_required_points_back_to_free_routing(monkeypatch):
    latest = install_fake_openai(monkeypatch, [payment_required_error()])
    with pytest.raises(LLMAPIError) as exc:
        make_client().classify("s", "u", TOOL)
    assert "free routing" in str(exc.value)
    assert len(latest().calls) == 1


def test_retry_count_honors_llm_max_retries(monkeypatch):
    latest = install_fake_openai(monkeypatch, [timeout_error()] * 5)
    with pytest.raises(LLMTimeoutError):
        make_client(max_retries=5).classify("s", "u", TOOL)
    assert len(latest().calls) == 5


def test_bad_tool_schema_is_rejected_before_any_call(monkeypatch):
    latest = install_fake_openai(monkeypatch, [])
    with pytest.raises(LLMMalformedResponseError):
        make_client().classify("s", "u", {"name": "x"})
    assert latest().calls == []


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _config(monkeypatch, **env):
    for name in ("OPENROUTER_API_KEY", "MODEL_NAME", "DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    from src.config import Config
    return Config()


def test_config_defaults_to_openrouter_free(monkeypatch):
    cfg = _config(monkeypatch)
    assert cfg.model_name == "openrouter/free"
    assert cfg.openrouter_api_key == ""
    assert not hasattr(cfg, "anthropic" + "_api_key")


def test_config_keeps_llm_tuning_settings(monkeypatch):
    cfg = _config(monkeypatch, LLM_MAX_TOKENS="512", LLM_TIMEOUT_SECONDS="9.5",
                  LLM_MAX_RETRIES="4")
    assert (cfg.llm_max_tokens, cfg.llm_timeout_seconds, cfg.llm_max_retries) == (512, 9.5, 4)


def test_validate_for_live_run_requires_openrouter_key(monkeypatch):
    cfg = _config(monkeypatch, DB_PASSWORD="pw")
    problems = cfg.validate_for_live_run()
    assert len(problems) == 1
    assert "OPENROUTER_API_KEY" in problems[0]
    assert "ANTHROPIC" not in " ".join(problems)


def test_validate_for_live_run_rejects_paid_model(monkeypatch):
    cfg = _config(monkeypatch, OPENROUTER_API_KEY=TEST_KEY, DB_PASSWORD="pw",
                  MODEL_NAME="openai/gpt-4o")
    problems = cfg.validate_for_live_run()
    assert any("MODEL_NAME" in p and "free" in p for p in problems)


def test_validate_for_live_run_passes_when_configured(monkeypatch):
    cfg = _config(monkeypatch, OPENROUTER_API_KEY=TEST_KEY, DB_PASSWORD="pw")
    assert cfg.validate_for_live_run() == []


def test_config_repr_never_contains_the_key(monkeypatch):
    cfg = _config(monkeypatch, OPENROUTER_API_KEY=TEST_KEY, DB_PASSWORD="pw-secret")
    text = repr(cfg)
    assert TEST_KEY not in text
    assert "pw-secret" not in text


def test_config_and_client_agree_on_free_models():
    from src.config import is_free_openrouter_model as cfg_is_free
    for m in ["openrouter/free", "a/b:free", "a/b", "", None]:
        assert cfg_is_free(m) == is_free_openrouter_model(m)


# ---------------------------------------------------------------------------
# Repository hygiene
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
_BANNED = ["Anthropic" + "LLMClient", "anthropic" + "_api_key", "ANTHROPIC" + "_API_KEY",
           "import " + "anthropic", "from " + "anthropic", "claude" + "-"]


def test_no_active_anthropic_references_in_source():
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.relative_to(ROOT)}: {b}" for b in _BANNED if b in text]
        if "anthropic" in text.lower():
            offenders.append(f"{path.relative_to(ROOT)}: mentions the old provider")
    assert offenders == []


def test_requirements_pin_openai_and_drop_the_old_sdk():
    lines = [l.strip() for l in (ROOT / "requirements.txt").read_text().splitlines()
             if l.strip() and not l.strip().startswith("#")]
    assert any(l.startswith("openai==") for l in lines)
    assert not any(l.lower().startswith("anthropic") for l in lines)


def test_env_example_has_empty_openrouter_key_placeholder():
    lines = (ROOT / ".env.example").read_text().splitlines()
    assert "OPENROUTER_API_KEY=" in lines
    assert "MODEL_NAME=openrouter/free" in lines
    assert not any("ANTHROPIC" in l for l in lines)


def test_no_real_looking_openrouter_key_committed():
    suspicious = []
    for path in list((ROOT / "src").rglob("*.py")) + [ROOT / ".env.example",
                                                      ROOT / "requirements.txt"]:
        if ("sk-" + "or-") in path.read_text(encoding="utf-8"):
            suspicious.append(str(path.relative_to(ROOT)))
    assert suspicious == []
