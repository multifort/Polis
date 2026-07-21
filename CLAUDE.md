# CLAUDE.md — Polis 工程操作契约

> 本文件是 Polis 仓库的**最高优先级工作约定**，对人类贡献者与 AI 助手同等生效。
> 它不重复设计内容（见 `docs/`），只规定**怎么干活、什么红线不能碰**。
> 设计/约束的唯一来源：`docs/design/`、`docs/constraints/`、`docs/decisions/`。

## 0. 一句话
Polis = 多 Agent 协同平台：给定意图，开出一家自治「城邦(Org)」，由角色化 Agent 规划→路由→执行，
全程受治理、可审计、成本透明（理念见 [docs/design/0a-Polis理念与隐喻.md](docs/design/0a-Polis理念与隐喻.md)）。

## 1. 技术栈（权威速查，细节见 docs/design/01）
- 后端：Python 3.12 + FastAPI + SQLAlchemy 2.0(async) + Pydantic v2 + Alembic
- 编排：Temporal（Python SDK）｜模型网关：LiteLLM｜工具：MCP｜向量：PostgreSQL + pgvector
- 可观测/评估：Langfuse｜护栏：Guardrails-AI｜前端：React/Next.js（后续）
- 包管理：后端 uv（锁定）/ 前端 pnpm（锁定）｜部署：docker-compose →（V3）K8s
- **不在 MVP 引入**：Kafka / Elasticsearch / Milvus / 多余 Redis / K8s / OPA / 微服务拆分

## 2. 仓库结构
```text
backend/   FastAPI 服务（modular monolith：org/planner/runtime/memory/model/observability/api）
frontend/  Web（React/Next.js）
infra/     docker-compose / 迁移 / 部署
docs/      design(设计) · constraints(约束) · decisions(ADR) · plan(研发计划) · legacy(归档)
```

## 3. 工程操作模型（强制）
**分支**：trunk-based；`main` 受保护、禁直推；短分支 `feat/… | fix/… | chore/…`，快速合并。
**提交**：Conventional Commits（`feat: / fix: / docs: / refactor: / test: / chore:`），一次一件事，说清 what+why；
AI 协作提交带 `Co-Authored-By`。
**任务驱动 (DoR)**：开发前满足就绪定义——目标/验收明确、关联设计章节、依赖就绪、无重大未决、1~3 天可完成（否则拆分）。
**完成定义 (DoD)**：验收满足 + 有测试且通过 + 过本地门禁(lint/type/secret/coverage) + 文档/ADR/OpenAPI 同步 +
无遗留 TODO/skip + 经评审合并 + org_id 隔离/安全无回归。**禁止"先合后补测试/文档"。**
**质量门禁**（初期 pre-commit/pre-push 本地强制，引 CI 后迁流水线）：
`ruff` + `mypy` + `pytest`(覆盖率核心模块 ≥70%) + `gitleaks` + `bandit` + `pip-audit`；绕过 `--no-verify` 需评审说明。
**本地集成测试授权**（用户于 2026-07-21 明确授权）：AI 助手可为本仓库的开发与测试申请提升权限，使用
`127.0.0.1`、`::1` 本地 socket、操作系统分配的临时端口，并与本项目启动的 PostgreSQL、Temporal、MinIO、
MCP test server 等本地测试服务通信。测试应优先在沙箱内执行；若因 `PermissionError`、socket bind/connect
被拒绝或本地 test server 无法启动而失败，应使用相同命令申请提升权限后重跑，并分别记录“沙箱环境失败”与
“提升权限后的真实结果”。不得将沙箱限制误报为代码失败，也不得仅因该限制跳过、屏蔽或降级测试。

本地 MinIO 是共享常驻基础设施：S3 API 固定使用 `localhost:9000`，`localhost:9001` 仅为 Web 控制台。
集成测试必须复用该实例与稳定测试桶，通过唯一对象前缀隔离并在用例结束后清理对象；不得为每次测试再启动
MinIO/Testcontainers 容器或占用新的 MinIO 端口。

该授权仅覆盖回环地址和本项目的本地测试服务，不包含外网访问、依赖下载、生产环境操作、无关本地服务或数据
访问，也不自动授权监听 `0.0.0.0`。所有提升权限操作仍须遵循执行环境的审批机制；测试完成后应停止临时服务
并释放端口，且不得以任何方式绕过沙箱或权限控制。
**迁移**：只走 Alembic，向后兼容（先加后删、可回滚），与代码同 PR。
**API 契约**：以 FastAPI 生成的 **OpenAPI 为准**，前端类型从它生成。
**ADR**：架构/选型/重大权衡写 `docs/decisions/NNNN-*.md`（见 `0000-adr-template.md`），架构变更 PR 必须含/引 ADR。
**验证门 (F3)**：到 V1 验收门用数据决定是否进 V2（DAG 可用率≥70% / 路由命中≥75% / 人审通过≥50% / 成本时延在预算），
未达**回炉调 Planner/路由/记忆，而不是加模块**。

## 4. ★ 安全与 AI 使用红线（不可逾越）
1. **删除 / 系统安全类操作严格禁止自动执行**（`rm -rf`、`sudo`、强推、硬重置、`dd/mkfs/shutdown` 等）——
   见 `.claude/settings.json` 已配 deny/ask。需要时由人显式执行。
2. **绝不臆造**工具/命令/构建/测试结果；命令是否成功**必须看真实输出**，不确定就重跑、看日志。
3. **改/读/搜文件用专用工具**（Read/Grep/Edit），不靠记忆臆改；不用 bash 文本工具拼改源码。
4. **密钥永不入** 代码/仓库/日志/上下文/记忆/Trace；配置走环境变量，`.env` 不入库，`.env.example` 给模板。
5. **多租户隔离**：所有业务表带 `org_id`，应用层统一注入过滤；写隔离回归测试（A/B 互不可见）。
6. **AI 生成的代码/skill/角色/计划默认不可信**：须人读懂、过门禁、有测试、经人审才生效。
7. BYO 凭证**任务级短时句柄、用完即焚**，永不落盘/日志/上下文（见 docs/design/06）。

## 5. 文档与命令
- 设计导航：[docs/README.md](docs/README.md)｜色彩/视觉唯一来源：[docs/constraints/10a-色彩规范.md](docs/constraints/10a-色彩规范.md)
- 研发计划与任务：[docs/plan/研发计划.md](docs/plan/研发计划.md) ｜ [docs/plan/研发任务清单.md](docs/plan/研发任务清单.md)
- **续接/当前进度**：新 session 先读 [docs/续接指南.md](docs/续接指南.md)（里程碑进度、怎么起服务、环境踩坑、M3 下一步任务）。
- 技术债：走捷径/留 TODO/延后工程实践时，登记 [docs/tech-debt.md](docs/tech-debt.md)（属 DoD 的一部分）；偿还后留痕。
- 便捷命令：`/adr`（起草 ADR）、`/task`（建任务含 DoR）、`/review`（评审清单）——见 `.claude/commands/`
- 构建/测试命令将在 M1 落地后补到此处（届时以 `backend/README` 与 `Makefile` 为准）。

## 6. 术语一致（A14）
Org=城邦/虚拟公司、Agent=智能体/公民、Role=角色/公职、Plan=计划、Skill=技能、Approval=审批、
Capability=能力（受控词表）。全端一致，错误文案给「原因+下一步」。详见 0a 理念文档的术语表。
