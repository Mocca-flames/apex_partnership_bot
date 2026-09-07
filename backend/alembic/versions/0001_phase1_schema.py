"""create Phase 1 core tables

Revision ID: 0001_phase1_schema
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_phase1_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", sa.String(100), unique=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("surname", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("phone", sa.String(30), nullable=False),
        sa.Column("university", sa.String(255)),
        sa.Column("field", sa.String(255)),
        sa.Column("study_year", sa.Integer),
        sa.Column("whatsapp_number", sa.String(30), unique=True),
        sa.Column("auth_passcode", sa.String(50), unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="UNVERIFIED"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_students_whatsapp_number", "students", ["whatsapp_number"])
    op.create_table(
        "transporters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("fleet_owner_phone", sa.String(30), nullable=False),
        sa.Column("truck_count", sa.Integer),
        sa.Column("truck_type", sa.String(50)),
        sa.Column("status", sa.String(30), nullable=False, server_default="NEW_LEAD"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_transporters_fleet_owner_phone", "transporters", ["fleet_owner_phone"])
    op.create_table(
        "apex_staff",
        sa.Column("phone_number", sa.String(30), primary_key=True),
        sa.Column("staff_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor_phone", sa.String(30)),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("apex_staff")
    op.drop_index("ix_transporters_fleet_owner_phone", table_name="transporters")
    op.drop_table("transporters")
    op.drop_index("ix_students_whatsapp_number", table_name="students")
    op.drop_table("students")
