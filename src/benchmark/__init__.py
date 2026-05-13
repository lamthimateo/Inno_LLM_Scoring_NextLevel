"""Benchmark orchestration package.

Modules:

- ``importing``  — parse answer-key text files + persist into ``question_sets`` and ``questions``
- ``workflow``   — review state transitions (draft / in_review / approved / locked)
- ``prompting``  — build the strict ``QID: LETTER`` prompt sent to models
- ``pipeline``   — persistence helpers for one model run (raw output + answers + aggregate)
- ``exporting``  — write CSV + static leaderboard assets

The CLI was removed in v0.2.0. All flows are driven from the web UI under
:mod:`src.web`.
"""
