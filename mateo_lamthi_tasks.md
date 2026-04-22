# Mateo Lamthi — Tasks Completed (Apr 21, 2026)

This document summarizes the work completed for the checklist items:

- Review existing API adapters
- Connect real APIs
- Improve API error handling
- Store model outputs correctly
- Test backend workflow

---

## 1) Review existing API adapters

### What was found
- `src/adapters/base.py`: defines `ModelAdapter` + `ModelResult` interface.
- `src/adapters/openai_adapter.py`: existed as a stub; now implemented (see below).
- `src/adapters/anthropic_adapter.py` and `src/adapters/google_adapter.py`: remain stubs (not integrated yet).

---

## 2) Connect real APIs (one-provider stable integration)

### What was implemented
Connected **OpenAI** as the first “real” provider using the official Python SDK + **Responses API**.

### Key additions/changes
- **Implemented** `OpenAIAdapter.run()` to perform real requests and return `ModelResult`.
  - File: `src/adapters/openai_adapter.py`
- **Added** API runner helper to call one or multiple OpenAI models.
  - File: `src/runner/api_runner.py`
- **Added** CLI command `run-openai` to run the benchmark directly via OpenAI (no copy/paste).
  - Implemented in the main CLI (now located in `src/benchmark/cli.py`)
  - Backwards compatible wrapper preserved: `scripts/benchmark.py`

### Usage

```bash
export OPENAI_API_KEY="..."

python3 scripts/benchmark.py run-openai \
  --set-id benchmark_v1 \
  --run-id run_openai_001 \
  --models gpt-4.1,gpt-4.1-mini
```

---

## 3) Improve API error handling

### What was implemented
- **Retries + exponential backoff** for transient failures (rate limits/timeouts/connection/server errors).
- **Clearer error messages** that include the model name and attempt count.
- **Per-model isolation**: in `run-openai`, models are called one-by-one so a single failure doesn’t abort the entire run.

### Where
- Retries/backoff: `src/adapters/openai_adapter.py` (`max_retries`, backoff logic)
- Per-model isolation + error capture: `src/benchmark/cli.py` (`run_openai` path)

---

## 4) Store model outputs correctly (request → response → storage)

### What was implemented
- Raw model output is stored in SQLite table `model_runs.raw_text` for both:
  - file-based runs (`source='file'`)
  - API-based runs (`source='api'`)
- Added a place to store **provider metadata** (response id / latency / usage / errors):
  - `model_runs.meta_json` (JSON-encoded text)
- Added a **lightweight migration** so existing DBs get the new column automatically.

### Where
- Schema addition: `src/storage/schema.py` (`meta_json` column)
- Migration on connect/init: `src/storage/db.py` (`_ensure_schema_migrations`)
- Insert logic (writes `meta_json`):
  - `src/benchmark/pipeline.py` (`store_model_run`)
  - (used by both `run-file` and `run-openai`)

---

## 5) Test backend workflow (edge cases + reliability)

### What was implemented
Added a small `unittest` suite covering brittle edges:
- MCQ parsing behavior (blanks, duplicates, violation heuristics)
- Scoring correctness per question + per category
- DB migration reliability for `meta_json`
- OpenAI adapter missing-key error path

### Where
- `tests/test_parser_scoring.py`
- `tests/test_db_migrations.py`
- `tests/test_openai_error_paths.py`

### How to run tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

---

## Project cleanliness refactor (extra)

To keep the project easier to maintain, the large CLI script was refactored into a small package.

### What changed
- New package: `src/benchmark/`
  - `cli.py`, `prompting.py`, `importing.py`, `pipeline.py`, `exporting.py`, `constants.py`
- Backwards compatibility:
  - `scripts/benchmark.py` is now a thin wrapper that forwards to `src.benchmark.cli:main`

### Packaging/deps
- Added `requirements.txt` with `openai==2.30.0`
- Added `pyproject.toml` for a standard project definition

---

## Security / hygiene fixes

- Removed a real key from `.env.example` (it now contains placeholders only).
- Added root `.gitignore` to prevent committing:
  - `__pycache__/`, `*.pyc`
  - `results/`
  - local DB files (`db/*.db`)
  - `.env`

---

## Current status vs checklist

- **Review existing API adapters**: Done
- **Connect real APIs**: Done for **OpenAI** (Anthropic/Google still stubs)
- **Improve API error handling**: Done
- **Store model outputs correctly**: Done (raw outputs + `meta_json`)
- **Test backend workflow**: Done (unit tests passing)

