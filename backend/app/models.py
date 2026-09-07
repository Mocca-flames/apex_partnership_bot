from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    lead_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    first_name: Mapped[str] = mapped_column(String(100))
    surname: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str] = mapped_column(String(30))
    university: Mapped[str | None] = mapped_column(String(255))
    field: Mapped[str | None] = mapped_column(String(255))
    study_year: Mapped[int | None] = mapped_column(Integer)
    whatsapp_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    auth_passcode: Mapped[str | None] = mapped_column(String(50), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="UNVERIFIED", nullable=False)
    tutorial_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    transporters: Mapped[list["Transporter"]] = relationship(back_populates="student")


class Transporter(Base):
    __tablename__ = "transporters"
    __table_args__ = (Index("ix_transporters_fleet_owner_phone", "fleet_owner_phone"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    student_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("students.id", ondelete="RESTRICT"), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255))
    fleet_owner_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    truck_count: Mapped[int | None] = mapped_column(Integer)
    truck_type: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="NEW_LEAD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    student: Mapped[Student] = relationship(back_populates="transporters")


class LeadSubmissionSession(Base):
    __tablename__ = "lead_submission_sessions"

    student_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), primary_key=True
    )
    step: Mapped[str] = mapped_column(String(30), nullable=False, default="PHONE")
    fleet_owner_phone: Mapped[str | None] = mapped_column(String(30))
    company_name: Mapped[str | None] = mapped_column(String(255))
    truck_count: Mapped[int | None] = mapped_column(Integer)
    truck_type: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    student: Mapped[Student] = relationship()


class ApexStaff(Base):
    __tablename__ = "apex_staff"

    phone_number: Mapped[str] = mapped_column(String(30), primary_key=True)
    staff_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_phone: Mapped[str | None] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
