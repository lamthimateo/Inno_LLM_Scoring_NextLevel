#!/usr/bin/env python3
"""
Benchmark content QA / review report generator.

Scans `imports/answer_key/*.txt` and produces a markdown report highlighting:
- question counts per category
- missing/duplicate QIDs
- missing choices (A-E)
- missing "Correct answer: X"
- formatting anomalies that may break the importer

Run:
  python3 scripts/benchmark_review.py --in imports/answer_key --out results/benchmark_review_report.md
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


QID_RE = re.compile(r"^\s*([CEMANX]\d+)\.\s*(.*)$")
CHOICE_RE = re.compile(r"^\s*([A-E])\.\s*(.*)$")
ANSWER_RE = re.compile(r"^\s*(Correct answer|Correct|ANSWER)\s*:\s*([A-E])\s*$", re.IGNORECASE)


@dataclass
class Question:
    qid: str
    prompt: str
    choices: Dict[str, str]
    correct: Optional[str]
    source_file: str


def parse_questions_from_file(fp: Path) -> Tuple[List[Question], List[str]]:
    lines = fp.read_text(encoding="utf-8").splitlines()
    i = 0
    questions: List[Question] = []
    warnings: List[str] = []

    while i < len(lines):
        m_q = QID_RE.match(lines[i])
        if not m_q:
            i += 1
            continue

        qid = m_q.group(1)
        prompt = m_q.group(2).strip()
        choices: Dict[str, str] = {}
        correct: Optional[str] = None

        j = i + 1
        while j < len(lines):
            if QID_RE.match(lines[j]):
                break
            m_c = CHOICE_RE.match(lines[j])
            if m_c:
                choices[m_c.group(1)] = m_c.group(2).strip()
                j += 1
                continue
            m_a = ANSWER_RE.match(lines[j])
            if m_a:
                correct = m_a.group(2).upper()
                j += 1
                continue
            j += 1

        if not prompt:
            warnings.append(f"{fp.name}: {qid} has empty prompt")

        questions.append(
            Question(
                qid=qid,
                prompt=prompt,
                choices=choices,
                correct=correct,
                source_file=fp.name,
            )
        )
        i = j

    return questions, warnings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    out_path = Path(args.out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(in_dir.glob("*.txt"))
    if not files:
        raise SystemExit(f"No .txt files found under {in_dir}")

    all_q: List[Question] = []
    warnings: List[str] = []
    for fp in files:
        qs, ws = parse_questions_from_file(fp)
        all_q.extend(qs)
        warnings.extend(ws)

    by_prefix: Dict[str, List[Question]] = {k: [] for k in ["C", "E", "M", "A", "N", "X"]}
    seen: Dict[str, Question] = {}
    duplicates: List[str] = []
    missing_answers: List[str] = []
    missing_choices: List[str] = []
    short_choices: List[str] = []

    for q in all_q:
        if q.qid in seen:
            duplicates.append(f"{q.qid} ({seen[q.qid].source_file}, {q.source_file})")
        else:
            seen[q.qid] = q

        by_prefix[q.qid[0]].append(q)

        if q.correct is None:
            missing_answers.append(f"{q.qid} ({q.source_file})")

        missing = [c for c in ["A", "B", "C", "D", "E"] if c not in q.choices]
        if missing:
            missing_choices.append(f"{q.qid} missing {','.join(missing)} ({q.source_file})")

        for k, v in q.choices.items():
            if len(v.strip()) <= 1:
                short_choices.append(f"{q.qid} choice {k} too short ({q.source_file})")

    def md_list(items: List[str], limit: int = 30) -> str:
        if not items:
            return "- (none)\n"
        shown = items[:limit]
        tail = "" if len(items) <= limit else f"\n- ... and {len(items)-limit} more"
        return "\n".join([f"- {x}" for x in shown]) + tail + "\n"

    total = len(all_q)
    counts = {k: len(v) for k, v in by_prefix.items()}

    report = []
    report.append("# Benchmark review report\n")
    report.append(f"Input folder: `{in_dir}`\n")
    report.append(f"Files scanned: {len(files)}\n")
    report.append(f"Total questions parsed: **{total}**\n")
    report.append("\n## Category counts (by QID prefix)\n")
    for k in ["C", "E", "M", "A", "N", "X"]:
        report.append(f"- **{k}**: {counts[k]}\n")

    report.append("\n## Content QA findings\n")
    report.append(f"- **Duplicate QIDs**: {len(duplicates)}\n")
    report.append(md_list(duplicates))
    report.append(f"- **Missing correct answers**: {len(missing_answers)}\n")
    report.append(md_list(missing_answers))
    report.append(f"- **Missing choices (A–E)**: {len(missing_choices)}\n")
    report.append(md_list(missing_choices))
    report.append(f"- **Suspiciously short choices**: {len(short_choices)}\n")
    report.append(md_list(short_choices))

    report.append("\n## Parser/importer warnings\n")
    report.append(md_list(warnings))

    report.append("\n## Notes / criteria suggestions\n")
    report.append(
        "- Keep each question in the format `QID. <prompt>` followed by `A.`..`E.` choices and a `Correct answer: X` line.\n"
        "- Avoid duplicate QIDs across category files.\n"
        "- Ensure every question has exactly 5 choices (A–E) and one correct answer.\n"
    )

    out_path.write_text("".join(report), encoding="utf-8")
    print(f"Wrote report: {out_path}")


if __name__ == "__main__":
    main()

