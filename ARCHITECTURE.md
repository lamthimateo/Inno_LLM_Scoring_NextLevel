# Architecture

This document describes the architecture of **LLM Arena**: modules, runtime
topology, data flow, and the relational schema.

The system was rewritten from a CLI-only tool into a web app in v0.2.0; this
document reflects the current GUI-based, Postgres-backed system. The
historical CLI design lives in `docs/archive/tasks/` for reference.

---

## High-level overview

LLM Arena is a reproducible MCQ benchmark runner with a two-person review
workflow, a multi-provider adapter layer, and a static leaderboard export.

- **Authoring**: users upload `.txt` answer-key files; the importer parses
  them into versioned `QuestionSet` + `Question` rows.
- **Review workflow**: sets move `draft → in_review → approved → locked`.
  The approver cannot be the author (enforced at the service layer).
- **Execution**: locked sets can be evaluated against any registered model
  via the adapter registry. Runs execute against four models in parallel
  by default via OpenRouter.
- **Scoring**: a strict `QID: LETTER` parser extracts answers and the
  evaluator scores them (+1 correct / 0 blank / -10 wrong) and aggregates
  by category.
- **Persistence**: every run keeps the raw model output, parsed answers,
  per-category scores, and provider metadata in Postgres (SQLite for
  tests and local development).
- **Export / UI**: results render in the live web UI and can also be
  exported to a static HTML + JSON leaderboard.

---

## Runtime topology

`docker compose up` brings up four services:

| Service     | Image                | Purpose                                                    |
| ----------- | -------------------- | ---------------------------------------------------------- |
| `postgres`  | `postgres:16-alpine` | Application database.                                      |
| `redis`     | `redis:7-alpine`     | Job queue backing store (RQ).                              |
| `app`       | built from Dockerfile | FastAPI + uvicorn, runs migrations + seeds users at boot.  |
| `worker`    | built from Dockerfile | RQ worker for background run execution.                    |

Static assets (CSS, JS, logo) are served from `/static` (repo-root
`static/`). Templates live in `src/web/templates/` and are rendered via
Jinja2 + HTMX for partial updates.

---

## Module layout

### `src/web/` — HTTP layer
- `app.py` — FastAPI entrypoint, session middleware, static mount,
  router wiring.
- `templating.py` — shared Jinja2 environment, `render()` helper,
  Flask-style `url_for()` shim for the design-system templates.
- `seed.py` — idempotent user seeder (env-driven; runs on first boot).
- `leaderboard.py` — writes a static `index.html` + `leaderboard.json`
  pair from a list of leaderboard rows.
- `routes/questions.py` — `/questions/*` (list, import preview, detail,
  edit, workflow transitions).
- `routes/runs.py` — `/runs/*` (list, new-run modal, status fragment,
  leaderboard, cancel).

### `src/auth/` — authentication
- `passwords.py` — bcrypt hashing via passlib.
- `service.py` — register / login / change / reset, with audit logging.
- `dependencies.py` — FastAPI deps (`get_current_user`, `require_role`).
- `router.py` — `/auth/*` routes (login / logout / signup / forgot /
  reset / change-password).

### `src/benchmark/` — domain logic
- `importing.py` — parse `*.txt` answer-key files into `ParsedQuestion`s
  and persist them as `Question` rows under a `QuestionSet`.
- `validation.py` — static-content checks (duplicate QIDs, missing
  choices, missing answers, short choices) used by the import preview
  and by `scripts/benchmark_review.py`.
- `workflow.py` — two-person review state transitions + question edit
  versioning.
- `queries.py` — read-side query helpers used by routes.
- `prompting.py` — build the strict `QID: LETTER` prompt from DB rows.
- `pipeline.py` — `store_model_run()` and
  `store_answers_and_aggregates()` (parse + score + persist).
- `runs.py` — `create_run()` / `execute_run()` orchestration with
  cancellation support; background-job entrypoint for the RQ worker.
- `exporting.py` — query `aggregates ⋈ model_runs` and (optionally)
  write the static leaderboard.

### `src/adapters/` — model providers
- `base.py` — `ModelAdapter` interface and `ModelResult` dataclass
  (`model_id`, `raw_text`, `meta`).
- `openai_adapter.py` — OpenAI Responses API with retries / backoff.
- `openrouter_adapter.py` — OpenRouter Chat Completions (single key,
  many providers).
- `anthropic_adapter.py`, `google_adapter.py`, `groq_adapter.py`,
  `mistral_adapter.py` — native SDK adapters (`ANTHROPIC_API_KEY`,
  `GOOGLE_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`).
- `mistral_agent_adapter.py` — Mistral **Agents** beta
  (`mistral-agent:<id>` when ``MISTRAL_AGENT_ID`` is set).
- `registry.py` — `provider:model` → adapter lookup + the curated
  catalog used by the new-run model picker.

### `src/evaluator/` — parsing + scoring
- `parser_mcq.py` — extracts `QID: LETTER` pairs from raw model output
  and counts format violations.
- `scoring.py` — applies the scoring rules and aggregates by category
  derived from the QID prefix (`C/E/M/A/N/X`).

### `src/storage/` — persistence
- `models.py` — full SQLAlchemy ORM schema (Postgres / SQLite portable).
- `db.py` — engine + sessionmaker; SQLite-specific `PRAGMA foreign_keys`
  and `StaticPool` handling so tests can run on `sqlite:///:memory:`.

### `alembic/` — migrations
- `env.py` + `versions/0001_initial_schema.py` — initial schema using
  `Base.metadata.create_all` (greenfield). Future schema changes should
  be autogenerated with `alembic revision --autogenerate`.

### `scripts/`
- `benchmark_review.py` — offline batch QA report. Runs the same
  checks as `src/benchmark/validation.py` but emits a markdown summary
  for `imports/answer_key/*.txt`. Useful for CI gates.

### `tests/`
- pytest, SQLite in-memory. Covers parser/scoring, adapter retries,
  schema, pipeline, auth, every HTML route, and one full end-to-end
  flow via FastAPI's `TestClient`.

---

## Database schema

All tables live in Postgres in production and SQLite in tests/dev. The
schema is defined as SQLAlchemy ORM classes in `src/storage/models.py`
and managed via Alembic.

| Table                   | Rows                                                        |
| ----------------------- | ----------------------------------------------------------- |
| `users`                 | authn (bcrypt hash), role (`admin / author / reviewer`).    |
| `audit_log`             | every state-changing action (who, when, what).              |
| `question_sets`         | set + status + `author_id` + `reviewer_id`.                 |
| `questions`             | current version of each question.                           |
| `question_versions`     | historical snapshots used by the diff view.                 |
| `runs`                  | one evaluation against a locked set.                        |
| `model_runs`            | raw output + provider meta per `(run, model)`.              |
| `answers`               | parsed per-question score.                                  |
| `aggregates`            | per-model totals + per-category sub-scores.                 |
| `jobs`                  | background-job persistence (status, progress, error).       |
| `password_reset_tokens` | single-use tokens, TTL 1h.                                  |

Two-person review is enforced by FK + service-layer checks: the
`reviewer_id` is required for `approve` / `lock` and must differ from
`author_id`. Every transition is recorded in `audit_log`.

---

## End-to-end data flow

### A) Import + review workflow
1. Author opens **Questions → + Import new set**, picks one or more
   `.txt` files, and hits **Preview**.
2. `POST /questions/preview` parses the files and runs
   `validate_questions()` (see `src/benchmark/validation.py`), rendering
   an HTMX fragment with categories, duplicates, missing choices, etc.
3. **Save** writes `QuestionSet` (status `draft`) and `Question` rows.
4. Author clicks **Submit for review** → status `in_review`.
5. A different user (reviewer) clicks **Approve** → `approved`, then
   **Lock** → `locked`. Locked sets are immutable.

### B) Run execution
1. User picks a locked set on **Runs → + New run** and selects one or
   more models from the curated catalog.
2. `POST /runs` creates a `runs` row (status `queued`) and enqueues the
   RQ job that calls `src.benchmark.runs.execute_run`.
3. The orchestrator loops over `(run_id, model_id)` pairs:
   - Looks up the adapter via `src/adapters/registry.py`.
   - Calls `adapter.run(prompt, ...)`, capturing the raw response and
     provider metadata.
   - Persists the result via `store_model_run()` →
     `store_answers_and_aggregates()`.
4. The detail page polls `/runs/{id}/status` (HTMX) every 2 s and the
   leaderboard fills in as each model returns.

### C) Scoring
1. `parse_model_output` extracts `QID: LETTER` pairs from the raw model
   output and counts format violations.
2. `score_answers` applies +1 / 0 / −10 and aggregates by category from
   the QID prefix (`C/E/M/A/N/X`).
3. Persisted into `answers` (per-question) and `aggregates`
   (per-model-run totals).

### D) Export
1. `fetch_leaderboard_rows(session, run_id)` joins `aggregates` with
   `model_runs` and returns a list of dicts.
2. The web leaderboard renders these rows in-page.
3. For an offline snapshot, `export_results(...)` writes:
   - `results/benchmark_results.csv`
   - `results/leaderboard/leaderboard.json`
   - `results/leaderboard/index.html` (sortable, comparable, no build)

`results/` is gitignored — exports are generated, not source-controlled.

---

## Test surface

`DATABASE_URL=sqlite:///:memory: SESSION_SECRET=test pytest -q`

The suite is fully self-contained: every test resets the schema, no
external services are required, and adapter calls are patched out.
