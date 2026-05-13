"""Project-wide default constants.

Currently just the default SQLite path so both the CLI and the FastAPI web
app resolve the same DB without duplicating string literals.
"""

import os


def default_db_path(base_dir: str) -> str:
    return os.path.join(base_dir, "db", "benchmark.db")

