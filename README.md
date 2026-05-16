# LLM Arena

A **web-first LM-Arena-style benchmark runner** with a two-person review
workflow, multi-provider model adapters, PostgreSQL storage, and live runs
against four LLMs in a single click.

- Login-only web UI (FastAPI + Jinja2 + HTMX). The CLI is gone.
- Two-tab interface: **Questions** (author / review / lock) and
  **Results** (start runs, watch progress, view leaderboard).
- Two-person sign-off on every question set:
  `draft → in_review → approved → locked`. The approver can **never** be
  the author — enforced at the service layer with an audit log.
- Strict MCQ output format (`QID: LETTER`) so scoring is deterministic.
- Four-model evaluation by default via **OpenRouter** (OpenAI, Anthropic,
  Google, Meta — one API key, four providers).
- Reproducibility: only locked sets can be evaluated. Every run keeps
  the raw model output, parsed answers, per-category scores, and
  provider metadata in Postgres.

---

## Quick start (Docker)

The shortest path from `git clone` to a working UI:

```bash
cp .env.example .env
# Edit .env: set SESSION_SECRET. For live runs, either add OPENROUTER_API_KEY,
# or set all four native keys (ANTHROPIC_API_KEY, GOOGLE_API_KEY, GROQ_API_KEY,
# MISTRAL_API_KEY) to use direct SDK adapters as the default preset, or use
# OPENAI_API_KEY alone for OpenAI-direct defaults.

docker compose up --build
```

That brings up four containers:

| Service     | Port  | Purpose                                                       |
| ----------- | ----- | ------------------------------------------------------------- |
| `postgres`  | 5432  | Application database.                                         |
| `redis`     | 6379  | Reserved for background-job persistence (RQ).                 |
| `app`       | 8000  | FastAPI app + uvicorn (auto-reload in dev).                   |
| `worker`    | —     | RQ worker (optional; runs the evaluation jobs).               |

Open <http://localhost:8000>. You'll see the login screen.

### Default accounts

The `app` container runs `python -m src.web.seed` on first boot. By default
it creates three accounts so the two-person review can be demonstrated:

| Username    | Password       | Role     |
| ----------- | -------------- | -------- |
| `admin`     | `inno-admin`   | admin    |
| `mateo`     | `mateo1234`    | author   |
| `nikoleta`  | `nikoleta1234` | reviewer |

> Override the admin password with `SEED_ADMIN_PASSWORD=...` in `.env`.
> Set `SEED_DEMO_USERS=0` to skip the two demo accounts.

### Demo walk-through

1. Log in as **mateo** (author).
2. Go to **Questions → + Import new set**. Drop any `.txt` from
   `imports/answer_key/` and pick a `set_id` (e.g. `benchmark_v1`).
3. On the set detail page click **Submit for review** and pass the
   reviewer's user id (you can grab it from `docker compose exec
   postgres psql -U benchmark -c 'select id, username from users;'`).
4. Log out and log back in as **nikoleta** (reviewer). Open the set,
   click **Approve**, then **Lock**.
5. Switch to the **Results** tab and click **+ New run**. Pick the
   locked set; the four default models are pre-filled. Click **Start
   run**. The page polls the run status every 2 seconds and the
   leaderboard fills in as each model returns.

---

## What's inside

```
.
├── alembic/                 Database migrations (autogenerate-capable)
├── alembic.ini
├── docker-compose.yml       postgres + redis + app + worker
├── Dockerfile
├── .env.example             every env var the app reads
├── imports/                 sample input data (answer-key text files)
├── pyproject.toml           deps (mirrored in requirements.txt)
├── requirements.txt
├── static/                  css, js, logo — no build step
│   ├── css/app.css          design tokens + components
│   ├── img/logo.png         brand mark (also used as favicon)
│   └── js/                  htmx + a vanilla helper (theme/toast/modals)
├── src/
│   ├── adapters/            model adapters
│   │   ├── base.py          ModelAdapter / ModelResult
│   │   ├── openai_adapter.py        OpenAI Responses API + retries
│   │   ├── openrouter_adapter.py    OpenRouter Chat Completions
│   │   ├── anthropic_adapter.py     Claude Messages API
│   │   ├── google_adapter.py        Gemini (`google-genai`)
│   │   ├── groq_adapter.py          Groq (OpenAI-compatible)
│   │   ├── mistral_adapter.py       Mistral chat completions
│   │   └── registry.py      'provider:model' → adapter
│   ├── auth/                authentication
│   │   ├── passwords.py     bcrypt via passlib
│   │   ├── service.py       register / login / change / reset
│   │   ├── dependencies.py  FastAPI deps (current_user, require_role)
│   │   └── router.py        /auth/* HTTP routes
│   ├── benchmark/           domain logic
│   │   ├── importing.py     parse .txt files + persist Questions
│   │   ├── workflow.py      review state transitions + question edits
│   │   ├── queries.py       read-side query helpers
│   │   ├── prompting.py     build the strict MCQ prompt
│   │   ├── pipeline.py      store_model_run + store_answers_and_aggregates
│   │   ├── runs.py          create_run + execute_run + run_in_background
│   │   └── exporting.py     export to CSV + static leaderboard assets
│   ├── evaluator/           parsing + scoring
│   ├── storage/
│   │   ├── models.py        full SQLAlchemy schema
│   │   └── db.py            engine + sessionmaker
│   └── web/                 HTTP layer
│       ├── app.py           FastAPI entrypoint + middleware wiring
│       ├── templating.py    shared Jinja2 + render()
│       ├── seed.py          idempotent user seed (env-driven)
│       ├── leaderboard.py   static HTML/JSON leaderboard writer
│       ├── routes/
│       │   ├── questions.py /questions/* (list, import, detail, edit, workflow)
│       │   └── runs.py      /runs/* (list, new, detail, status fragment)
│       └── templates/       Jinja2 (extends _base.html)
└── tests/                   pytest — sqlite in-memory
```

### Database schema

| Table                  | Rows                                                                |
| ---------------------- | ------------------------------------------------------------------- |
| `users`                | authn, role (admin/author/reviewer)                                 |
| `audit_log`            | every state-changing action                                         |
| `question_sets`        | set + status + author_id + reviewer_id                              |
| `questions`            | current version of each question                                    |
| `question_versions`    | historical snapshots (diff view)                                    |
| `runs`                 | one evaluation against a locked set                                 |
| `model_runs`           | raw output + provider meta per (run, model)                         |
| `answers`              | parsed per-question score                                           |
| `aggregates`           | per-model totals + per-category sub-scores                          |
| `jobs`                 | background-job persistence (status + progress + error)              |
| `password_reset_tokens`| single-use tokens (TTL 1h; link logged to server log)               |

Migrations live in `alembic/versions/`. The initial revision uses
`Base.metadata.create_all` (cheap on a greenfield schema). Future schema
changes should be auto-generated with
`alembic revision --autogenerate -m "..."` so they produce explicit
`op.create_table` / `op.alter_column` operations.

---

## Local development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./db/benchmark.db"
export SESSION_SECRET="dev-secret"
mkdir -p db
alembic upgrade head
python -m src.web.seed
uvicorn src.web.app:app --reload
```

The same code works on SQLite (development + tests) and PostgreSQL
(Docker / production); the only switch is `DATABASE_URL`.

---

## Running the tests

```bash
DATABASE_URL="sqlite:///:memory:" SESSION_SECRET=test pytest -q
```

What's covered:

- **Parser + scoring** (4) — pure unit tests around the strict-format parser.
- **OpenAI error paths** (3) — adapter retries, missing-key error, reasoning-model temperature handling.
- **DB schema** (2) — every table from `create_all`, `meta_json` present.
- **Pipeline / workflow** (5) — import → submit → approve → lock → run → aggregate.
- **Auth service** (20) — register / login / change / reset / hash helpers.
- **Auth routes** (7) — full HTTP flow via FastAPI TestClient.
- **Questions routes** (20) — list, import preview + submit path, two-person review, edit, 403 + 404.
- **Runs orchestration** (6) — happy path, partial failure, total failure, cancellation.
- **Runs routes** (10) — list, new-run modal, status fragment, leaderboard, cancel.
- **Template smoke** (5) — every rendered template returns 200.
- **End-to-end** (1) — login → import → review → lock → run → leaderboard,
  all via HTTP, with a mocked adapter.

84 tests, ~35 s on a laptop.

---

## Environment variables

| Var                       | Default                                        | Notes                                              |
| ------------------------- | ---------------------------------------------- | -------------------------------------------------- |
| `DATABASE_URL`            | `postgresql+psycopg://benchmark:…`             | Override to `sqlite:///./db/benchmark.db` for dev. |
| `SESSION_SECRET`          | `dev-secret-change-me`                         | Signs session cookies. **Set in prod.**            |
| `OPENAI_API_KEY`          | unset                                          | Required for `openai:*` model IDs.                 |
| `OPENROUTER_API_KEY`      | unset                                          | Required for `openrouter:*` model IDs.             |
| `ANTHROPIC_API_KEY`       | unset                                          | Required for `anthropic:*` model IDs.              |
| `GOOGLE_API_KEY`          | unset                                          | Required for `google:*` (Gemini) model IDs.        |
| `GROQ_API_KEY`            | unset                                          | Required for `groq:*` model IDs.                   |
| `MISTRAL_API_KEY`         | unset                                          | Required for `mistral:*` model IDs.                |
| `MISTRAL_AGENT_ID`        | unset                                          | If set, adds `mistral-agent:<id>` to the picker (beta Agents API). |
| `MISTRAL_AGENT_VERSION`   | `0`                                            | Passed to Agents API ``agent_version``.           |
| `OPENROUTER_HTTP_REFERER` | `https://github.com/inno-llm-scoring`          | Sent to OpenRouter for traffic routing.            |
| `OPENROUTER_APP_TITLE`    | `LLM Arena`                                    |                                                    |
| `SEED_ADMIN_USERNAME`     | `admin`                                        |                                                    |
| `SEED_ADMIN_PASSWORD`     | `inno-admin`                                   | Must be ≥ 8 chars. **Change in prod.**             |
| `SEED_DEMO_USERS`         | `1`                                            | Set to `0` to skip the mateo/nikoleta accounts.    |

---

## Adapters

| Provider              | Status         | Notes                                                                  |
| --------------------- | -------------- | ---------------------------------------------------------------------- |
| `openai:*`            | implemented    | Responses API. `OPENAI_API_KEY`.                       |
| `openrouter:*`        | implemented    | Chat Completions. `OPENROUTER_API_KEY` (falls back to `OPENAI_API_KEY` for dev). |
| `anthropic:*`         | implemented    | Messages API. `ANTHROPIC_API_KEY`.                     |
| `google:*`            | implemented    | Gemini via `google-genai`. `GOOGLE_API_KEY`.         |
| `groq:*`              | implemented    | Chat Completions. `GROQ_API_KEY`.                      |
| `mistral:*`           | implemented    | Chat completions. `MISTRAL_API_KEY`.              |
| `mistral-agent:*`     | implemented    | Agents beta (`beta.conversations.start`). Same API key; set `MISTRAL_AGENT_ID` for picker entry. |

If **all four** native keys (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`,
`GROQ_API_KEY`, `MISTRAL_API_KEY`) are set, the run form defaults to one
model per provider. Otherwise, OpenRouter (if configured) or OpenAI-direct
presets apply.

OpenRouter remains convenient when you want **one** key across vendors.

---

## License

Coursework — FH Technikum Wien, Innovation 2, SS2026.
