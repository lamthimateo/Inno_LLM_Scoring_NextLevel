import unittest

from src.evaluator.parser_mcq import parse_model_output
from src.evaluator.scoring import score_answers, SCORE_CORRECT, SCORE_NO_ANSWER, SCORE_WRONG


class TestParserMCQ(unittest.TestCase):
    def test_parses_basic_pairs_and_blanks(self):
        text = "C1: A\nC2:\nM10: e\nX3: B\n"
        answers, violations = parse_model_output(text)
        self.assertEqual(answers["C1"], "A")
        self.assertIsNone(answers["C2"])
        # parser only accepts A-E uppercase; lowercase is treated as blank/unparsed
        self.assertIsNone(answers.get("M10"))
        self.assertEqual(answers["X3"], "B")
        # line with "M10: e" contains a QID but doesn't match strict pattern -> violation
        self.assertGreaterEqual(violations, 1)

    def test_last_one_wins_for_duplicate_qid(self):
        text = "C1: A\nC1: B\n"
        answers, _ = parse_model_output(text)
        self.assertEqual(answers["C1"], "B")

    def test_counts_format_violations_when_qid_present_but_bad_pattern(self):
        text = "C1: maybe B\nC2: A\nnoise C3 ???\n"
        _, violations = parse_model_output(text)
        # heuristic: line "noise C3 ???" should count; "C1: maybe B" currently doesn't
        self.assertGreaterEqual(violations, 1)


class TestScoring(unittest.TestCase):
    def test_scores_correct_wrong_blank(self):
        answer_key = {"C1": "A", "E2": "B", "M3": "C"}
        model_answers = {"C1": "A", "E2": "C", "M3": None}
        per_q, per_cat = score_answers(answer_key, model_answers)
        self.assertEqual(per_q["C1"], SCORE_CORRECT)
        self.assertEqual(per_q["E2"], SCORE_WRONG)
        self.assertEqual(per_q["M3"], SCORE_NO_ANSWER)
        self.assertEqual(per_cat["chemistry"], SCORE_CORRECT)
        self.assertEqual(per_cat["emotions"], SCORE_WRONG)
        self.assertEqual(per_cat["math"], SCORE_NO_ANSWER)


if __name__ == "__main__":
    unittest.main()

