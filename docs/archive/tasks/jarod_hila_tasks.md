# Jarod Hila — Tasks (UI / Leaderboard)

This document summarizes what was implemented for Jarod’s leaderboard/UI checklist and where to verify it.

---

## Checklist items covered

- Improve leaderboard layout
- Improve comparison view
- Improve score display
- Improve input form
- Check responsive design

---

## What was implemented

### Leaderboard layout + design polish
- Modernized styling (cards, spacing, typography, gradients, shadows).
- Improved table readability (sticky header, zebra rows, hover/selection states).
- Added **Light/Dark theme toggle** (defaults to system preference, persists in `localStorage`).

### Comparison view
- Added a **side-by-side comparison panel**.
- Click table rows to select up to **2 models**; includes mini bars for category scores.
- Added “Clear compare” and “Show compared only” controls.

### Score display
- Total score includes a compact “score tag” with a colored dot.
- Compare panel shows visual bars for category scores for quick scanning.

### Input/filter form
- Replaced single input with a small toolbar:
  - filter field
  - clear compare
  - show compared only toggle
  - compare chips (selected models)

### Responsive design
- Grid collapses to a single column below ~980px.
- Table remains usable on mobile via horizontal scroll container.

---

## Where it lives (source of truth)

- `src/web/leaderboard.py`
  - Generates `index.html` + `leaderboard.json` under the export folder.

---

## How to verify (demo)

1) Export a run:

```bash
python3 scripts/benchmark.py export --run-id <RUN_ID> --out results
```

2) Serve the leaderboard:

```bash
python3 scripts/benchmark.py serve --dir results/leaderboard --port 8080
```

3) Open in browser:
- `http://localhost:8080`

Then:
- click table rows to compare
- toggle theme
- test filter + “show compared only”
- resize browser window for responsiveness

