"""Scoring rules for the MCQ benchmark.

Rules (intentionally penal so models can't sandbag with random guesses):

    correct answer   -> +1
    blank / no answer -> 0
    wrong answer     -> -10

Category aggregation maps each QID prefix (``C/E/M/A/N/X``) to a named
category column on the ``aggregates`` table.
"""

from typing import Dict, Optional, Tuple

SCORE_CORRECT = 1
SCORE_NO_ANSWER = 0
SCORE_WRONG = -10

CATEGORY_MAP = {
    "C": "chemistry",
    "E": "emotions",
    "M": "math",
    "A": "reasoning3d",
    "N": "no_knowledge",
    "X": "contradiction",
}


def score_answers(answer_key: Dict[str, str], model_answers: Dict[str, Optional[str]]) -> Tuple[Dict[str, int], Dict[str, int]]:
    per_q: Dict[str, int] = {}
    per_cat = {v: 0 for v in CATEGORY_MAP.values()}

    for qid, correct in answer_key.items():
        given = model_answers.get(qid)
        if given is None:
            s = SCORE_NO_ANSWER
        elif given.upper() == correct.upper():
            s = SCORE_CORRECT
        else:
            s = SCORE_WRONG

        per_q[qid] = s
        per_cat[CATEGORY_MAP[qid[0]]] += s

    return per_q, per_cat
