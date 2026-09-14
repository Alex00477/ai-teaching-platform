# 数据库迁移

这里存放可追踪的数据库迁移版本。当前步骤已创建认证基础迁移 `001_auth.sql`；业务实体和约束见 [技术方案](../docs/技术方案.md)。

在 PostgreSQL 中显式执行：`psql "$DATABASE_URL" -f migrations/001_auth.sql`。迁移必须能够从空库建立当前步骤所需表；应用启动不自动修改数据库。
