# Polis · 虚拟智能企业平台

> **对用户的一句话**：一个目标，开出一家 **AI 虚拟公司**——角色化智能体替你规划、协作、交付，全程可控、可审计。
>
> 技术上：给定意图，系统开出一家「虚拟公司(Org)」；Org 内有按 **Role** 组织、可版本化的 **Agent**，由 **Planner** 出图、按能力路由分派，在受治理（审批 / 护栏 / 凭证隔离）的运行时里协同完成目标。

`Polis` 的产品定位是「虚拟智能企业平台」。品牌隐喻来自城邦：每个 Org 是一个自治组织，有公民（Agent）、角色分工（Role）、治理规则（审批/护栏）、记忆与资产沉淀。工作期曾用代号 `AgentOS`，现行文档与代码统一使用 `Polis`；历史讨论稿保留在 `docs/legacy/`。

## 这是什么 / 不是什么

- **是**：多 Agent 协同平台的编排层、运行时、治理层、记忆/检索、可观测与产品工作台。
- **是**：复用优先的工程实现，把 Temporal / LiteLLM / MCP / PostgreSQL+pgvector / Langfuse / MinIO 等成熟组件组合成可演进的平台。
- **不是**：从零自研编排、向量库、模型网关、可观测系统或工作流引擎。

## 当前状态

项目已经不是早期脚手架阶段。当前主线已完成 M0-M7、V2 生成内核/记忆/协同线，以及 C 阶段的一批产品化能力。后端主路径和前端工作台均已具备可运行形态。

已就绪的核心能力包括：

- 身份认证、刷新/登出、多 Org、成员与角色权限、RLS 多租户隔离。
- Org provision：按预设创建虚拟公司、角色、Agent 花名册。
- Planner：模板检索优先，未命中时可走 LLM 生成 DAG；结构/语义校验与有界自修复。
- Runtime：Temporal 编排、AgentRuntime、多轮工具调用、黑板、附件读取、质量门、返工与升级审批。
- Memory：任务黑板、组织记忆、向量检索、记忆晋升、衰减与治理 API。
- Model：LiteLLM 接入、DeepSeek chat、本地 TEI/bge embedding、模型目录、凭证信封加密。
- Observability：Langfuse 采集、自建运行观测页、token/成本统计、评估器、审批收件箱。
- Product：Next.js 工作台、工作列表/详情、任务多次运行、附件上传、结果导出、运营看板、花名册与设置页。

最新进度、环境提示和下一步优先级请以 [docs/续接指南.md](docs/续接指南.md) 为准；顶层 README 只作为项目入口。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Alembic, uv |
| 前端 | Next.js 14 App Router, React 18, TypeScript, pnpm |
| 编排 | Temporal Python SDK |
| 模型 | LiteLLM, DeepSeek, 本地 TEI embedding |
| 数据 | PostgreSQL, pgvector, Alembic migrations |
| 对象存储 | MinIO / S3 兼容 |
| 可观测 | Langfuse + Polis 自建观测 API/UI |
| 工具/技能 | MCP 抽象、Skill loader、内置工具与可扩展技能 |

## 目录结构

```text
polis/
├─ backend/        FastAPI modular monolith
│  ├─ src/polis/
│  │  ├─ api/      health/catalog 等聚合路由
│  │  ├─ core/     安全等基础能力
│  │  ├─ db/       session、RLS/org scoped 助手、ORM 基础
│  │  └─ modules/  org/planner/runtime/memory/model/observability/storage
│  ├─ migrations/  Alembic 迁移
│  └─ tests/       pytest 集成与单元测试
├─ frontend/       Next.js Web 工作台
│  ├─ app/         登录、工作台、Org 子页面
│  ├─ components/  应用壳与通用组件
│  └─ lib/         API client
├─ infra/          docker-compose 本地基础设施
└─ docs/           设计、约束、ADR、研发计划、技术债与续接指南
```

## 快速开始

后端、前端和基础设施分开启动。第一次启动前请复制环境变量模板并按本机情况填充密钥。

```bash
# 1. 基础设施：PostgreSQL/pgvector
cd infra
cp -n .env.example .env
docker compose up -d postgres

# 2. 后端
cd ../backend
cp -n .env.example .env
make install
make migrate
make seed
make dev

# 3. 前端
cd ../frontend
pnpm install
pnpm dev
```

常用地址：

- 后端 API：`http://localhost:8000`
- OpenAPI/Swagger：`http://localhost:8000/docs`
- 前端：`http://localhost:3000`

涉及真实任务执行时，还需要 Temporal worker、模型服务和按需基础设施：

```bash
# Temporal + UI
cd infra
docker compose --env-file .env up -d temporal temporal-ui

# Polis worker
cd ../backend
make worker

# 按需：MinIO / Langfuse / LiteLLM / text-embeddings
cd ../infra
docker compose --env-file .env up -d minio langfuse litellm text-embeddings
```

也可以用 compose profile 启动整栈容器：

```bash
cd infra
cp -n .env.example .env
docker compose --env-file .env --profile app up -d
```

更多环境细节、测试账号、DeepSeek/TEI/Langfuse 注意事项见 [docs/续接指南.md](docs/续接指南.md)。

## 常用命令

本地质量门禁：

```bash
uv tool install pre-commit
scripts/install-gitleaks.sh
pre-commit install -t pre-commit -t commit-msg -t pre-push
```

后端：

```bash
cd backend
make dev            # uvicorn 热重载服务，端口 8000
make worker         # Temporal worker
make migrate        # Alembic upgrade head
make seed           # 幂等 seed 能力/模型/预设/模板
make lint           # ruff check
make type           # mypy strict
make test           # pytest
make check          # lint + type + test
```

前端：

```bash
cd frontend
pnpm dev            # Next.js dev server
pnpm build          # 生产构建
pnpm start          # 启动生产构建
```

## 架构入口

- 应用组合根：[backend/src/polis/main.py](backend/src/polis/main.py)
- API 聚合：[backend/src/polis/api/router.py](backend/src/polis/api/router.py)
- 后端配置：[backend/src/polis/config.py](backend/src/polis/config.py)
- 前端 API client：[frontend/lib/api.ts](frontend/lib/api.ts)
- 本地基础设施：[infra/docker-compose.yml](infra/docker-compose.yml)

后端按 modular monolith 组织，常见分层是 `api -> service -> repository/domain`，模块边界集中在 `backend/src/polis/modules/`。组织级业务通过 `X-Org-Id`、成员校验和数据库 RLS 共同保证隔离。

## 关键决策

- 与既有 `hermes-test` 完全独立，不复用其前端：[ADR-0001](docs/decisions/0001-independent-system.md)
- 后端采用 Python 3.12 + FastAPI：[ADR-0002](docs/decisions/0002-backend-python-fastapi.md)
- 项目命名为 Polis：[ADR-0003](docs/decisions/0003-project-name-polis.md)
- 复用优先技术栈：Temporal / LiteLLM / MCP / pgvector / Langfuse：[ADR-0004](docs/decisions/0004-reuse-first-stack.md)
- 多租户采用逻辑隔离 + RLS 兜底：[ADR-0005](docs/decisions/0005-multi-tenancy-strategy.md)

## 文档导航

- [docs/续接指南.md](docs/续接指南.md)：当前进度、环境跑法、下一步优先级。
- [docs/README.md](docs/README.md)：完整文档索引。
- [docs/design/](docs/design/)：系统设计与数据模型。
- [docs/design/v2/](docs/design/v2/)：V2 生成内核、记忆、协同与产品形态设计。
- [docs/constraints/](docs/constraints/)：UI、前端、后端、移动端、工程化与过程约束。
- [docs/decisions/](docs/decisions/)：ADR 架构决策。
- [docs/plan/](docs/plan/)：研发计划与任务清单。
- [docs/tech-debt.md](docs/tech-debt.md)：技术债台账。

## 贡献约定

工程操作契约见 [CLAUDE.md](CLAUDE.md)。核心原则：

- 改动前读相关设计与约束，优先遵循现有模块边界和代码风格。
- 迁移只走 Alembic，密钥只走环境变量，`.env` 不入库。
- 多租户相关改动必须考虑 `org_id`、`X-Org-Id`、RLS 与隔离回归。
- 提交前至少按风险运行对应测试；较大改动应跑 `cd backend && make check` 等价门禁。
