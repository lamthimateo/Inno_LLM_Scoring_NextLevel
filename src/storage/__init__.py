"""SQLAlchemy persistence layer.

- ``models``  — every table as a SQLAlchemy ORM class
- ``db``      — engine, sessionmaker, FastAPI dependency, context manager

Production uses Postgres (configured via ``DATABASE_URL``). Tests override
``DATABASE_URL`` to point at SQLite in-memory and call :func:`db.reset_engine`.
"""
