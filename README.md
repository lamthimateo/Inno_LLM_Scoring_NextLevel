# Inno LLM Scoring — Next Level (Review + Adapters + SQLite + Web Leaderboard)

This project is a **mini LM-Arena-style benchmark runner** with:

- **Question workflow**: Draft → In Review → Approved → Locked (two-person signoff)
- **Model connectors** (adapters): file-based runner + stubs for API-based runners
- **SQLite database** for reproducible runs, raw outputs, and scores
- **Web dashboard** (static HTML + local server) showing a leaderboard like LM Arena

## 0) Folder overview

- `imports/answer_key/` : your benchmark category files **with** correct answers
- `imports/blind_test/` : the same benchmark **without** answers (what you paste into models)
- `imports/model_outputs/` : saved model replies (`QID: LETTER`)
- `db/benchmark.db` : SQLite database (created by `init-db`)
- `results/` : CSV/JSON/HTML outputs

## 1) Setup

Requires **Python 3.10+**.

From the project root:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/benchmark.py init-db
```

## 2) Import questions (draft) + two-person review

Import from your `imports/answer_key/*.txt` files:

```bash
python3 scripts/benchmark.py import-questions \
  --source imports/answer_key \
  --set-id benchmark_v1 \
  --author mateo
```

Submit for review:

```bash
python3 scripts/benchmark.py submit-review --set-id benchmark_v1 --reviewer nikoleta
```

Approve (second person):

```bash
python3 scripts/benchmark.py approve --set-id benchmark_v1 --reviewer nikoleta
```

Lock the set for reproducibility:

```bash
python3 scripts/benchmark.py lock --set-id benchmark_v1
```

## 3) Build the prompt for models

```bash
python3 scripts/benchmark.py build-prompt --set-id benchmark_v1 --out results/prompt_to_models.txt
```

Paste that prompt into each model. Save each model's reply as a `.txt` file under `imports/model_outputs/`.

## 4) Run scoring from saved model outputs

```bash
python3 scripts/benchmark.py run-file \
  --set-id benchmark_v1 \
  --model-outputs imports/model_outputs \
  --run-id run_001
```

This stores raw outputs + parsed answers + per-question scores into SQLite.

## 5) Export results

CSV + JSON + HTML leaderboard:

```bash
python3 scripts/benchmark.py export --run-id run_001 --out results
```

Open the leaderboard:

```bash
python3 scripts/benchmark.py serve --dir results/leaderboard --port 8080
# then open http://localhost:8080
```

## 6) Add API adapters later

See `src/adapters/` for the adapter interface and stubs (OpenAI/Anthropic/Gemini). They are wired so you can add real API calls later without changing scoring.

## 7) Run via OpenAI API (one-provider stable integration)

Set your API key:

```bash
export OPENAI_API_KEY="..."
```

Run one or more OpenAI models directly (no copy/paste step):

```bash
python3 scripts/benchmark.py run-openai \
  --set-id benchmark_v1 \
  --run-id run_openai_001 \
  --models gpt-4.1,gpt-4.1-mini
```

Then export as usual:

```bash
python3 scripts/benchmark.py export --run-id run_openai_001 --out results
```

---

### Model reply format (STRICT)

Each model must output **only**:

```
C1: C
C2:
...
X10: B
```

Blank after `:` = *no answer*.
