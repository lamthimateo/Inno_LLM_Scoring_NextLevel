import os


def default_db_path(base_dir: str) -> str:
    return os.path.join(base_dir, "db", "benchmark.db")

