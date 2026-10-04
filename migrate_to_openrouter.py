#!/usr/bin/env python3
"""
One-shot, idempotent finisher for the Anthropic -> OpenRouter migration.

Run once from the repository root AFTER copying the updated files in:

    python migrate_to_openrouter.py            # apply
    python migrate_to_openrouter.py --check    # report only, change nothing

What it does (only text edits, no network, never reads or prints .env):
  1. src/pipeline.py: imports LLMConfigError next to LLMAuthError, catches it
     wherever LLMAuthError is caught at client construction, switches the
     Phase 5 "no key" warning to OPENROUTER_API_KEY, clarifies the Phase 3
     start-up hint, and fixes one mis-indented closing parenthesis.
     The result is compiled before it is written; if it would not compile,
     the file is left untouched and the script says so.
  2. src/ and tests/: renames any leftover ANTHROPIC_API_KEY /
     anthropic_api_key / AnthropicLLMClient identifiers.
  3. README.md: current-state wording -> OpenRouter, plus a short
     "LLM provider (current)" section.
  4. PHASE*_SUMMARY.md and reports/*.md: NOT rewritten. A banner is added
     marking Anthropic-era content as historical (and PHASE6_SUMMARY.md gets
     a correction note about which files the Phase 6 commit touched).
  5. Final repository-wide scan for the old provider, printed as a report.
Safe to run more than once.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECK_ONLY = "--check" in sys.argv
MARKER = "<!-- openrouter-migration -->"
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", "node_modules", ".pytest_cache", "logs"}
SEARCH_TERMS = ["AnthropicLLMClient", "anthropic_api_key", "ANTHROPIC_API_KEY",
                "import anthropic", "from anthropic", "claude-", "Anthropic"]
changed = []


def read(path: Path):
    """UTF-8 text, or None (with a note) for files that are not UTF-8."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"! skipped {path.relative_to(ROOT)} (not UTF-8 text)")
        return None


def write(path: Path, old: str, new: str):
    if new != old:
        changed.append(str(path.relative_to(ROOT)))
        if not CHECK_ONLY:
            path.write_text(new, encoding="utf-8")


def fix_pipeline():
    path = ROOT / "src" / "pipeline.py"
    if not path.exists():
        print("! src/pipeline.py not found; run this from the repository root.")
        return
    old = path.read_text(encoding="utf-8")
    s = old

    def fix_import(m):
        names = [n.strip() for n in m.group(1).strip("() \n").split(",") if n.strip()]
        for needed in ("LLMAuthError", "LLMConfigError", "OpenRouterLLMClient"):
            if needed not in names:
                names.append(needed)
        return "from .ai.llm_client import " + ", ".join(sorted(set(names)))
    s = re.sub(r"from \.ai\.llm_client import ([^\n(]+|\([^)]*\))", fix_import, s, count=1)

    s = re.sub(r"except\s+LLMAuthError\s+as\s+(\w+):", r"except (LLMAuthError, LLMConfigError) as \1:", s)
    s = s.replace("No ANTHROPIC_API_KEY configured", "No OPENROUTER_API_KEY configured")
    s = s.replace(
        'print("Set OPENROUTER_API_KEY in your .env file (see .env.example) and try again.")',
        'print("Set OPENROUTER_API_KEY (and a free MODEL_NAME, default openrouter/free) '
        'in your .env file (see .env.example) and try again.")')
    # Mis-indented ")" closing OpenRouterLLMClient(...) in run_respond.
    s = re.sub(r"\n\)\n([ \t]+)generator = ResponseGenerator\(llm_client\)",
               r"\n\1)\n\1generator = ResponseGenerator(llm_client)", s)
    s = s.replace("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
    s = s.replace("anthropic_api_key", "openrouter_api_key")
    s = s.replace("AnthropicLLMClient", "OpenRouterLLMClient")

    try:
        compile(s, str(path), "exec")
    except SyntaxError as e:
        print(f"! src/pipeline.py would not compile after edits ({e}); left unchanged.")
        return
    write(path, old, s)


def rename_identifiers():
    for base in ("src", "tests"):
        for path in (ROOT / base).rglob("*.py"):
            if any(p in SKIP_DIRS for p in path.parts) or path.name == "pipeline.py":
                continue
            old = read(path)
            if old is None:
                continue
            s = (old.replace("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
                    .replace("anthropic_api_key", "openrouter_api_key")
                    .replace("AnthropicLLMClient", "OpenRouterLLMClient"))
            write(path, old, s)


README_SECTION = f"""{MARKER}
## LLM provider (current): OpenRouter

- **Provider:** [OpenRouter](https://openrouter.ai), through its OpenAI-compatible API
  (`https://openrouter.ai/api/v1`) using the official `openai` Python SDK.
- **Used by:** Phase 3 (ticket classification) **and** Phase 5 (response drafting).
  Both go through `OpenRouterLLMClient` in `src/ai/llm_client.py`.
- **Default model:** `openrouter/free` (OpenRouter's free router, which picks a free model
  that supports tool calling). Only free routing is supported; any other `MODEL_NAME` must
  end in `:free`, and paid models are refused at startup. No credits or billing are needed.
- **API key:** `OPENROUTER_API_KEY`, read only from your local `.env` (copy `.env.example`).
  **Never commit a key**; `.env` is git-ignored, and the key is kept out of logs, error
  messages and `repr(Config)`.
- **Dry-run / live safety is unchanged:** every phase is dry-run by default, and writing to
  the database needs both the phase's `*_DRY_RUN=false` **and** `--live`.
- **Free-tier limits:** about 20 requests/min and 50 requests/day on a free account (more
  after a one-time credit purchase). Each ticket is one call per phase, so run small
  `--limit` batches.
- Historical note: earlier phase summaries and reports describe the original Anthropic-based
  implementation (historical, not current); they are kept and marked as historical.
"""


def fix_readme():
    path = ROOT / "README.md"
    if not path.exists():
        return
    old = path.read_text(encoding="utf-8")
    s = old
    s = s.replace("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
    s = s.replace("AnthropicLLMClient", "OpenRouterLLMClient")
    s = s.replace("anthropic_api_key", "openrouter_api_key")
    s = re.sub(r"`claude-[A-Za-z0-9.\-]+`", "`openrouter/free`", s)
    s = re.sub(r"\bclaude-[A-Za-z0-9.\-]*[A-Za-z0-9]", "openrouter/free", s)
    s = s.replace("provider-agnostic interface + Anthropic implementation",
                  "provider-agnostic interface + OpenRouter implementation")
    s = re.sub(r"\bAnthropic API key\b", "OpenRouter API key", s)
    s = re.sub(r"\bAnthropic (tool[- ]use)\b", r"OpenAI-compatible function calling (\1)", s)
    s = re.sub(r"\bAnthropic SDK\b", "OpenAI SDK (pointed at OpenRouter)", s)
    s = re.sub(r"(?m)^(\s*[-*]?\s*`?)anthropic(==[\w.]+)?(`?)", r"\1openai==2.54.0\3", s)
    if MARKER not in s:
        m = re.search(r"(?m)^# .*\n", s)
        pos = m.end() if m else 0
        s = s[:pos] + "\n" + README_SECTION + "\n" + s[pos:]
    write(path, old, s)


HIST_BANNER = f"""{MARKER}
> **Historical document.** This file records the project as it was when this phase was
> completed, when the LLM provider was Anthropic. The current provider is **OpenRouter**
> (`OPENROUTER_API_KEY`, default model `openrouter/free`) for both Phase 3 and Phase 5.
> See the README for how things work now. Anthropic references below are kept as history,
> not as current instructions.

"""

PHASE6_NOTE = f"""{MARKER}
> **Correction (OpenRouter migration).** The Phase 6 commit *did* modify `src/ai/llm_client.py`,
> `src/config.py` and `src/pipeline.py`, starting the move from Anthropic to OpenRouter. The
> migration has since been completed: Phase 3 and Phase 5 both use `OpenRouterLLMClient`,
> `validate_for_live_run()` checks `OPENROUTER_API_KEY`, and the default model is
> `openrouter/free`. Mentions of `ANTHROPIC_API_KEY` below describe the situation at the time
> and are historical.

"""


def mark_historical():
    docs = sorted(ROOT.glob("PHASE*_SUMMARY.md")) + sorted((ROOT / "reports").glob("*.md"))
    for path in docs:
        old = read(path)
        if old is None or MARKER in old:
            continue
        mentions = re.search(r"anthropic|claude-", old, re.IGNORECASE)
        if path.name == "PHASE6_SUMMARY.md":
            write(path, old, PHASE6_NOTE + old)
        elif mentions:
            write(path, old, HIST_BANNER + old)


def final_scan():
    print("\nRepository scan for the old provider:")
    hits = 0
    for path in ROOT.rglob("*"):
        if (not path.is_file() or any(p in SKIP_DIRS for p in path.parts)
                or path.name in (".env", Path(__file__).name)
                or path.suffix not in (".py", ".md", ".txt", ".example", ".sql", ".toml",
                                       ".cfg", ".ini", ".yml", ".yaml", ".json", "")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT)
        if path.name.startswith("test_openrouter_"):
            continue  # regression guards that search FOR the old names on purpose
        historical = MARKER in text and path.name != "README.md"
        for n, line in enumerate(text.splitlines(), 1):
            if any(t in line for t in SEARCH_TERMS) or "anthropic" in line.lower():
                if MARKER in line or line.lstrip().startswith(">") or "historical" in line.lower():
                    continue
                hits += 1
                tag = "historical (bannered)" if historical else "CHECK"
                print(f"  [{tag}] {rel}:{n}: {line.strip()[:110]}")
        if ("sk-" + "or-") in text:
            print(f"  [WARNING] {rel} contains something that looks like an OpenRouter key. "
                  f"Remove it and rotate the key.")
    if hits == 0:
        print("  none found")


if __name__ == "__main__":
    fix_pipeline()
    rename_identifiers()
    fix_readme()
    mark_historical()
    verb = "Would change" if CHECK_ONLY else "Changed"
    print(f"{verb} {len(changed)} file(s):" + "".join(f"\n  - {c}" for c in changed))
    final_scan()
