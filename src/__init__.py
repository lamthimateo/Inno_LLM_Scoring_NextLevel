"""LLM Arena — web-first benchmark runner.

Top-level subpackages:

- ``benchmark``  — importing, prompting, validation, scoring pipeline, run orchestration, export
- ``adapters``   — provider-specific LLM clients (OpenAI + OpenRouter implemented; Anthropic / Google stubs)
- ``evaluator``  — strict MCQ output parser + scoring rules
- ``storage``    — SQLAlchemy ORM + engine/session helpers (Postgres in prod, SQLite for tests/dev)
- ``auth``       — user accounts, login sessions, password reset
- ``web``        — FastAPI app, HTML routes, Jinja2 templating, static leaderboard renderer

See ``ARCHITECTURE.md`` at repo root for the full data-flow diagram.
"""
