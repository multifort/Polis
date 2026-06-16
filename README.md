# Polis

> 一个多 Agent 协同平台：给定意图，系统开出一家「虚拟公司(Org)」——
> 内有按**角色(Role)**组织、可版本化的 **Agent**，由 **Planner** 规划、按**能力路由**分派、
> 在受治理（审批 / 护栏 / 凭证隔离）的运行时里协同完成目标。

**命名**：`Polis`（城邦）。每个 Org 即一个自治的「城邦」：有公民(Agent)、有角色分工、有治理（审批/护栏）。
（工作期曾用代号 “AgentOS”，现已弃用；活动文档已统一为 Polis，仅 `docs/legacy/` 归档保留旧字样作为历史记录。）

## 这是什么 / 不是什么
- **是**：编排层 + 运行时 + 治理 + 记忆/检索 + 可观测，**复用优先**地把成熟开源件组装成平台。
- **不是**：又一个从零自研的编排/向量/网关轮子。MVP 阶段直接用 Temporal / LiteLLM / MCP / PostgreSQL+pgvector / Langfuse。

## 关键决策（详见 `docs/decisions/`）
- 与既有 `hermes-test` **完全独立**，不复用其前端（[ADR-0001](docs/decisions/0001-independent-system.md)）。
- 后端 **Python 3.12 + FastAPI**（[ADR-0002](docs/decisions/0002-backend-python-fastapi.md)）。
- 项目命名 **Polis**（[ADR-0003](docs/decisions/0003-project-name-polis.md)）。
- **复用优先**技术栈：Temporal / LiteLLM / MCP / pgvector / Langfuse（[ADR-0004](docs/decisions/0004-reuse-first-stack.md)）。

## 目录结构
```text
polis/
├─ backend/        FastAPI 服务（M1 起搭建）
├─ frontend/       Web（React/Next.js，后续）
├─ infra/          docker-compose / 部署（后续）
└─ docs/
   ├─ design/      系统设计 00–08（总览/选型/组织角色/规划路由/运行时/记忆/模型凭证/数据部署/IP）
   ├─ constraints/ 工程化约束（UI/前端/后端/移动端/工程化/过程 + 10a 色彩规范）
   ├─ decisions/   ADR 架构决策记录
   └─ legacy/      早期讨论稿（已被 design/ 取代，留作历史）
```

## 现状
设计与规范已就绪（见 `docs/`）。代码尚未开始——下一步 **M1**：FastAPI 脚手架 + pre-commit 门禁 + PostgreSQL/pgvector + Alembic。

## 文档导航
从 [docs/README.md](docs/README.md) 进入。色彩/视觉以 [10a 色彩规范](docs/constraints/10a-色彩规范.md) 为唯一来源。
