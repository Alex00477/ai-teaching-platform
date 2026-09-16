from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    account_status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RegistrationCode(Base):
    __tablename__ = "registration_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    subject: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClassJoinCode(Base):
    __tablename__ = "class_join_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClassMembership(Base):
    __tablename__ = "class_memberships"
    __table_args__ = (
        UniqueConstraint("student_id", "class_id", name="uq_class_membership_student_class"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        Index("ix_assignments_teacher_status", "teacher_id", "status"),
        Index("ix_assignments_class_status", "class_id", "status"),
        CheckConstraint("status IN ('draft', 'published')", name="ck_assignment_status"),
        CheckConstraint("version > 0", name="ck_assignment_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(String(64))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssignmentQuestion(Base):
    __tablename__ = "assignment_questions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "position", name="uq_assignment_question_position"),
        Index("ix_assignment_questions_assignment", "assignment_id", "position"),
        CheckConstraint("position > 0", name="ck_assignment_question_position_positive"),
        CheckConstraint(
            "question_type IN ('choice', 'fill', 'short')",
            name="ck_assignment_question_type",
        ),
        CheckConstraint(
            "question_type <> 'short' OR (max_score IS NOT NULL AND max_score > 0 AND rubric IS NOT NULL AND length(trim(rubric)) > 0)",
            name="ck_short_question_fields",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rubric: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnswerDraft(Base):
    __tablename__ = "answer_drafts"
    __table_args__ = (
        UniqueConstraint("student_id", "assignment_id", name="uq_answer_draft_student_assignment"),
        CheckConstraint("assignment_version > 0", name="ck_answer_draft_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    assignment_version: Mapped[int] = mapped_column(Integer)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("student_id", "assignment_id", name="uq_submission_student_assignment"),
        CheckConstraint("assignment_version > 0", name="ck_submission_version_positive"),
        CheckConstraint(
            "status IN ('submitted', 'grading', 'pending_review', 'graded', 'failed')",
            name="ck_submission_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    assignment_version: Mapped[int] = mapped_column(Integer)
    answers: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="submitted", index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GradingRecord(Base):
    __tablename__ = "grading_records"
    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_grading_record_submission"),
        CheckConstraint("assignment_version > 0", name="ck_grading_record_version_positive"),
        CheckConstraint("status IN ('draft', 'confirmed')", name="ck_grading_record_status"),
        CheckConstraint("total_score >= 0", name="ck_grading_record_total_nonnegative"),
        CheckConstraint("max_score > 0", name="ck_grading_record_max_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assignment_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    max_score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GradingItem(Base):
    __tablename__ = "grading_items"
    __table_args__ = (
        UniqueConstraint("grading_record_id", "question_id", name="uq_grading_item_record_question"),
        CheckConstraint("score >= 0", name="ck_grading_item_score_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    grading_record_id: Mapped[str] = mapped_column(ForeignKey("grading_records.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("assignment_questions.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AITask(Base):
    __tablename__ = "ai_grade_tasks"
    __table_args__ = (
        CheckConstraint("assignment_version > 0", name="ck_ai_grade_task_version_positive"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'pending_review', 'confirmed', 'failed')",
            name="ck_ai_grade_task_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assignment_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "uq_ai_grade_task_running_submission",
    AITask.submission_id,
    unique=True,
    postgresql_where=AITask.status.in_(("pending", "processing", "pending_review")),
    sqlite_where=AITask.status.in_(("pending", "processing", "pending_review")),
)


Index("ix_class_join_codes_active", ClassJoinCode.class_id, ClassJoinCode.expires_at)
Index(
    "uq_active_class_membership_student",
    ClassMembership.student_id,
    unique=True,
    postgresql_where=ClassMembership.status == "active",
    sqlite_where=ClassMembership.status == "active",
)


Index("ix_registration_codes_active", RegistrationCode.role, RegistrationCode.expires_at)
Index("ix_recovery_codes_active", RecoveryCode.user_id, RecoveryCode.expires_at)
Index("ix_user_sessions_active", UserSession.user_id, UserSession.expires_at)
