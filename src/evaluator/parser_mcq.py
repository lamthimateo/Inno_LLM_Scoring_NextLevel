import re
from typing import Dict, Optional, Tuple


QID_RE = re.compile(r"\b([CEMANX]\d+)\s*:\s*([A-E]?)\b")


def parse_model_output(text: str) -> Tuple[Dict[str, Optional[str]], int]:
    """Return (answers, format_violations).

    Extracts all 'QID: LETTER' pairs anywhere in text.
    If a QID appears multiple times, the last one wins.

    format_violations counts obvious junk patterns like 'C1: maybe B'.
    """
    answers: Dict[str, Optional[str]] = {}
    for qid, ans in QID_RE.findall(text):
        answers[qid] = ans if ans != "" else None

    # Simple format violation heuristic: lines containing QID but not matching strict pattern
    violations = 0
    for line in text.splitlines():
        if re.search(r"\b[CEMANX]\d+\b", line) and not QID_RE.search(line):
            violations += 1

    return answers, violations
