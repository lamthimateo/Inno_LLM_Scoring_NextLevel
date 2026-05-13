# Inno LLM Scoring — Next Level

A **mini LM-Arena-style benchmark runner** with a review workflow, provider
adapters, SQLite storage, and a static leaderboard.

- Strict MCQ format (`QID: LETTER`) so scoring is deterministic.
- Two-person sign-off on question sets (`draft → in_review → approved → locked`).
- Two execution modes: **paste-from-UI** (any model) or **API** (OpenAI today).
- All results live in `db/benchmark.db` and can be exported to CSV + a
  self-contained HTML leaderboard.

For the deep dive (modules, data flow, schema), see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Project structure

```
.
├── ARCHITECTURE.md          # full module + DB walkthrough
├── CHANGELOG.md             # human-written change notes
├── README.md
├── pyproject.toml           # package metadata + console script
├── requirements.txt         # pinned runtime deps
│
├── imports/
│   ├── answer_key/          # source benchmark .txt (with "Correct answer: X")
│   ├── blind_test/          # same questions WITHOUT answers (paste into models)
│   └── model_outputs/       # collected model replies (one .txt per model)
│
├── docs/
│   └── tasks/               # per-person sprint deliverable notes
│
├── scripts/
│   ├── benchmark.py         # backwards-compat wrapper -> src.benchmark.cli:main
│   └── benchmark_review.py  # static QA report over imports/answer_key/
│
├── src/
│   ├── benchmark/           # CLI + import / prompt / pipeline / export
│   ├── adapters/            # OpenAI (real), Anthropic + Google (stubs)
│   ├── runner/              # file-based + API-based execution
│   ├── evaluator/           # MCQ parser + scoring rules
│   ├── storage/             # SQLite schema + migrations
│   └── web/                 # FastAPI dashboard + static leaderboard renderer
│
└── tests/                   # unittest suite (parser, scoring, DB, adapter)
```

`db/` and `results/` are created on demand and are **gitignored** — they hold
generated artifacts only.

---

## Question categories

Each QID prefix maps to one of six categories. The scoring pipeline aggregates
per category and exposes it in the leaderboard.

| Prefix | Category        | What it stresses                            |
|:------:|-----------------|---------------------------------------------|
| `C`    | `chemistry`     | factual recall                              |
| `E`    | `emotions`      | social / affective reasoning                |
| `M`    | `math`          | multi-step calculation                      |
| `A`    | `reasoning3d`   | spatial / 3D reasoning                      |
| `N`    | `no_knowledge`  | does the model admit when it doesn't know?  |
| `X`    | `contradiction` | does the model push back on user input?     |

Scoring rule per question:

| Outcome  | Score |
|----------|------:|
| correct  | **+1** |
| blank    |   0   |
| wrong    | **-10** |

The harsh penalty for wrong answers is intentional — it prevents random
guessing from outperforming honest abstention on the `N` and `X` categories.

---

## Adapter status

| Provider     | Adapter                          | Wired? | Env var            |
|--------------|----------------------------------|:------:|--------------------|
| OpenAI       | `src/adapters/openai_adapter.py` | yes    | `OPENAI_API_KEY`   |
| Anthropic    | `src/adapters/anthropic_adapter.py` | stub | `ANTHROPIC_API_KEY` |
| Google       | `src/adapters/google_adapter.py` | stub   | `GOOGLE_API_KEY`   |

For non-OpenAI providers, run them manually through their UI, paste each reply
into `imports/model_outputs/<model_id>.txt`, then use `run-file`.

---

## Setup

Requires **Python 3.10+**.

```bash
python3 -m pip install -r requirements.txt
python3 scripts/benchmark.py init-db
```

---

## Workflow

### 1) Import questions + review

```bash
python3 scripts/benchmark.py import-questions \
  --source imports/answer_key \
  --set-id benchmark_v1 \
  --author mateo

python3 scripts/benchmark.py submit-review --set-id benchmark_v1 --reviewer nikoleta
python3 scripts/benchmark.py approve       --set-id benchmark_v1 --reviewer nikoleta
python3 scripts/benchmark.py lock          --set-id benchmark_v1
```

### 2) Build the prompt

```bash
python3 scripts/benchmark.py build-prompt --set-id benchmark_v1 --out results/prompt_to_models.txt
```

### 3a) Run via API (OpenAI)

```bash
export OPENAI_API_KEY="..."
python3 scripts/benchmark.py run-openai \
  --set-id benchmark_v1 \
  --run-id run_openai_001 \
  --models gpt-4.1,gpt-4.1-mini
```

### 3b) Run from saved model replies (any provider)

Drop each model's reply as `imports/model_outputs/<model_id>.txt`, then:

```bash
python3 scripts/benchmark.py run-file \
  --set-id benchmark_v1 \
  --model-outputs imports/model_outputs \
  --run-id run_001
```

### 4) Export results + leaderboard

```bash
python3 scripts/benchmark.py export --run-id run_001 --out results
python3 scripts/benchmark.py serve  --dir results/leaderboard --port 8080
# open http://localhost:8080
```

### 5) Web UI (optional)

Run OpenAI jobs from a browser:

```bash
export OPENAI_API_KEY="..."
python3 -m uvicorn src.web.app:app --reload --port 8000
# open http://localhost:8000
```

### 6) Static QA report on the question set

```bash
python3 scripts/benchmark_review.py \
  --in  imports/answer_key \
  --out results/benchmark_review_report.md
```

---

## Model reply format (STRICT)

Each model must output **only**:

```
C1: C
C2:
...
X10: B
```

Blank after `:` means *no answer*. Anything else on that line counts as a
**format violation** on the leaderboard.

---

## Tests

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

Three suites:

- `tests/test_parser_scoring.py` — MCQ parser + scoring edge cases
- `tests/test_db_migrations.py`  — additive schema migration applies idempotently
- `tests/test_openai_error_paths.py` — missing key produces a clear error

---

## Per-person task notes

Sprint deliverables and implementation notes per teammate live in
[`docs/tasks/`](docs/tasks/). Update them when finishing a sprint item.
