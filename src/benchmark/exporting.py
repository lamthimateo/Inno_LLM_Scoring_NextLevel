from pathlib import Path

from src.web.leaderboard import write_leaderboard_assets


def export_results(conn, *, run_id: str, out_dir: str) -> None:
    rows = conn.execute(
        """SELECT mr.model_id,
                  a.total_score as total,
                  a.chemistry, a.emotions, a.math, a.reasoning3d, a.no_knowledge, a.contradiction,
                  a.correct_count as correct, a.wrong_count as wrong, a.blank_count as blank,
                  a.format_violations
           FROM model_runs mr
           JOIN aggregates a ON a.model_run_id = mr.model_run_id
           WHERE mr.run_id=?
           ORDER BY a.total_score DESC""",
        (run_id,),
    ).fetchall()

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    csv_path = out / "benchmark_results.csv"
    import csv as _csv

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(
            [
                "model_id",
                "total",
                "chemistry",
                "emotions",
                "math",
                "reasoning3d",
                "no_knowledge",
                "contradiction",
                "correct",
                "wrong",
                "blank",
                "format_violations",
            ]
        )
        for r in rows:
            w.writerow([r[c] for c in r.keys()])

    data = [dict(r) for r in rows]
    lb_dir = out / "leaderboard"
    write_leaderboard_assets(data, str(lb_dir))

