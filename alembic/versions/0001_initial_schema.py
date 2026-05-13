"""Initial schema for v0.2.0 (GUI rewrite).

Creates every table from the ORM metadata in one shot. This is a common
pattern for the *first* migration on a greenfield project: subsequent
migrations should be auto-generated with ``alembic revision --autogenerate``
and produce explicit ``op.create_table`` / ``op.alter_column`` calls.

Revision ID: 0001
Revises: <none>
Create Date: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from src.storage.models import Base


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
