"""Benchmark orchestration package.

Modules:

- ``cli``        — argparse entrypoint exposing every subcommand
- ``importing``  — parse answer-key text files into SQLite ``questions``
- ``prompting``  — build the strict ``QID: LETTER`` prompt sent to models
- ``pipeline``   — persistence helpers (raw output, parsed answers, aggregates)
- ``exporting``  — write CSV + static leaderboard assets
- ``constants``  — shared defaults (e.g. DB path)
"""
