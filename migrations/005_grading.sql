-- P0 manual grading records and per-question feedback. Run after 004_submissions.sql.
CREATE TABLE IF NOT EXISTS grading_records (
    id VARCHAR(36) PRIMARY KEY,
    submission_id VARCHAR(36) NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    teacher_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assignment_version INTEGER NOT NULL CHECK (assignment_version > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
    total_score INTEGER NOT NULL DEFAULT 0 CHECK (total_score >= 0),
    max_score INTEGER NOT NULL CHECK (max_score > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at TIMESTAMPTZ,
    CONSTRAINT uq_grading_record_submission UNIQUE (submission_id)
);

CREATE INDEX IF NOT EXISTS ix_grading_records_teacher_status
    ON grading_records (teacher_id, status);

CREATE TABLE IF NOT EXISTS grading_items (
    id VARCHAR(36) PRIMARY KEY,
    grading_record_id VARCHAR(36) NOT NULL REFERENCES grading_records(id) ON DELETE CASCADE,
    question_id VARCHAR(36) NOT NULL REFERENCES assignment_questions(id) ON DELETE CASCADE,
    score INTEGER NOT NULL DEFAULT 0 CHECK (score >= 0),
    feedback TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_grading_item_record_question UNIQUE (grading_record_id, question_id)
);

CREATE INDEX IF NOT EXISTS ix_grading_items_record
    ON grading_items (grading_record_id);
