#!/usr/bin/env python3
import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

# Ensure imports like `from src....` work regardless of where the script is launched from.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.storage.db import init_db, connect, utc_now_iso
from src.runner.file_runner import load_model_outputs
from src.runner.api_runner import run_openai_models
from src.evaluator.parser_mcq import parse_model_output
from src.evaluator.scoring import score_answers
from src.web.leaderboard import write_leaderboard_assets

DB_PATH_DEFAULT = os.path.join(BASE_DIR, "db", "benchmark.db")


def _category_from_qid(qid: str) -> str:
    return {
        "C": "chemistry",
        "E": "emotions",
        "M": "math",
        "A": "reasoning3d",
        "N": "no_knowledge",
        "X": "contradiction",
    }[qid[0]]


def parse_answer_key_from_txt_folder(folder: str) -> dict:
    """Parse answer key from your category txt files (qid line + 'Correct answer: X' line)."""
    answer_key = {}
    qid_re = re.compile(r"^\s*([CEMANX]\d+)\.")
    ans_re = re.compile(r"^\s*(Correct answer|Correct|ANSWER)\s*:\s*([A-E])\s*$", re.IGNORECASE)

    for fp in sorted(Path(folder).glob("*.txt")):
        current = None
        for line in fp.read_text(encoding="utf-8").splitlines():
            m_q = qid_re.match(line)
            if m_q:
                current = m_q.group(1)
                continue
            m_a = ans_re.match(line)
            if m_a and current:
                answer_key[current] = m_a.group(2).upper()
                current = None

    return answer_key


def import_questions(args):
    conn = connect(args.db)
    now = utc_now_iso()
    try:
        # Upsert question set
        conn.execute(
            """INSERT INTO question_sets(set_id,status,author,reviewer,created_at,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(set_id) DO UPDATE SET author=excluded.author, updated_at=excluded.updated_at""",
            (args.set_id, "draft", args.author, None, now, now)
        )

        # Parse answer key files
        answer_key = parse_answer_key_from_txt_folder(args.source)
        if not answer_key:
            raise SystemExit(f"No answers parsed from {args.source}. Make sure files contain 'Correct answer: X'.")

        # Parse questions into DB by reading full text blocks (lightweight: store prompt+choices as plain text)
        # We keep prompt as the full question line (after 'C1.') and choices as JSON list.
        qid_re = re.compile(r"^\s*([CEMANX]\d+)\.\s*(.*)$")
        choice_re = re.compile(r"^\s*([A-E])\.\s*(.*)$")

        for fp in sorted(Path(args.source).glob("*.txt")):
            lines = fp.read_text(encoding="utf-8").splitlines()
            i = 0
            while i < len(lines):
                m_q = qid_re.match(lines[i])
                if not m_q:
                    i += 1
                    continue
                qid = m_q.group(1)
                prompt = m_q.group(2).strip()

                # gather A-E
                choices = []
                j = i + 1
                while j < len(lines):
                    m_c = choice_re.match(lines[j])
                    if m_c:
                        choices.append({"label": m_c.group(1), "text": m_c.group(2).strip()})
                        j += 1
                        continue
                    # stop when next question starts
                    if qid_re.match(lines[j]):
                        break
                    j += 1

                if len(choices) >= 5:
                    correct = answer_key.get(qid)
                    category = _category_from_qid(qid)
                    conn.execute(
                        """INSERT OR REPLACE INTO questions(qid,set_id,category,prompt,choices_json,correct_answer,scoring_rule)
                           VALUES(?,?,?,?,?,?,?)""",
                        (qid, args.set_id, category, prompt, json.dumps(choices, ensure_ascii=False), correct, "mcq_v1")
                    )

                i = j

        conn.execute("UPDATE question_sets SET updated_at=? WHERE set_id=?", (now, args.set_id))
        conn.commit()
        print(f"Imported questions into set '{args.set_id}' (draft).")
    finally:
        conn.close()


def submit_review(args):
    conn = connect(args.db)
    now = utc_now_iso()
    try:
        cur = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (args.set_id,)).fetchone()
        if not cur:
            raise SystemExit(f"Unknown set_id: {args.set_id}")
        if cur["status"] != "draft":
            raise SystemExit(f"Set must be in draft to submit review. Current: {cur['status']}")

        conn.execute(
            "UPDATE question_sets SET status='in_review', reviewer=?, updated_at=? WHERE set_id=?",
            (args.reviewer, now, args.set_id)
        )
        conn.commit()
        print(f"Set '{args.set_id}' submitted for review to '{args.reviewer}'.")
    finally:
        conn.close()


def approve(args):
    conn = connect(args.db)
    now = utc_now_iso()
    try:
        row = conn.execute("SELECT status, reviewer FROM question_sets WHERE set_id=?", (args.set_id,)).fetchone()
        if not row:
            raise SystemExit(f"Unknown set_id: {args.set_id}")
        if row["status"] != "in_review":
            raise SystemExit(f"Set must be in_review to approve. Current: {row['status']}")
        if row["reviewer"] != args.reviewer:
            raise SystemExit(f"Only assigned reviewer '{row['reviewer']}' can approve.")

        conn.execute(
            "UPDATE question_sets SET status='approved', updated_at=? WHERE set_id=?",
            (now, args.set_id)
        )
        conn.commit()
        print(f"Set '{args.set_id}' approved by '{args.reviewer}'.")
    finally:
        conn.close()


def lock_set(args):
    conn = connect(args.db)
    now = utc_now_iso()
    try:
        row = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (args.set_id,)).fetchone()
        if not row:
            raise SystemExit(f"Unknown set_id: {args.set_id}")
        if row["status"] != "approved":
            raise SystemExit(f"Set must be approved to lock. Current: {row['status']}")

        conn.execute("UPDATE question_sets SET status='locked', updated_at=? WHERE set_id=?", (now, args.set_id))
        conn.commit()
        print(f"Set '{args.set_id}' locked.")
    finally:
        conn.close()


def build_prompt(args):
    conn = connect(args.db)
    try:
        out = _build_prompt_text(conn, args.set_id)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"Wrote prompt to {args.out}")
    finally:
        conn.close()


def _build_prompt_text(conn, set_id: str) -> str:
    row = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (set_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown set_id: {set_id}")
    if row["status"] not in ("approved", "locked"):
        raise SystemExit("Set must be approved/locked to build prompt.")

    questions = conn.execute(
        "SELECT qid, category, prompt, choices_json FROM questions WHERE set_id=? ORDER BY qid",
        (set_id,)
    ).fetchall()

    header = (
        "You will answer a multiple-choice benchmark.\n\n"
        "RULES (STRICT):\n"
        "1) Output ONLY answers in the format: QID: LETTER\n"
        "2) One answer per line.\n"
        "3) Allowed letters: A, B, C, D, E only.\n"
        "4) No explanations, no extra text, no markdown.\n"
        "5) If you are unsure, leave it blank after the colon (example: C7: ).\n"
        "6) Answer every question ID shown.\n\n"
        "ANSWER TEMPLATE (fill letters):\n"
    )

    template_txt = "\n".join([f"{q['qid']}: " for q in questions])

    body = ["\n\nQUESTIONS:\n"]
    for q in questions:
        choices = json.loads(q["choices_json"])
        body.append(f"{q['qid']}. {q['prompt']}")
        for c in choices:
            body.append(f"{c['label']}. {c['text']}")
        body.append("")

    return header + template_txt + "\n" + "\n".join(body)


def _store_model_answers_and_aggregates(conn, *, model_run_id: int, answer_key: dict, raw_text: str):
    parsed, format_violations = parse_model_output(raw_text)
    per_q, per_cat = score_answers(answer_key, parsed)

    correct = wrong = blank = 0
    for qid, s in per_q.items():
        given = parsed.get(qid)
        if given is None:
            blank += 1
        elif s == 1:
            correct += 1
        else:
            wrong += 1

        conn.execute(
            "INSERT OR REPLACE INTO answers(model_run_id,qid,given_answer,correct_answer,score) VALUES(?,?,?,?,?)",
            (model_run_id, qid, given, answer_key.get(qid), s)
        )

    total = sum(per_q.values())
    conn.execute(
        """INSERT OR REPLACE INTO aggregates(
               model_run_id,total_score,chemistry,emotions,math,reasoning3d,no_knowledge,contradiction,
               correct_count,wrong_count,blank_count,format_violations
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            model_run_id, total,
            per_cat["chemistry"], per_cat["emotions"], per_cat["math"],
            per_cat["reasoning3d"], per_cat["no_knowledge"], per_cat["contradiction"],
            correct, wrong, blank, format_violations
        )
    )


def run_file(args):
    conn = connect(args.db)
    now = utc_now_iso()
    try:
        row = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (args.set_id,)).fetchone()
        if not row:
            raise SystemExit(f"Unknown set_id: {args.set_id}")
        if row["status"] not in ("approved", "locked"):
            raise SystemExit("Set must be approved/locked to run.")

        # Create run
        conn.execute(
            "INSERT OR REPLACE INTO runs(run_id,set_id,created_at,prompt_policy,notes) VALUES(?,?,?,?,?)",
            (args.run_id, args.set_id, now, args.prompt_policy, args.notes or "")
        )

        # Answer key
        answer_key = {
            r["qid"]: r["correct_answer"]
            for r in conn.execute("SELECT qid, correct_answer FROM questions WHERE set_id=?", (args.set_id,))
        }

        # Load model outputs
        models = load_model_outputs(args.model_outputs)
        if not models:
            raise SystemExit(f"No .txt files found in {args.model_outputs}")

        for model_id, raw_text in models.items():
            # store raw model run
            conn.execute(
                "INSERT OR REPLACE INTO model_runs(run_id,model_id,source,raw_text,meta_json,created_at) VALUES(?,?,?,?,?,?)",
                (args.run_id, model_id, "file", raw_text, None, now)
            )
            model_run_id = conn.execute(
                "SELECT model_run_id FROM model_runs WHERE run_id=? AND model_id=?",
                (args.run_id, model_id)
            ).fetchone()["model_run_id"]
            _store_model_answers_and_aggregates(conn, model_run_id=model_run_id, answer_key=answer_key, raw_text=raw_text)

        conn.commit()
        print(f"Stored run '{args.run_id}' with {len(models)} models.")
    finally:
        conn.close()


def run_openai(args):
    conn = connect(args.db)
    now = utc_now_iso()
    try:
        row = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (args.set_id,)).fetchone()
        if not row:
            raise SystemExit(f"Unknown set_id: {args.set_id}")
        if row["status"] not in ("approved", "locked"):
            raise SystemExit("Set must be approved/locked to run.")

        prompt = _build_prompt_text(conn, args.set_id)

        conn.execute(
            "INSERT OR REPLACE INTO runs(run_id,set_id,created_at,prompt_policy,notes) VALUES(?,?,?,?,?)",
            (args.run_id, args.set_id, now, args.prompt_policy, args.notes or "")
        )

        answer_key = {
            r["qid"]: r["correct_answer"]
            for r in conn.execute("SELECT qid, correct_answer FROM questions WHERE set_id=?", (args.set_id,))
        }

        models = [m.strip() for m in args.models.split(",") if m.strip()]
        if not models:
            raise SystemExit("--models must be a comma-separated list, e.g. gpt-4.1,gpt-4.1-mini")

        # Call models one-by-one so a single failure doesn't kill the whole run.
        stored = 0
        for m in models:
            meta_json = None
            try:
                results = run_openai_models(
                    prompt,
                    [m],
                    temperature=args.temperature,
                    max_output_tokens=args.max_output_tokens,
                    timeout_s=args.timeout_s,
                    max_retries=args.max_retries,
                )
                r = results[0]
                raw_text = r.raw_text
                model_id = r.model_id
                meta_json = json.dumps(r.meta, ensure_ascii=False)
            except Exception as e:
                model_id = f"openai:{m}"
                raw_text = f"API_ERROR: {e.__class__.__name__}: {str(e)}"
                meta_json = json.dumps(
                    {"provider": "openai", "model": m, "error": {"type": e.__class__.__name__, "message": str(e)}},
                    ensure_ascii=False,
                )

            conn.execute(
                "INSERT OR REPLACE INTO model_runs(run_id,model_id,source,raw_text,meta_json,created_at) VALUES(?,?,?,?,?,?)",
                (args.run_id, model_id, "api", raw_text, meta_json, now)
            )
            model_run_id = conn.execute(
                "SELECT model_run_id FROM model_runs WHERE run_id=? AND model_id=?",
                (args.run_id, model_id)
            ).fetchone()["model_run_id"]
            _store_model_answers_and_aggregates(conn, model_run_id=model_run_id, answer_key=answer_key, raw_text=raw_text)
            stored += 1

        conn.commit()
        print(f"Stored OpenAI API run '{args.run_id}' with {stored} model(s).")
    finally:
        conn.close()


def export_results(args):
    conn = connect(args.db)
    try:
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
            (args.run_id,)
        ).fetchall()

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)

        # CSV
        csv_path = out_dir / "benchmark_results.csv"
        import csv as _csv
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["model_id","total","chemistry","emotions","math","reasoning3d","no_knowledge","contradiction","correct","wrong","blank","format_violations"])
            for r in rows:
                w.writerow([r[c] for c in r.keys()])

        # leaderboard assets
        data = [dict(r) for r in rows]
        lb_dir = out_dir / "leaderboard"
        write_leaderboard_assets(data, str(lb_dir))

        print(f"Wrote: {csv_path}")
        print(f"Wrote: {lb_dir / 'index.html'}")
    finally:
        conn.close()


def serve_dir(args):
    import http.server
    import socketserver
    os.chdir(args.dir)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", args.port), handler) as httpd:
        print(f"Serving {args.dir} at http://localhost:{args.port}")
        httpd.serve_forever()


def main():
    p = argparse.ArgumentParser(prog="benchmark")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-db")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.set_defaults(func=lambda a: (init_db(a.db), print(f"Initialized DB at {a.db}")))

    s = sub.add_parser("import-questions")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.add_argument("--source", required=True)
    s.add_argument("--set-id", required=True)
    s.add_argument("--author", required=True)
    s.set_defaults(func=import_questions)

    s = sub.add_parser("submit-review")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.add_argument("--set-id", required=True)
    s.add_argument("--reviewer", required=True)
    s.set_defaults(func=submit_review)

    s = sub.add_parser("approve")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.add_argument("--set-id", required=True)
    s.add_argument("--reviewer", required=True)
    s.set_defaults(func=approve)

    s = sub.add_parser("lock")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.add_argument("--set-id", required=True)
    s.set_defaults(func=lock_set)

    s = sub.add_parser("build-prompt")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.add_argument("--set-id", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=build_prompt)

    s = sub.add_parser("run-file")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.add_argument("--set-id", required=True)
    s.add_argument("--model-outputs", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--prompt-policy", default="strict_format_v1")
    s.add_argument("--notes", default="")
    s.set_defaults(func=run_file)

    s = sub.add_parser("run-openai")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.add_argument("--set-id", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--models", required=True, help="Comma-separated OpenAI model list (e.g. gpt-4.1,gpt-4.1-mini)")
    s.add_argument("--temperature", type=float, default=0.0)
    s.add_argument("--max-output-tokens", type=int, default=2048)
    s.add_argument("--timeout-s", type=float, default=120.0)
    s.add_argument("--max-retries", type=int, default=3)
    s.add_argument("--prompt-policy", default="strict_format_v1")
    s.add_argument("--notes", default="")
    s.set_defaults(func=run_openai)

    s = sub.add_parser("export")
    s.add_argument("--db", default=DB_PATH_DEFAULT)
    s.add_argument("--run-id", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=export_results)

    s = sub.add_parser("serve")
    s.add_argument("--dir", required=True)
    s.add_argument("--port", type=int, default=8080)
    s.set_defaults(func=serve_dir)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
