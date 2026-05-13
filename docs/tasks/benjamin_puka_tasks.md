# Benjamin Puka — Tasks (Benchmark Content)

This document summarizes supporting work added to help complete Benjamin’s benchmark-content responsibilities, and where the outputs live.

Benjamin’s items (from the sprint plan screenshot) are primarily **content and review** tasks:
- Review current benchmark set / group questions
- Refine categories / add new items
- Expand benchmark set / define criteria
- Finalize demo benchmark set
- Polish benchmark content / remove weak items
- Final benchmark review / prepare summary

Because content quality is a human/editorial decision, the repo now contains an **automated QA + review report** to speed up the review and help identify weak spots consistently.

---

## What was implemented (support tooling)

### Benchmark QA / review report generator
Added a script that scans `imports/answer_key/*.txt` and outputs a markdown report containing:
- total questions parsed
- category counts by QID prefix (C/E/M/A/N/X)
- duplicates / missing correct answers / missing choices
- simple “weak signal” heuristics (e.g., suspiciously short choices)
- importer-format warnings that may break ingestion

**Script**
- `scripts/benchmark_review.py`

**Generated report (current)**
- `results/benchmark_review_report.md`

---

## Current benchmark status (from report)

- 6 category files scanned
- 60 questions parsed
- Balanced: 10 questions per category prefix (C/E/M/A/N/X)
- No duplicates / no missing answers / no missing choices
- Some “suspiciously short choices” flagged (mostly numeric-only options). These are not necessarily wrong, but they are worth reviewing for clarity.

---

## How Benjamin can use this

### 1) Run the review report after edits

```bash
python3 scripts/benchmark_review.py --in imports/answer_key --out results/benchmark_review_report.md
```

### 2) Use the report as the “review summary”
- Attach or copy the sections (counts + findings) into your sprint deliverables.
- Use the flagged items as a shortlist for “remove weak items / polish content”.

### 3) Suggested criteria (practical)
- Each question has:
  - clear prompt
  - exactly 5 choices A–E
  - exactly one correct answer
  - no ambiguous wording
  - no “trick” formatting that could confuse models
- Keep category balance roughly even (unless intentionally weighted).

---

## Files involved

- Source benchmark:
  - `imports/answer_key/*.txt`
  - `imports/blind_test/*.txt` (no answers)
- Tooling + outputs:
  - `scripts/benchmark_review.py`
  - `results/benchmark_review_report.md`

