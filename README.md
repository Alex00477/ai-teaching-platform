# AI 教学平台

## 项目简介

面向学生和教师的 AI 教学平台，P0 优先验证“班级—作业—批改—反馈”教学闭环。

## 当前状态

当前已建立可运行的前后端工程骨架，并完成认证基础模块；班级、作业、批改和讲义业务仍按步骤实现。原始需求保留在 [需求规约.md](需求规约.md)，已确认的产品和工程取舍保留在 [decisions/](decisions/)。

## 文档索引

- [需求规约](需求规约.md)：原始需求，以及已确认/待确认事项。
- [MVP 范围与优先级](docs/MVP范围与优先级.md)：P0/P1/P2 范围、顺序和发布门槛。
- [业务规则](docs/业务规则.md)：角色权限、状态、关键规则和必须处理的异常；开发时的业务规则唯一来源。
- [验收清单](docs/验收清单.md)：主流程和关键越权、重复提交、异步失败场景。
- [技术方案](docs/技术方案.md)：技术基线、数据模型、异步任务、部署和容量约束。
- [架构与产品决策记录](decisions/)：需要追溯的跨模块取舍。

## 如何启动

最小工程骨架已建立。首次启动前，请将 `.env.template` 复制为未提交的 `.env`，并替换 `SESSION_SECRET`；Worker 还需要服务端配置 `PH8_API_KEY`。

本地启动顺序：

1. `docker compose up -d postgres redis`
2. 在 `apps/api` 安装 Python 依赖：`pip install -e ".[dev]"`
3. 启动 API：`uvicorn teaching_platform.main:app --app-dir src --reload`
4. 启动 Worker（仅验证配置）：`python -m teaching_platform.worker --once`
5. 在 `apps/web` 安装并启动前端：`npm install && npm run dev`

当前 API 提供健康检查和 `/auth` 认证入口；Worker 只完成配置校验和轮询占位，班级、作业、批改和讲义业务迁移将在后续步骤实现。
