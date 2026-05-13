"""Parsing and scoring of model outputs.

- ``parser_mcq``  — extract ``QID: LETTER`` pairs + count format violations
- ``scoring``     — apply the scoring rule (+1 correct, 0 blank, -10 wrong)
                    and aggregate by category prefix (C/E/M/A/N/X).
"""
