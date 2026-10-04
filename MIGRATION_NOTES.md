# Meridian Commerce: Anthropic → OpenRouter migration

## Apply (from the repository root)
1. Copy every file in this bundle over the repo, keeping the paths.
2. `python migrate_to_openrouter.py --check`  (preview: changes nothing)
3. `python migrate_to_openrouter.py`          (apply: pipeline.py, README, historical banners)
4. `pip install -r requirements.txt`  (a fresh venv is best: `pip uninstall anthropic` if it's still installed)
5. `cp .env.example .env`, then set `OPENROUTER_API_KEY=` (from https://openrouter.ai/keys) and `DB_PASSWORD=` **in `.env` only**
6. `pytest tests/ -v`
7. Dry runs (no DB writes): `python -m src.pipeline classify --limit 3` and `python -m src.pipeline respond --limit 3`

You can delete `migrate_to_openrouter.py` and this file once step 3 is done.

## Files
Replaced in full:
- `src/ai/llm_client.py`: OpenRouter client, used by Phases 3 and 5
- `src/config.py`
- `src/ai/prompts.py`: comment only
- `tests/conftest.py`: docstring only
- `tests/test_response_engine.py`: docstring only
- `requirements.txt`
- `.env.example`

New files:
- `tests/openrouter_fakes.py`
- `tests/test_openrouter_client.py`
- `tests/test_openrouter_integration.py`
- `tests/test_openrouter_pipeline_wiring.py`
- `migrate_to_openrouter.py`

Edited by the script:
- `src/pipeline.py`
- `README.md`
- `PHASE*_SUMMARY.md` and `reports/*.md`: banner only, the body stays unchanged

Unchanged (deliberately):
- the Phase 4 rules and thresholds
- the DB schema and SQL
- the safety scanner
- the eligibility logic
- the response models
- the metrics
- TicketClassifier
- ResponseGenerator

## Behavior notes
- `LLMClient.generate_structured()` now exists on the base class and on `OpenRouterLLMClient`. Before this change, live Phase 5 with a key crashed with an AttributeError, because only the test fake had that method.
- `validate_for_live_run()` used to read the removed `anthropic_api_key` field, which crashed every `--live` classify. It now checks `OPENROUTER_API_KEY` and a free `MODEL_NAME`.
- Paid models are refused: only `openrouter/free` or ids ending in `:free` are accepted, and anything else fails with `config_error`.
- Retries: `LLM_MAX_RETRIES` still means the total number of attempts. These are retried:
  - timeouts
  - 429
  - connection errors
  - 5xx
  - malformed tool calls

  Two cases fail fast so they don't burn the free daily quota:
  - auth errors (401)
  - other 4xx (400/402/404)
- The key is redacted from error messages and hidden from `repr(Config)`, and `DB_PASSWORD` is hidden too.
- `LLMResponse` gained an optional `model` field, recording which free model served each call.

## OpenRouter free-tier limitations
- About 20 requests/min and 50 requests/day. The daily cap goes up to 1000/day after a one-time purchase of $10 in credits, which this project does not need or use. Failed attempts count toward the quota.
- One ticket is one call per phase, so 1,500 tickets × 2 phases is about 60 days at 50/day. Run small `--limit` batches.
- `openrouter/free` picks a model per request. Output quality, and whether it honors the forced `tool_choice`, can vary. When it doesn't, the reply is treated as malformed and retried, and the ticket is marked failed or BLOCKED; a draft is never invented.
- Free endpoints may log or train on prompts. Only the existing allow-listed context is sent: no names, emails, phones, payment details or order values.
- Reasoning-style free models can use up `LLM_MAX_TOKENS` before emitting the tool call. If you see many `malformed_response` failures, raise it (e.g. 2048).
