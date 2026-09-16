# 数据库迁移

这里存放可追踪的数据库迁移版本。当前步骤已创建认证基础迁移 `001_auth.sql`、班级迁移 `002_classes.sql`、作业迁移 `003_assignments.sql`、提交迁移 `004_submissions.sql`、人工批改迁移 `005_grading.sql` 和 AI 任务迁移 `006_ai_grade_tasks.sql`；业务实体和约束见 [技术方案](../docs/技术方案.md)。

在 PostgreSQL 中按顺序显式执行：`psql "$DATABASE_URL" -f migrations/001_auth.sql`、`psql "$DATABASE_URL" -f migrations/002_classes.sql`、`psql "$DATABASE_URL" -f migrations/003_assignments.sql`、`psql "$DATABASE_URL" -f migrations/004_submissions.sql`、`psql "$DATABASE_URL" -f migrations/005_grading.sql`、`psql "$DATABASE_URL" -f migrations/006_ai_grade_tasks.sql`。迁移必须能够从空库建立当前步骤所需表；应用启动不自动修改数据库。`002_classes.sql` 为教师班级、班级码和学生成员关系建立唯一性与权限所需索引，`003_assignments.sql` 为作业和题目定义建立状态、题型和简答题字段约束，`004_submissions.sql` 为学生草稿和不可变提交快照建立版本、状态和唯一性约束，`005_grading.sql` 为人工批改记录和逐题反馈建立确认状态、版本和唯一性约束，`006_ai_grade_tasks.sql` 为异步 AI 批改任务建立持久化状态、版本和运行中唯一性约束。
