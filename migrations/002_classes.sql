-- P0 class and membership baseline. Run after 001_auth.sql.
CREATE TABLE IF NOT EXISTS classes (
    id VARCHAR(36) PRIMARY KEY,
    teacher_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    subject VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_classes_teacher_id ON classes (teacher_id);
CREATE INDEX IF NOT EXISTS ix_classes_status ON classes (status);

CREATE TABLE IF NOT EXISTS class_join_codes (
    id VARCHAR(36) PRIMARY KEY,
    class_id VARCHAR(36) NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    code_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    max_uses INTEGER NOT NULL CHECK (max_uses > 0),
    used_count INTEGER NOT NULL DEFAULT 0 CHECK (used_count >= 0),
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (used_count <= max_uses)
);

CREATE INDEX IF NOT EXISTS ix_class_join_codes_active
    ON class_join_codes (class_id, expires_at);

CREATE TABLE IF NOT EXISTS class_memberships (
    id VARCHAR(36) PRIMARY KEY,
    student_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id VARCHAR(36) NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_class_membership_student_class UNIQUE (student_id, class_id)
);

CREATE INDEX IF NOT EXISTS ix_class_memberships_student_id ON class_memberships (student_id);
CREATE INDEX IF NOT EXISTS ix_class_memberships_class_id ON class_memberships (class_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_class_membership_student
    ON class_memberships (student_id) WHERE status = 'active';

