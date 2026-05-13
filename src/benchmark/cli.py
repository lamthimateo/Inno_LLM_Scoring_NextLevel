#!/usr/bin/env python3
"""Benchmark CLI.

Wires every subcommand exposed by the project:

    init-db | import-questions | submit-review | approve | lock
    build-prompt | run-file | run-openai | export | serve

Each subcommand is a thin adapter over a focused module under
``src/benchmark/`` so the CLI stays simple and the underlying functions stay
unit-testable. ``scripts/benchmark.py`` is a backwards-compatible wrapper
that forwards to :func:`main` here.
"""

import argparse
import json
import os

from src.benchmark.constants import default_db_path
from src.benchmark.exporting import export_results as export_results_impl
from src.benchmark.importing import import_questions as import_questions_impl
from src.benchmark.pipeline import load_answer_key, store_answers_and_aggregates, store_model_run
from src.benchmark.prompting import build_prompt_text
from src.runner.api_runner import run_openai_models
from src.runner.file_runner import load_model_outputs
from src.storage.db import connect, init_db, utc_now_iso


def submit_review(conn, *, set_id: str, reviewer: str) -> None:
    now = utc_now_iso()
    cur = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (set_id,)).fetchone()
    if not cur:
        raise SystemExit(f"Unknown set_id: {set_id}")
    if cur["status"] != "draft":
        raise SystemExit(f"Set must be in draft to submit review. Current: {cur['status']}")

    conn.execute(
        "UPDATE question_sets SET status='in_review', reviewer=?, updated_at=? WHERE set_id=?",
        (reviewer, now, set_id),
    )


def approve(conn, *, set_id: str, reviewer: str) -> None:
    now = utc_now_iso()
    row = conn.execute("SELECT status, reviewer FROM question_sets WHERE set_id=?", (set_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown set_id: {set_id}")
    if row["status"] != "in_review":
        raise SystemExit(f"Set must be in_review to approve. Current: {row['status']}")
    if row["reviewer"] != reviewer:
        raise SystemExit(f"Only assigned reviewer '{row['reviewer']}' can approve.")

    conn.execute("UPDATE question_sets SET status='approved', updated_at=? WHERE set_id=?", (now, set_id))


def lock_set(conn, *, set_id: str) -> None:
    now = utc_now_iso()
    row = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (set_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown set_id: {set_id}")
    if row["status"] != "approved":
        raise SystemExit(f"Set must be approved to lock. Current: {row['status']}")

    conn.execute("UPDATE question_sets SET status='locked', updated_at=? WHERE set_id=?", (now, set_id))


def run_file(conn, *, set_id: str, run_id: str, model_outputs: str, prompt_policy: str, notes: str) -> None:
    now = utc_now_iso()
    row = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (set_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown set_id: {set_id}")
    if row["status"] not in ("approved", "locked"):
        raise SystemExit("Set must be approved/locked to run.")

    conn.execute(
        "INSERT OR REPLACE INTO runs(run_id,set_id,created_at,prompt_policy,notes) VALUES(?,?,?,?,?)",
        (run_id, set_id, now, prompt_policy, notes or ""),
    )

    answer_key = load_answer_key(conn, set_id)
    models = load_model_outputs(model_outputs)
    if not models:
        raise SystemExit(f"No .txt files found in {model_outputs}")

    for model_id, raw_text in models.items():
        model_run_id = store_model_run(
            conn,
            run_id=run_id,
            model_id=model_id,
            source="file",
            raw_text=raw_text,
            meta=None,
            created_at=now,
        )
        store_answers_and_aggregates(conn, model_run_id=model_run_id, answer_key=answer_key, raw_text=raw_text)


def run_openai(
    conn,
    *,
    set_id: str,
    run_id: str,
    models_csv: str,
    temperature: float,
    max_output_tokens: int,
    timeout_s: float,
    max_retries: int,
    prompt_policy: str,
    notes: str,
) -> None:
    now = utc_now_iso()
    row = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (set_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown set_id: {set_id}")
    if row["status"] not in ("approved", "locked"):
        raise SystemExit("Set must be approved/locked to run.")

    prompt = build_prompt_text(conn, set_id)
    conn.execute(
        "INSERT OR REPLACE INTO runs(run_id,set_id,created_at,prompt_policy,notes) VALUES(?,?,?,?,?)",
        (run_id, set_id, now, prompt_policy, notes or ""),
    )

    answer_key = load_answer_key(conn, set_id)
    models = [m.strip() for m in models_csv.split(",") if m.strip()]
    if not models:
        raise SystemExit("--models must be a comma-separated list, e.g. gpt-4.1,gpt-4.1-mini")

    for m in models:
        meta = None
        try:
            r = run_openai_models(
                prompt,
                [m],
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_s=timeout_s,
                max_retries=max_retries,
            )[0]
            model_id = r.model_id
            raw_text = r.raw_text
            meta = r.meta
        except Exception as e:
            model_id = f"openai:{m}"
            raw_text = f"API_ERROR: {e.__class__.__name__}: {str(e)}"
            meta = {"provider": "openai", "model": m, "error": {"type": e.__class__.__name__, "message": str(e)}}

        model_run_id = store_model_run(
            conn,
            run_id=run_id,
            model_id=model_id,
            source="api",
            raw_text=raw_text,
            meta=meta,
            created_at=now,
        )
        store_answers_and_aggregates(conn, model_run_id=model_run_id, answer_key=answer_key, raw_text=raw_text)


def serve_dir(dir_path: str, port: int) -> None:
    import http.server
    import socketserver

    os.chdir(dir_path)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving {dir_path} at http://localhost:{port}")
        httpd.serve_forever()


def main(argv=None) -> None:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_default = default_db_path(os.path.dirname(base_dir))

    p = argparse.ArgumentParser(prog="benchmark")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-db")
    s.add_argument("--db", default=db_default)

    s = sub.add_parser("import-questions")
    s.add_argument("--db", default=db_default)
    s.add_argument("--source", required=True)
    s.add_argument("--set-id", required=True)
    s.add_argument("--author", required=True)

    s = sub.add_parser("submit-review")
    s.add_argument("--db", default=db_default)
    s.add_argument("--set-id", required=True)
    s.add_argument("--reviewer", required=True)

    s = sub.add_parser("approve")
    s.add_argument("--db", default=db_default)
    s.add_argument("--set-id", required=True)
    s.add_argument("--reviewer", required=True)

    s = sub.add_parser("lock")
    s.add_argument("--db", default=db_default)
    s.add_argument("--set-id", required=True)

    s = sub.add_parser("build-prompt")
    s.add_argument("--db", default=db_default)
    s.add_argument("--set-id", required=True)
    s.add_argument("--out", required=True)

    s = sub.add_parser("run-file")
    s.add_argument("--db", default=db_default)
    s.add_argument("--set-id", required=True)
    s.add_argument("--model-outputs", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--prompt-policy", default="strict_format_v1")
    s.add_argument("--notes", default="")

    s = sub.add_parser("run-openai")
    s.add_argument("--db", default=db_default)
    s.add_argument("--set-id", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--models", required=True)
    s.add_argument("--temperature", type=float, default=0.0)
    s.add_argument("--max-output-tokens", type=int, default=2048)
    s.add_argument("--timeout-s", type=float, default=120.0)
    s.add_argument("--max-retries", type=int, default=3)
    s.add_argument("--prompt-policy", default="strict_format_v1")
    s.add_argument("--notes", default="")

    s = sub.add_parser("export")
    s.add_argument("--db", default=db_default)
    s.add_argument("--run-id", required=True)
    s.add_argument("--out", required=True)

    s = sub.add_parser("serve")
    s.add_argument("--dir", required=True)
    s.add_argument("--port", type=int, default=8080)

    args = p.parse_args(argv)

    if args.cmd == "init-db":
        init_db(args.db)
        print(f"Initialized DB at {args.db}")
        return

    # Serving is purely static and should not require opening the DB.
    if args.cmd == "serve":
        serve_dir(args.dir, args.port)
        return

    conn = connect(args.db)
    try:
        if args.cmd == "import-questions":
            import_questions_impl(conn, source=args.source, set_id=args.set_id, author=args.author)
            conn.commit()
            print(f"Imported questions into set '{args.set_id}' (draft).")
            return

        if args.cmd == "submit-review":
            submit_review(conn, set_id=args.set_id, reviewer=args.reviewer)
            conn.commit()
            print(f"Set '{args.set_id}' submitted for review to '{args.reviewer}'.")
            return

        if args.cmd == "approve":
            approve(conn, set_id=args.set_id, reviewer=args.reviewer)
            conn.commit()
            print(f"Set '{args.set_id}' approved by '{args.reviewer}'.")
            return

        if args.cmd == "lock":
            lock_set(conn, set_id=args.set_id)
            conn.commit()
            print(f"Set '{args.set_id}' locked.")
            return

        if args.cmd == "build-prompt":
            out = build_prompt_text(conn, args.set_id)
            os.makedirs(os.path.dirname(args.out), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"Wrote prompt to {args.out}")
            return

        if args.cmd == "run-file":
            run_file(
                conn,
                set_id=args.set_id,
                run_id=args.run_id,
                model_outputs=args.model_outputs,
                prompt_policy=args.prompt_policy,
                notes=args.notes,
            )
            conn.commit()
            return

        if args.cmd == "run-openai":
            run_openai(
                conn,
                set_id=args.set_id,
                run_id=args.run_id,
                models_csv=args.models,
                temperature=args.temperature,
                max_output_tokens=args.max_output_tokens,
                timeout_s=args.timeout_s,
                max_retries=args.max_retries,
                prompt_policy=args.prompt_policy,
                notes=args.notes,
            )
            conn.commit()
            print(f"Stored OpenAI API run '{args.run_id}'.")
            return

        if args.cmd == "export":
            export_results_impl(conn, run_id=args.run_id, out_dir=args.out)
            print(f"Wrote: {os.path.join(args.out, 'benchmark_results.csv')}")
            print(f"Wrote: {os.path.join(args.out, 'leaderboard', 'index.html')}")
            return

    finally:
        conn.close()


if __name__ == "__main__":
    main()

