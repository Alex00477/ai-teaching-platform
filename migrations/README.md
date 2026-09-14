# 数据库迁移

这里存放可追踪的数据库迁移版本。当前步骤已创建认证基础迁移 `001_auth.sql`、班级迁移 `002_classes.sql` 和作业迁移 `003_assignments.sql`；业务实体和约束见 [技术方案](../docs/技术方案.md)。

在 PostgreSQL 中按顺序显式执行：`psql "$DATABASE_URL" -f migrations/001_auth.sql`、`psql "$DATABASE_URL" -f migrations/002_classes.sql`、`psql "$DATABASE_URL" -f migrations/003_assignments.sql`。迁移必须能够从空库建立当前步骤所需表；应用启动不自动修改数据库。`002_classes.sql` 为教师班级、班级码和学生成员关系建立唯一性与权限所需索引，`003_assignments.sql` 为作业和题目定义建立状态、题型和简答题字段约束。
