"""add tutorial attempt tracking

Revision ID: 0002_tutorial_attempts
Revises: 0001_phase1_schema
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_tutorial_attempts"
down_revision = "0001_phase1_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("tutorial_attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("students", "tutorial_attempts")