"""Inno LLM Scoring — Next Level.

A mini LM-Arena-style benchmark runner. Top-level subpackages:

- ``benchmark``  — CLI entrypoint, importing, prompting, scoring pipeline, export
- ``adapters``   — provider-specific LLM clients (OpenAI implemented, others stubs)
- ``runner``     — file-based and API-based execution drivers
- ``evaluator``  — MCQ output parser + scoring rules
- ``storage``    — SQLite schema + connection helpers
- ``web``        — FastAPI dashboard + static leaderboard renderer

See ``ARCHITECTURE.md`` at repo root for the full data-flow diagram.
"""
