import json


def build_prompt_text(conn, set_id: str) -> str:
    row = conn.execute("SELECT status FROM question_sets WHERE set_id=?", (set_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown set_id: {set_id}")
    if row["status"] not in ("approved", "locked"):
        raise SystemExit("Set must be approved/locked to build prompt.")

    questions = conn.execute(
        "SELECT qid, category, prompt, choices_json FROM questions WHERE set_id=? ORDER BY qid",
        (set_id,),
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

