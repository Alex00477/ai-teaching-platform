-- P0 asynchronous AI grading tasks. Run after 005_grading.sql.
CREATE TABLE IF NOT EXISTS ai_grade_tasks (
    id VARCHAR(36) PRIMARY KEY,
    submission_id VARCHAR(36) NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    teacher_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assignment_version INTEGER NOT NULL CHECK (assignment_version > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'pending_review', 'confirmed', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    result JSONB,
    error_code VARCHAR(64),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_ai_grade_tasks_status_created
    ON ai_grade_tasks (status, created_at);
CREATE INDEX IF NOT EXISTS ix_ai_grade_tasks_teacher_status
    ON ai_grade_tasks (teacher_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_grade_task_running_submission
    ON ai_grade_tasks (submission_id)
    WHERE status IN ('pending', 'processing', 'pending_review');
