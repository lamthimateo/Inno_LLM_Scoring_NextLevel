import os
import tempfile
import unittest

from src.storage.db import connect, init_db


class TestDbMigrations(unittest.TestCase):
    def test_connect_applies_meta_json_migration(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "benchmark.db")
            init_db(db_path)
            conn = connect(db_path)
            try:
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(model_runs)").fetchall()}
                self.assertIn("meta_json", cols)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

