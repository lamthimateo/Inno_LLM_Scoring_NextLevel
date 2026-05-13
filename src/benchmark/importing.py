"""Import benchmark question files into SQLite.

Reads every ``*.txt`` under ``imports/answer_key/`` and populates the
``question_sets`` and ``questions`` tables. The expected file format is::

    C1. <prompt text>
    A. <choice A>
    B. <choice B>
    ...
    E. <choice E>
    Correct answer: B

QID prefix maps to category:

    C = chemistry        E = emotions        M = math
    A = reasoning3d      N = no_knowledge    X = contradiction

A question is only inserted if it has at least 5 choices. Locked sets cannot
be re-imported (use a new ``--set-id`` such as ``benchmark_v2`` instead).
"""

import json
import re
from pathlib import Path

from src.storage.db import utc_now_iso


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


def import_questions(conn, *, source: str, set_id: str, author: str) -> None:
    now = utc_now_iso()
    existing = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (set_id,)).fetchone()
    if existing and existing["status"] == "locked":
        raise SystemExit(
            f"Set '{set_id}' is locked. Use a new --set-id (e.g. {set_id}_v2) or start from a fresh DB."
        )

    conn.execute(
        """INSERT INTO question_sets(set_id,status,author,reviewer,created_at,updated_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(set_id) DO UPDATE SET
             status='draft',
             author=excluded.author,
             reviewer=NULL,
             updated_at=excluded.updated_at""",
        (set_id, "draft", author, None, now, now),
    )

    answer_key = parse_answer_key_from_txt_folder(source)
    if not answer_key:
        raise SystemExit(f"No answers parsed from {source}. Make sure files contain 'Correct answer: X'.")

    qid_re = re.compile(r"^\s*([CEMANX]\d+)\.\s*(.*)$")
    choice_re = re.compile(r"^\s*([A-E])\.\s*(.*)$")

    for fp in sorted(Path(source).glob("*.txt")):
        lines = fp.read_text(encoding="utf-8").splitlines()
        i = 0
        while i < len(lines):
            m_q = qid_re.match(lines[i])
            if not m_q:
                i += 1
                continue
            qid = m_q.group(1)
            prompt = m_q.group(2).strip()

            choices = []
            j = i + 1
            while j < len(lines):
                m_c = choice_re.match(lines[j])
                if m_c:
                    choices.append({"label": m_c.group(1), "text": m_c.group(2).strip()})
                    j += 1
                    continue
                if qid_re.match(lines[j]):
                    break
                j += 1

            if len(choices) >= 5:
                correct = answer_key.get(qid)
                category = _category_from_qid(qid)
                conn.execute(
                    """INSERT OR REPLACE INTO questions(qid,set_id,category,prompt,choices_json,correct_answer,scoring_rule)
                       VALUES(?,?,?,?,?,?,?)""",
                    (qid, set_id, category, prompt, json.dumps(choices, ensure_ascii=False), correct, "mcq_v1"),
                )

            i = j

    conn.execute("UPDATE question_sets SET updated_at=? WHERE set_id=?", (now, set_id))

