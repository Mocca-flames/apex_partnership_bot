"""add Phase 4 lead intake sessions and phone uniqueness

Revision ID: 0003_phase4_lead_intake
Revises: 0002_tutorial_attempts
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_phase4_lead_intake"
down_revision = "0002_tutorial_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_submission_sessions",
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("step", sa.String(30), nullable=False, server_default="PHONE"),
        sa.Column("fleet_owner_phone", sa.String(30)),
        sa.Column("company_name", sa.String(255)),
        sa.Column("truck_count", sa.Integer),
        sa.Column("truck_type", sa.String(50)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_transporters_fleet_owner_phone",
        "transporters",
        ["fleet_owner_phone"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_transporters_fleet_owner_phone", table_name="transporters")
    op.drop_table("lead_submission_sessions")