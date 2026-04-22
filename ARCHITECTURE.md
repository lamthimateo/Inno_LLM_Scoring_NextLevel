# Architecture

This document describes the current architecture of **Inno LLM Scoring — Next Level**: modules, data flow, and the SQLite persistence model.

---

## High-level overview

The system is a lightweight, reproducible benchmark runner with a strict MCQ answer format and an exportable leaderboard.

- **Source data**: benchmark question sets are imported from text files under `imports/answer_key/`.
- **Review workflow**: sets move through `draft → in_review → approved → locked`.
- **Execution**:
  - **File runner**: parse saved model outputs from `imports/model_outputs/*.txt`
  - **API runner**: call an LLM provider (currently OpenAI) and capture raw responses
- **Scoring**: parse answers, score per question, aggregate per category + totals.
- **Persistence**: store raw outputs, parsed answers, and aggregates in SQLite (`db/benchmark.db`).
- **Export/UI**: export CSV + static `index.html` leaderboard driven by `leaderboard.json`.

---

## Module layout

### CLI / orchestration
- `scripts/benchmark.py`
  - Backwards-compatible wrapper that forwards to `src/benchmark/cli.py`.
- `src/benchmark/cli.py`
  - CLI command wiring (`init-db`, `import-questions`, `submit-review`, `approve`, `lock`, `build-prompt`, `run-file`, `run-openai`, `export`, `serve`)
  - Calls into the focused modules below.

### Benchmark pipeline utilities
- `src/benchmark/importing.py`
  - Parses question text files and imports `question_sets` + `questions` into SQLite.
- `src/benchmark/prompting.py`
  - Builds the strict “QID: LETTER” prompt from DB.
- `src/benchmark/pipeline.py`
  - Shared persistence helpers:
    - `store_model_run(...)` writes raw output + provider metadata
    - `store_answers_and_aggregates(...)` parses + scores + persists per-question + aggregates
- `src/benchmark/exporting.py`
  - Exports CSV and writes leaderboard assets (JSON + HTML).

### Runners (execution)
- `src/runner/file_runner.py`
  - Loads saved outputs from `imports/model_outputs/*.txt` into `{model_id: raw_text}`.
- `src/runner/api_runner.py`
  - Executes API calls (currently OpenAI) and returns `ModelResult` objects.

### Adapters (providers)
- `src/adapters/base.py`
  - Defines:
    - `ModelAdapter` interface (`id()`, `run(prompt, ...)`)
    - `ModelResult` dataclass (`model_id`, `raw_text`, `meta`)
- `src/adapters/openai_adapter.py`
  - Real provider integration (Responses API), retry/backoff, and robust output extraction.
- `src/adapters/anthropic_adapter.py`, `src/adapters/google_adapter.py`
  - Stubs (not wired yet).

### Evaluator (parsing + scoring)
- `src/evaluator/parser_mcq.py`
  - Extracts `QID: LETTER` pairs from raw model output and counts format violations.
- `src/evaluator/scoring.py`
  - Applies scoring rules:
    - correct = +1
    - blank = 0
    - wrong = -10
  - Aggregates by category derived from QID prefix (`C/E/M/A/N/X`).

### Storage (SQLite)
- `src/storage/schema.py`
  - `SCHEMA_SQL` used to create tables.
- `src/storage/db.py`
  - `connect()` with foreign keys enabled
  - idempotent init + lightweight migrations (e.g. adding `meta_json` to `model_runs`)

### Web export
- `src/web/leaderboard.py`
  - Writes `leaderboard.json` + static `index.html` to `results/leaderboard/`.

---

## SQLite schema (conceptual)

The DB is designed to preserve *traceability* from a run → raw output → parsed answers → scores.

### `question_sets`
Represents a benchmark set with workflow status.

- `set_id` (PK)
- `status`: `draft | in_review | approved | locked`
- `author`, `reviewer`
- `created_at`, `updated_at`

### `questions`
All questions belonging to a set.

- `(qid, set_id)` (composite PK)
- `category` (string)
- `prompt` (text)
- `choices_json` (JSON string)
- `correct_answer` (A–E)
- `scoring_rule` (currently `mcq_v1`)

### `runs`
One evaluation run against a given set.

- `run_id` (PK)
- `set_id` (FK)
- `prompt_policy` (string, e.g. `strict_format_v1`)
- `notes`
- `created_at`

### `model_runs`
Raw model output captured for each model in a run.

- `model_run_id` (PK)
- `run_id` (FK)
- `model_id` (e.g. file name, or `openai:<model>`)
- `source`: `file | api`
- `raw_text`: raw output text from the model
- `meta_json`: JSON metadata (usage, latency, response id, errors)
- `created_at`
- unique constraint: `(run_id, model_id)`

### `answers`
Per-question persisted scoring for a model run.

- `(model_run_id, qid)` (composite PK)
- `given_answer`, `correct_answer`
- `score`

### `aggregates`
Per-model-run aggregates used for leaderboard.

- `model_run_id` (PK/FK)
- category totals: `chemistry`, `emotions`, `math`, `reasoning3d`, `no_knowledge`, `contradiction`
- `total_score`
- counts: `correct_count`, `wrong_count`, `blank_count`
- `format_violations`

---

## End-to-end data flow

### A) Import + review workflow
1. `import-questions` reads text files from `imports/answer_key/`
2. Writes to `question_sets` (status `draft`) and `questions`
3. `submit-review` → status `in_review`
4. `approve` → status `approved`
5. `lock` → status `locked` (freezes the set for reproducibility)

### B) Prompt generation
1. `build-prompt` reads questions from SQLite
2. Emits a prompt with strict output rules and an answer template

### C) Run execution (two options)

**Option 1: File runner**
1. Collect model outputs manually into `imports/model_outputs/*.txt`
2. `run-file` loads these files and stores them into `model_runs`

**Option 2: API runner (OpenAI)**
1. `run-openai` calls OpenAI via `OpenAIAdapter` (Responses API)
2. Stores raw output into `model_runs.raw_text` and metadata into `model_runs.meta_json`

### D) Parsing + scoring + persistence
1. `parse_model_output` extracts `QID: LETTER` pairs and counts format violations
2. `score_answers` scores each question and aggregates by category
3. Persist into:
   - `answers` (per-question)
   - `aggregates` (per-model-run totals)

### E) Export + leaderboard
1. `export` queries `aggregates` joined with `model_runs`
2. Writes:
   - `results/benchmark_results.csv`
   - `results/leaderboard/leaderboard.json`
   - `results/leaderboard/index.html`
3. `serve` can serve the leaderboard directory locally.

