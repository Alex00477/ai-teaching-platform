-- P0 answer drafts and immutable submissions. Run after 003_assignments.sql.
CREATE TABLE IF NOT EXISTS answer_drafts (
    id VARCHAR(36) PRIMARY KEY,
    student_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assignment_id VARCHAR(36) NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    assignment_version INTEGER NOT NULL CHECK (assignment_version > 0),
    answers JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_answer_draft_student_assignment UNIQUE (student_id, assignment_id)
);

CREATE INDEX IF NOT EXISTS ix_answer_drafts_student_assignment
    ON answer_drafts (student_id, assignment_id);

CREATE TABLE IF NOT EXISTS submissions (
    id VARCHAR(36) PRIMARY KEY,
    student_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assignment_id VARCHAR(36) NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    assignment_version INTEGER NOT NULL CHECK (assignment_version > 0),
    answers JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'submitted'
        CHECK (status IN ('submitted', 'grading', 'pending_review', 'graded', 'failed')),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_submission_student_assignment UNIQUE (student_id, assignment_id)
);

CREATE INDEX IF NOT EXISTS ix_submissions_assignment_status
    ON submissions (assignment_id, status);
CREATE INDEX IF NOT EXISTS ix_submissions_student
    ON submissions (student_id, submitted_at);
