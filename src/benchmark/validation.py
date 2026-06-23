"""Static-content validation for parsed benchmark questions.

These helpers were originally inlined in ``scripts/benchmark_review.py`` to
build a markdown QA report. The web import-preview HTMX endpoint
(``POST /questions/preview``) needs the same checks at request time, so
the logic is factored out here.

The functions accept the :class:`~src.benchmark.importing.ParsedQuestion`
dataclass produced by ``parse_questions_from_text`` /
``parse_questions_from_folder`` — no DB session required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from src.benchmark.importing import ParsedQuestion


REQUIRED_CHOICE_LABELS: tuple[str, ...] = ("A", "B", "C", "D", "E")

# Choices with stripped length <= this threshold are flagged as suspiciously
# short (e.g. single letters / numbers that are likely typos in the source).
SHORT_CHOICE_THRESHOLD = 1


@dataclass
class ValidationFinding:
    """Single validation check result rendered in the preview fragment."""

    level: str  # "pass" | "warn" | "fail"
    title: str
    detail: str = ""
    qids: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Structured outcome of running all static checks over a list of questions."""

    total: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)
    missing_answers: list[str] = field(default_factory=list)
    missing_choices: list[str] = field(default_factory=list)
    short_choices: list[str] = field(default_factory=list)
    empty_prompts: list[str] = field(default_factory=list)
    findings: list[ValidationFinding] = field(default_factory=list)

    @property
    def level(self) -> str:
        """Overall severity: ``fail`` if any blocker, ``warn`` if soft, else ``pass``."""

        if self.duplicates or self.missing_choices or self.empty_prompts:
            return "fail"
        if self.missing_answers:
            return "warn"
        return "pass"

    @property
    def is_clean(self) -> bool:
        return self.level == "pass"


def _q_label(q: ParsedQuestion) -> str:
    return f"{q.qid} ({q.source_file})"


def validate_questions(questions: Iterable[ParsedQuestion]) -> ValidationReport:
    """Run every static check used by the import preview / review script.

    The same set of checks lived in ``scripts/benchmark_review.py``; behaviour
    is preserved so the markdown report and the live preview stay in sync.
    """

    qs: Sequence[ParsedQuestion] = list(questions)
    report = ValidationReport(total=len(qs))

    seen: dict[str, ParsedQuestion] = {}
    for q in qs:
        report.by_category[q.category] = report.by_category.get(q.category, 0) + 1

        if q.qid in seen:
            report.duplicates.append(
                f"{q.qid} ({seen[q.qid].source_file}, {q.source_file})"
            )
        else:
            seen[q.qid] = q

        if q.correct_answer is None:
            report.missing_answers.append(_q_label(q))

        present = {c.get("label") for c in q.choices}
        missing = [c for c in REQUIRED_CHOICE_LABELS if c not in present]
        if missing:
            report.missing_choices.append(
                f"{q.qid} missing {','.join(missing)} ({q.source_file})"
            )

        if not q.prompt.strip():
            report.empty_prompts.append(_q_label(q))

        for c in q.choices:
            label = c.get("label", "?")
            text = (c.get("text") or "").strip()
            if len(text) <= SHORT_CHOICE_THRESHOLD:
                report.short_choices.append(
                    f"{q.qid} choice {label} too short ({q.source_file})"
                )

    report.findings = _build_findings(report)
    return report


def _build_findings(report: ValidationReport) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []

    def add(level: str, title: str, items: list[str]) -> None:
        if not items:
            return
        findings.append(
            ValidationFinding(
                level=level,
                title=title,
                detail=f"{len(items)} found",
                qids=items[:15],
            )
        )

    add("fail", "Duplicate QIDs", report.duplicates)
    add("fail", "Missing choices (A–E)", report.missing_choices)
    add("fail", "Empty prompts", report.empty_prompts)
    add("warn", "Missing correct answer", report.missing_answers)
    if not findings:
        findings.append(
            ValidationFinding(
                level="pass",
                title="All checks passed",
                detail=f"{report.total} questions look clean.",
            )
        )

    return findings
