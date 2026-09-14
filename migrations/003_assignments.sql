-- P0 assignments and question definitions. Run after 002_classes.sql.
CREATE TABLE IF NOT EXISTS assignments (
    id VARCHAR(36) PRIMARY KEY,
    class_id VARCHAR(36) NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    teacher_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    subject VARCHAR(64) NOT NULL,
    due_at TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_assignments_teacher_status ON assignments (teacher_id, status);
CREATE INDEX IF NOT EXISTS ix_assignments_class_status ON assignments (class_id, status);

CREATE TABLE IF NOT EXISTS assignment_questions (
    id VARCHAR(36) PRIMARY KEY,
    assignment_id VARCHAR(36) NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    question_type VARCHAR(16) NOT NULL CHECK (question_type IN ('choice', 'fill', 'short')),
    prompt TEXT NOT NULL,
    options JSONB,
    correct_answer TEXT,
    max_score INTEGER CHECK (max_score IS NULL OR max_score > 0),
    rubric TEXT,
    CONSTRAINT uq_assignment_question_position UNIQUE (assignment_id, position),
    CONSTRAINT ck_short_question_fields CHECK (
        question_type <> 'short' OR (max_score IS NOT NULL AND rubric IS NOT NULL AND length(trim(rubric)) > 0)
    )
);

CREATE INDEX IF NOT EXISTS ix_assignment_questions_assignment
    ON assignment_questions (assignment_id, position);
