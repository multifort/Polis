# Polis 技术债台账

> 记录开发中有意/被迫做的妥协与延后项，便于后续回溯与偿还。
> **纪律**：每当为推进而走捷径、留 TODO、延后某项工程实践，在此登记一条（属 DoD 的一部分，见 `docs/constraints/15`）。
> 偿还后把状态改为 `closed` 并注明提交。严重度：High（须尽快）/ Med（择机）/ Low（可接受，留痕）。

## 台账

| ID | 标题 | 严重度 | 状态 | 偿还触发 |
|---|---|---|---|---|
| [TD-001](#td-001) | main 分支保护未启用 | Med | open | 引入第二贡献者 / V1 正式开发前 |
| [TD-002](#td-002) | CI workflow 模板已落，远程启用待 workflow scope | Med | 部分偿还 | 启用 main 保护 / 进 staging 前 |
| [TD-003](#td-003) | gitleaks 本地安装脚本与 CI 模板已补；远程启用待 workflow scope | Low | 部分偿还 | 远程启用 CI 后关闭 |
| [TD-004](#td-004) | 基础设施镜像用浮动 tag | Low-Med | **closed** | 已固定 litellm/langfuse，见偿还记录 |
| [TD-005](#td-005) | bandit/pip-audit 临时安装未锁版本 | Low | **closed** | 已锁入 dev 依赖，见偿还记录 |
| [TD-006](#td-006) | db 引擎模块级单例、无 readiness | Med | **closed** | 已补，见偿还记录 |
| [TD-007](#td-007) | 无 DB 集成测试(testcontainers) | Med | **closed** | 已补，见偿还记录 |
| [TD-008](#td-008) | 早期提交作者归属错误 | Low | accepted(won't-fix) | — |
| [TD-009](#td-009) | 应用本体未容器化 | Low | **closed** | 已补 Dockerfile + app profile 并完成镜像构建验证 |
| [TD-010](#td-010) | 运行时 RLS 未接线 | Med | **closed** | 已补（M2 T9.2），见偿还记录 |
| [TD-011](#td-011) | 审计仅覆盖 org 写操作（auth 事件未） | Med | **closed** | 登录失败审计已补（独立事务），见偿还记录 |
| [TD-012](#td-012) | 认证缺登出/刷新轮换/会话清理 | Med | **closed** | 已补，见偿还记录 |
| [TD-013](#td-013) | 安全配置生产前须收紧（JWT 默认密钥/边缘限流） | Med | **closed** | 已补生产 fail-closed、DB 共享限流、邮件投递与 compose 网关认证限流 |
| [TD-014](#td-014) | 前端 token 存 localStorage + 无静默刷新 | Low-Med | **closed** | 已改 httpOnly cookie + 静默刷新 |
| [TD-015](#td-015) | org 过滤 repo 基类未建 | Low | **closed** | 已提供 select_org_scoped 助手 |
| [TD-016](#td-016) | 权限矩阵未完整落地（成员邀请/移除/角色调整） | Low-Med | **closed** | 已补成员管理闭环 |
| [TD-017](#td-017) | 预设关键词匹配对中文弱（无分词/无语义） | Low | **closed** | provisioning 语义选预设已落，见偿还记录 |
| [TD-018](#td-018) | Temporal worker 沙箱 pydantic_core 延迟导入 UserWarning | Low | **closed** | 已消除，见偿还记录 |
| [TD-019](#td-019) | 节点终态仅靠 GET /run 触发回写（无 workflow 完成回调） | Low-Med | **closed** | 已补 finalize_run 工作流完成回调，见偿还记录 |
| [TD-020](#td-020) | M3 Planner 仅模板优先，全自动 LLM 拆解兜底延后 | Low | **closed** | A2 generate_dag（RAG+双校验+自修复）已补，见偿还记录 |
| [TD-021](#td-021) | M4 执行内核 5 处桩待真实化（模型/凭证/记忆/护栏/MCP） | Med | open(设计内·ADR-0007) | M5/M6 |
| [TD-022](#td-022) | run_node 真实执行路径未经 Temporal worker 端到端测试 | Low-Med | open | worker+temporal 常驻测试环境就绪时 |
| [TD-023](#td-023) | SkillInvocation 计费/可观测为桩（latency/cost=0、聚合一条） | Low | **closed** | 实测 latency + 粗估 cost 已落，见偿还记录 |
| [TD-024](#td-024) | M5 记忆用确定性检索/去重；embedding/向量RAG/语义近邻/reranker 已接入可回退路径 | Med | **closed** | 真实 rerank 模型按部署配置启用 |
| [TD-025](#td-025) | Langfuse 采集+自建观测页(H-1/2/3) 完成；trace_ref 表落库未用(直查 API) | Low | **closed** | trace_ref 表后续按需 |
| [TD-028](#td-028) | execute 写 result_envelope 未关联 task_run.id | Med | **closed** | 已贯通 task_run.id |
| [TD-029](#td-029) | 部署：组件地址 dev 默认 localhost，生产需 env 覆盖 + 容器化用 service name | Low-Med | **closed** | 已补 compose service-name env 与生产模板 |
| [TD-026](#td-026) | M6 仍有桩：Guardrails 规则版/MCP 内置工具/单模型(无主模型·Agent选型) | Low-Med | open | Guardrails-AI/真实MCP/多模型第二步 |
| [TD-027](#td-027) | TEI 模型须预下载离线挂载（hf-mirror 不返回 etag，在线下载失败） | Low | open(运维已知) | 换可返回 etag 的源 / 自建镜像 |
| [TD-030](#td-030) | 模板/预设/记忆语义检索已落；能力语义去重原语已接入 TD-032 goal 提案链 | Med | **closed** | 技能/角色语义检索按后续复用场景再切 |
| [TD-032](#td-032) | Skill 生成链已落；manual 风险分级自动发布、tool/MCP 草稿最小权限+本地沙箱+人审墙、goal 端可达与语义去重已接线 | Med | **closed** | tool 类 LLM authoring / 外部真实 MCP server 沙箱后置 |
| [TD-033](#td-033) | compose-eval 升级为「试产出」judge 并硬门控（judge≥τ active / <τ draft） | Med | **closed** | 已接试产出 eval（带技能 playbook），见偿还记录 |
| [TD-034](#td-034) | 公司无法主动上传/编写自己的 Skill——现仅系统按需自动生成(skillgen) | Med | open(设计内后置) | 用户提出优先做时 |

---

## 详情

### TD-001
**main 分支保护未启用。** trunk-based 规定"`main` 受保护、禁直推"（CLAUDE.md §3 / 约束 14 E1），
但 GitHub 上未开 ruleset，M0 期间多次直推/快进合并到 `main`。
- 影响：无强制 PR/评审，可能误推；规范与现实不一致。
- 偿还：GitHub `Settings → Rules → Rulesets`，对 `main` 勾选 *Require a pull request before merging* + *Require review* + *Require status checks*（配合 TD-002 的 CI）。需仓库管理员（人工，CLI/`gh` 当前不可用）。

### TD-002
**CI workflow 模板已落，远程启用待 workflow scope。** 早期质量门禁仅本地 pre-commit/pre-push，`--no-verify` 可绕过。
- 已偿还（2026-07-07）：新增 `docs/ci/github-actions-ci.yml` 模板，覆盖后端 `ruff`/`mypy`/`pytest`/`bandit`/`pip-audit`、Alembic `upgrade head` + `check` 迁移漂移门、Gitleaks secret scan 与前端 `tsc --noEmit`/`next build`，复用 `uv.lock` 与 `pnpm-lock.yaml`；已补迁移 `8c9d0e1f2a3b` 对齐 schema drift，本地 `alembic upgrade head && alembic check` 通过。
- 约束：当前 GitHub PAT 缺少 `workflow` scope，直接推送 `.github/workflows/ci.yml` 被远程拒绝；需仓库管理员用带 `workflow` scope 的凭证把模板复制到 `.github/workflows/ci.yml`。
- 剩余：GitHub main 分支保护（TD-001）尚未启用，CI 还未成为必过 status check。

### TD-003
**本地 gitleaks 安装脚本与 CI 模板已补。** 官方 pre-commit hook 需现编译 Go，曾因网络失败；
本地改用 `scripts/install-gitleaks.sh` 安装固定版本二进制到 `~/.local/bin`（见 `.pre-commit-config.yaml` 头注），CI 模板使用 `gitleaks/gitleaks-action` 在远程跑全仓 secret scan。
- 影响：远程 CI 尚未启用前，仍依赖本地门禁。
- 偿还：待 `docs/ci/github-actions-ci.yml` 复制到 `.github/workflows/ci.yml` 并启用后，关闭 TD-003。

### TD-004
**基础设施镜像部分用浮动 tag。** `infra/docker-compose.yml` 中 `litellm:main-stable`、`langfuse:2`
（及一定程度上 `pgvector/pgvector:pg18`）非具体版本/digest，违背 E6 锁定精神。
- 影响：不同时间 `pull` 到的镜像可能不同，复现性差。
- 偿还：固定到具体版本号或 `@sha256` digest；进入 staging/共享环境前完成。

### TD-005
**bandit / pip-audit 经 `uvx` / `uv run --with` 临时安装。** 见 `.pre-commit-config.yaml` 的 local hook。
- 影响：每次运行可能拉取、版本漂移、略慢；未纳入 `uv.lock`。
- 偿还：将 bandit、pip-audit 加入 backend dev 依赖组锁定版本。

### TD-006
**`db/session.py` 在模块 import 时创建全局 engine 单例。** `engine = create_engine()` 位于模块顶层。
- 影响：import 即读配置/建连接池，耦合配置加载、不利测试覆写与优雅启停；当前无 DB readiness/健康探针。
- 偿还：改为 FastAPI `lifespan` 管理 engine 生命周期 + 依赖注入；`/health` 增加 DB readiness 检查（区分 liveness/readiness）。建议在 M1 接入真实模型/集成测试时一并重构。

### TD-007
**尚无 DB 集成测试。** 当前仅 `test_health` 这一 in-process 单测；T0.4 的 Alembic 基线靠手动对活库 `upgrade` 验证。
- 影响：模型与迁移、org_id 隔离/RLS 等无自动化回归。
- 偿还：M1 首批模型落地起，引入 testcontainers 跑迁移 + repo/集成测试；落地 T8.3 org_id 隔离回归（A/B 两租户互不可见），纳入门禁。

### TD-008
**早期提交作者归属错误（won't-fix）。** 前 5 个提交（`0a7629d`..`29902db`）作者为本机自动身份
`李宁 <lining@liningdeMacBook-Pro.local>`，而非 GitHub 账号 `multifort <fkdtz2008@gmail.com>`。
- 影响：这些提交在 GitHub 不关联到账号。已推送，修正需 force-push（被门禁禁止）。
- 处置：**接受历史**。已设仓库级 `user.email=fkdtz2008@gmail.com`，自 `d95deec` 起归属正确；不回改历史。

### TD-009
**应用本体容器化入口已落。** 新增 `backend/Dockerfile`、`frontend/Dockerfile` 与 compose `app` profile：
`api` 启动前跑 `alembic upgrade head`，`worker` 复用后端镜像，`web` 用 Next production server。
- 已补（2026-07-07）：`docker compose --env-file .env --profile app config` 已验证配置可解析；整栈启动入口见 `infra/README.md`。
- 已验证（2026-07-07）：使用独立 `BUILDX_CONFIG=/private/tmp/polis-buildx` 绕开本机 root-owned buildx 状态文件，并通过
  `NODE_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:22-alpine-linuxarm64 docker compose --env-file .env --profile app build api web`；
  产物 `polis-api:local` / `polis-web:local` 均为 arm64 镜像。

### TD-010
**运行时 RLS 未接线。** RLS 角色/策略/隔离回归(T8.3)已就位并测通，但**运行中的应用仍以 superuser `polis` 连接**
（`backend/.env` 的 `POLIS_DATABASE_URL`），会绕过 RLS——目前仅靠应用层 org 过滤，且现有端点只触达非 RLS 表（app_user/org/org_member）故无暴露。
- 影响：组织级数据表(role/agent/memory…)开始被读写后，若无 `SET ROLE`+`current_org` 则 RLS 不生效。
- 偿还：M2 当前公司中间件(T9.2)——每请求 `SET ROLE polis_app` + `set_config('app.current_org', org, true)`，请求结束 `RESET`。

### TD-011
**审计日志写入（部分完成）。** `audit_log` 表已建（T8.1）。
已覆盖：org 增改删 + provision（M2）；**认证 register/login/refresh/logout + 审批 plan.approve/plan.signal**（技术债清理批次3/4）。
- **已偿还（2026-06-27）**：登录失败 → `auth.login_failed` 审计（actor=尝试邮箱，不记密码），走**独立 session 事务**（失败请求会回滚，故另起 session 提交才留得下）；best-effort 不影响 401。单测 `test_login_failure_audited`。

### TD-012
**认证缺登出/刷新轮换/会话清理。** 已有 register/login/refresh，但**无 `/api/auth/logout`**（吊销 refresh）、
refresh **不轮换**（refresh 复用同值）、`auth_session` 行**不清理**（过期/吊销记录累积）。
- 影响：无法主动登出失效、refresh 长期有效面增大、session 表膨胀。
- 偿还：补 logout(吊销)、refresh 轮换(旋转+吊销旧)、过期 session 清理任务；M2。

### TD-013
**安全配置生产前须收紧（已完成当前阶段基线）。** dev 仍保留 JWT 默认密钥便利项；CORS 默认已收紧到常用本地前端端口以支持 cookie credentials；生产类环境 fail-closed 校验和 compose 网关认证限流已接入。
- 已完成（批次2）：`Settings.validate_for_prod()` 在 `env` 非 dev/test/local 时 fail-closed 校验——
  拒绝 JWT 默认密钥/长度<32、拒绝 CORS 通配 `*`；`create_app()` 启动调用；`test_config_prod` 覆盖。
- 已完成（2026-07-07）：登录失败限流落地并升级为 DB 共享桶——默认同一邮箱+IP 在 15 分钟窗口内失败 5 次后锁定 15 分钟，返回 `429` 与 `Retry-After`；成功登录清桶，多后端实例共享计数。
- 已完成（2026-07-07）：登录失败限流升级为 DB 共享桶（`auth_rate_limit_bucket`），失败/成功记录走独立事务；多后端实例共享同一邮箱+IP 计数。
- 已完成（2026-07-07）：找回密码闭环落地——一次性 `password_reset_token` 只存哈希，30 分钟过期；确认重置后更新密码、消费 token、吊销该用户所有 refresh 会话，并写审计。前端登录页已接入「忘记密码」流程；dev/local 返回 token 便于联调，生产响应不回显 token。
- 已完成（2026-07-07）：找回密码邮件投递接入——dev/local 可用 file outbox，生产 `validate_for_prod()` 要求 `POLIS_MAIL_BACKEND=smtp`、`POLIS_MAIL_FROM` 与 `POLIS_MAIL_SMTP_HOST`；API 生产响应不回显 token。
- 已完成（2026-07-07）：新增 `infra` app profile 的 Nginx `gateway`，对 `/api/auth/register`、`/api/auth/login`、`/api/auth/refresh`、找回密码 request/confirm 做 IP 维度前置限流（默认 `10r/m`，burst `20`），作为应用内 DB 共享登录失败限流之前的网关保护。公网部署仍可在 CDN/WAF/Ingress 层叠加更靠外的策略。
- 偿还：CORS/JWT env 化、DB 共享登录失败限流、找回密码前后端闭环与邮件投递、compose Nginx 网关认证入口限流已落地。

### TD-014
**前端 token 存 localStorage（已关闭）。**
- 已完成（批次5）：api client 加 401→静默 refresh→重试一次（并发去重）；刷新失败清 token 跳登录；
  `api.logout()` 调后端吊销会话。浏览器实测坏 access+有效 refresh 自动续期成功。
- 已完成（2026-07-07）：后端登录/注册/刷新写入 `polis_access` / `polis_refresh` httpOnly cookie；
  受保护路由兼容 Bearer 与 cookie；刷新/登出支持从 cookie 读取 refresh；前端不再保存 access/refresh 明文，
  仅保留无敏感信息的 `polis_auth` 登录态标记并对请求启用 credentials。
- 偿还：静默刷新与 token 存储硬化均已落地，保留 Bearer 返回值/请求头兼容 CLI、测试与旧会话。

### TD-015
**org 作用域查询助手（已提供）。** 原"统一 org_id 注入的 repo 基类"在 RLS-first 架构下改为更契合的**函数式助手**。
- 已完成（批次6）：`db/org_scoped.py` 的 `select_org_scoped[T: OrgScopedMixin](model, org_id)`；
  planner repo（get_plan/get_task_run_by_plan/update_plan_status）采用为纵深防御示范；`test_org_scoped` 覆盖。
- 约定：请求内查询靠 RLS + 本助手做纵深防御；**请求外任务/脚本（无 RLS 上下文）必须用本助手**，否则跨租户。
- 偿还：助手 + 示范采用 + 约定文档化完成；后续新组织级查询按约定采用。

### TD-016
**权限矩阵未完整落地。** M2 已用 owner 守卫（service 层内联 403）保护公司改名/删除/成员查看；
**M3 收尾**首次启用 `require_role`：`POST /api/plans/{id}/approve`、`/signal` 限 owner/approver（提交 `80ac672`，单测 `test_require_role.py`）。
已补：前端按角色门控审批入口——工作台仅 owner/approver 显示待处理审批，计划详情页禁用「批准并运行」/human gate「通过」，任务列表禁用直接启动类动作；AppShell 正确显示「审批人」角色。
已补（2026-07-07）：成员邀请/接受/移除后端闭环——`POST /api/orgs/{id}/invites`、`POST /api/invites/{token}/accept`、`DELETE /api/orgs/{id}/members/{user_id}`；owner 才能邀请/移除，邀请已有成员幂等返回，最后一个 owner 不能被移除。回归：`tests/test_integration_orgmgmt.py`。
已补（2026-07-07）：花名册页接入 owner 专属成员管理入口，可邀请成员/审批人、展示 dev/local 邀请令牌、移除非 owner 成员；非 owner 只读。
已补（2026-07-07）：`PATCH /api/orgs/{id}/members/{user_id}` 支持 owner 调整成员角色（owner/approver/member），最后一个 owner 不能被降级；花名册页接入角色下拉。回归：`tests/test_integration_orgmgmt.py`。
- 偿还：成员邀请/接受/移除/角色调整前后端基础闭环完成，TD-016 关闭。

### TD-017
**预设关键词匹配对中文弱。** `provisioning.match_preset` 关键词按空格分词做子串匹配，
中文不分词时需空格分隔或精确子串；语义检索（embedding）按 ADR-0006 留 M6。
- 影响：中文自由关键词命中率低；当前 UI 以"选预设"为主，影响有限。
- 偿还：M6 接 LiteLLM embedding 后改语义检索（preset.embedding 已建 hnsw 索引）。
- **已偿还（2026-06-27）**：`provisioning.match_preset` 语义优先——embed 关键词 + `repo.rank_presets_by_vector`(preset.embedding 余弦) 取 top-1，≥τ_preset(0.45) 命中；未命中/无网关/embed 失败 → 关键词子串兜底。`embed_backfill` 补 scenario_preset 回填。API 注入 LiteLLMGateway。单测 `test_provision_semantic.py`(4)。实测 live：「帮我把采购供应商分析一下」(非子串)→语义命中 采购分析公司；无关词→正确 404。

### TD-018
**Temporal worker 沙箱 pydantic_core 延迟导入 UserWarning（已偿还）。**
`workflow.py` 用 `workflow.unsafe.imports_passed_through()` 引入 `schemas`（PlanDag/validate），pydantic_core 曾在沙箱内延迟导入。
- 偿还（批次1）：在 `imports_passed_through` 块显式 `import pydantic` + `import pydantic_core`，
  让其在 workflow 模块初始加载时即 pass through；重起 worker 跑 workflow 实测告警计数 0。

### TD-019
**节点/任务终态仅在 `GET /run` 被调用时回写 DB（无 workflow 完成的主动回调）。**
`finish_task_run` 在轮询 `GET /run` 发现终态时才更新 `task_run`/`plan` 状态；若前端不再轮询，DB 状态可能滞留 `running`。
- 影响：M3 桩执行可接受（前端运行页持续轮询直到终态）；但无轮询场景下 DB 不最终一致。
- **已偿还（2026-06-25）**：`TaskWorkflow.run()` 结束时执行 `finalize_run` Activity 主动回写
  `task_run`/`plan` 终态（含 `finished_at`），不再依赖任何客户端轮询；`GET /run` 惰性回写保留为兜底。
  暴露契机：任务页只读 DB/产出、从不轮询 `/run`，导致运行卡 `running` 与节点产出不一致。见 commit `701c99b`。

### TD-020
**M3 Planner 只实现「模板优先」，T3.2 设计的「全自动拆解兜底」延后。**
研发任务 T3.2 原为「模板优先 + 全自动拆解兜底」；当前 `planner.service.plan` 仅模板优先，
无模板匹配时 `raise NoTemplateMatch`（404）。全自动拆解需 LLM 生成 DAG，依赖模型网关（M6）。
- 影响：当前公司能力不匹配任何模板时无法出图（404），需先有匹配模板；与 ADR-0006 确定性路线一致，M3 演示不受影响。
- **已偿还（2026-06-26，A2）**：`planner/generator.generate_dag`——模板未命中（相似度 < τ_tpl 或无可行模板）
  时 RAG 接地 LLM 生成 DAG（top-k 模板骨架作范例）+ 结构(Pydantic)/语义(`validate`)双校验 + 有界自修复(N=2)，
  仍不过→`PlanInvalid`(422)。无 active 能力仍 404（`NoTemplateMatch`）。实测：营销渠道目标命中采购模板失败→
  生成 4 节点合法 DAG（能力闭合于 org 4 能力、无环、全路由）。单测 `test_plan_generator.py` 5 例。

### TD-021
**M4 执行内核 5 处桩待真实化（设计内，ADR-0007）。** M4 按桩驱动路线搭全部执行内核结构，
依赖项用对齐接口的桩，待 M5/M6 替换（调用方不动）：
- `ModelGateway.chat` → `StubModelGateway`（脚本化/回显，不调真实 LLM）→ **M6 LiteLLM**。
- `CredentialBroker.scoped` → 占位短时句柄（无真实 Key）→ **M6 信封加密 + 用完即焚**。
- `MemoryCenter.retrieve` 返回空切片、`write_fact` 直写无评分去噪 → **M5 RAG 检索 + 写管线**。
- `Guardrails` 规则版（正则注入检测/回流过滤）→ **M6 Guardrails-AI**（注入/PII/内容过滤）。
- MCP 内置本地工具(echo/calc) → **真实外部 MCP server（browser-pilot 等）**。
- 影响：M4 可端到端跑「单节点经 Agent→出处入库」，但无真实 LLM 自主决策/语义记忆/凭证隔离/外部工具。
- 偿还：M5（记忆）、M6（模型/凭证/护栏）按 ADR-0007 桩边界逐处替换；切换点见续接指南 §「M6 切换点」。
- **进展（M5）**：「记忆」处已从空桩换为**确定性真实实现**（写入/检索/衰减/共享并发裁决/治理 API），
  仅 embedding/向量检索/语义近邻仍为确定性桩（见 TD-024）。其余 4 处（模型 chat/凭证/护栏/MCP）仍待 M6。

### TD-022
**`run_node` 真实执行路径未经 Temporal worker 端到端测试。**
`test_workflow` 用 `stub=True` 节点测编排（串/并/human/retry/重规划，不连 DB）；
`test_integration_execute` 直接测 `AgentRuntime.execute`（接 DB）。两者之间——
`run_node(stub=False)→execute_node` 经真实 Temporal worker+DB 的全链路——只在手工联调验证过，无自动化测试。
- 影响：worker 进程内 `init_engine`/session 生命周期、Activity 超时/重试与真实执行的交互无回归保护。
- 偿还：worker+temporal+pgvector 常驻测试环境就绪后，补一条经 Temporal Client 启动→真实 execute_node→envelope 入库的端到端用例。

### TD-023
**SkillInvocation 计费/可观测为桩。** `AgentRuntime.execute` 每节点聚合写一条 `skill_invocation`，
`latency_ms=0`、`cost_cents=0`，未按实际工具调用拆分、无真实耗时/成本。
- 影响：调用日志可证「有执行」，但计费/性能数据不可用。
- 偿还：M6 接 LiteLLM（真实 token 成本）+ Langfuse（trace/耗时）后，按工具调用粒度记录真实 latency/cost。
- **已偿还（2026-06-27）**：`agent_runtime.execute` 记**实测 latency_ms**（节点墙钟 perf_counter）+ **粗估 cost_cents**（`_rough_cost_cents`：输出 token×目录价 price_out，权威成本仍在 observability 的 langfuse 实测 in+out）。单测 `test_integration_execute` 断言 latency_ms>0。仍为聚合一条（非按工具粒度拆分）——工具级拆分留后续。

### TD-024
**M5 记忆为确定性实现；M6 已逐步接入语义能力（复用 ADR-0006/0007）。**
M5 写入/检索/衰减/共享并发/治理均真实落地；M6 已把 embedding/向量 RAG 与去重近邻逐步接上：
- `ModelGateway.embed` 有真实实现时会写入 `memory.embedding`，Stub 环境仍返回 None 并走确定性回退。
- 检索 `retrieve` 有 query embedding 时走 pgvector 余弦近邻；无向量或无命中时回退关键词 token 重叠 + importance/recency。
- rerank 为可选 LiteLLM reranker（`POLIS_RERANK_MODEL` 非空时启用）；未配置或失败时回退本地排序。
- 去重先用 `find_by_content` 精确匹配；有 embedding 时再用 `find_similar_by_vector` 做同 org/scope/namespace 语义近邻裁决（write_facts 去重、org 共享事实 override/conflict 共用）。
- 影响：无 embedding 的本地/桩路径仍只能精确匹配；有 embedding 的路径已能覆盖近义重复。
- **已偿还(M6)**：embed 已接本地 TEI(bge,1024)，write 自动填充 embedding、retrieve 切向量 RAG（M6-D），语义去重/近邻已接入；`ModelGateway.rerank` 与 `LiteLLMGateway.rerank` 已接入记忆检索，默认可回退本地排序。

### TD-025
**Langfuse 采集 + 自建观测页全通（已偿还）。**
- H-1：Langfuse v2 容器 headless 开箱即用（预置 keys，3001，零手动配置）+ LiteLLMGateway 自动上报 trace。
- H-2：后端聚合 API `GET /api/plans/{id}/observability`（manifest + 节点产出 + Langfuse LLM 明细，
  `langfuse_client.fetch_generations` 按 trace=task_id 拉，trust_env=False 直连）。
- H-3：前端「运行观测」页（Polis 风格，不暴露 Langfuse UI）。
- 实测：采购 4 节点真实 DeepSeek 执行 → 观测页展示真实产出 + 4 次 LLM 调用 token 数。
- 残留（低优先，按需）：`trace_ref` 表未落库（当前直查 langfuse API by task_id 已够）。

### TD-028
**`execute` 写 `result_envelope` 未关联 `task_run.id`（已偿还）。**
- 偿还：`approve` 先建 task_run 再 `start_workflow(args 加 run.id)`；`TaskWorkflow.run(plan, org_id, task_id)`
  → `run_node(node, org_id, task_id)` → `execute_node/execute`，写 `ResultEnvelope.task_id` + Langfuse trace
  session=task_id（任务级聚合）。实测采购 4 节点 envelope 关联 task_run、观测页按任务聚合。

### TD-029
**部署：组件地址用 dev 默认 localhost，生产需 env 覆盖。** 现状是 12-factor（`config.py` 默认值 + `POLIS_*` env 可覆盖），
架构正确；容器化时已显式配置：
- `POLIS_DATABASE_URL` / `POLIS_TEMPORAL_ADDR` / `POLIS_EMBEDDING_BASE_URL` / `POLIS_LANGFUSE_HOST` 指向真实地址。
- 应用容器化后，env 用容器网络 **service name**（`postgres:5432` / `temporal:7233` /
  `text-embeddings:80` / `langfuse:3000`），而非 localhost。
- 已修：`seed.py` 不再把 `connector.base_url=localhost` 写进 model_catalog（改为运行时由 `POLIS_EMBEDDING_BASE_URL` 决定）。
- 偿还（2026-07-07）：`infra/docker-compose.yml` 的 `api/worker` 已使用 service-name env；新增 `infra/.env.production.example` 作为 staging/生产模板。

### TD-026
**M6 仍有桩/简化项。**
- Guardrails 为规则版（正则注入检测），非 Guardrails-AI（注入/PII/内容过滤全量）。
- MCP 仅内置本地工具(echo/calc)，无真实外部 server（browser-pilot 等）。
- 模型配置为「单模型」：无 org 主模型字段、无按 Agent 选模型（AgentConfig.model 已有字段但前端未暴露）。
- 偿还：Guardrails-AI 接入；MCP 真实 server；多模型第二步（org.primary_model_id + Agent 选型 + cost_aware_pick 路由）。

### TD-027
**TEI embedding 模型须预下载离线挂载。** hf-mirror 反代不返回 `etag` header，TEI rust 下载器在线下载失败；
改为本机 `huggingface-cli download` 到 `infra/tei-models/` 挂载（`--model-id /data/models/...`）。
- 影响：换机/新环境需先预下载模型（~1.2G），非「compose up 即用」。
- 偿还：换可返回 etag 的镜像源 / 自建含模型的镜像 / 或用支持 hf-mirror 的下载方式。

### TD-030
**A1 检索升级仅落「模板语义选择」第一刀，能力/技能/角色语义检索延后（用户决策切片）。**
A1 设计（docs/design/v2/00 §A1）原为「模板/角色/技能/能力**全部**语义检索」。为符合 DoR（1–3 天可独立验收）
+ 尽早过评审，按用户决定先只做最高价值、最目标盲的一处——`service.plan` 模板选择：
从「第一个能力可行的模板」改为「能力可行候选中按 goal↔模板向量最相似择优」，TEI 不可用时优雅回退确定性逻辑。
- 影响：能力解析（节点 `required_capabilities`）、技能/角色检索仍走原关键词/遍历；多模板同质场景外，效果与原逻辑接近。
- 偿还：A1 后续刀补能力语义解析；技能/角色语义检索随 A3 编配生成 / B2 分层接地接线时一并做。属切片后置，非疏漏。
- **已偿还（2026-07-03）**：模板语义=A1；预设语义=TD-017；org 记忆语义接地=B2。**能力语义去重原语**（§14.4）已落：`repo.rank_capabilities_by_vector` + `skillgen.resolve_capability`（embed→最近已有 key，≥τ_dedup(0.86)复用，否则新）+ 单测 `test_capability_dedup.py`，并已作为 TD-032 goal 端能力提案链的活跃调用方接线。**注**：能力 key 是契约，**执行期路由保持精确匹配**，语义只用于登记去重（避免误路由）。技能/角色语义检索按后续复用场景再切。
- **TD-010 已偿还**：运行时 RLS 接通——`OrgContext` 中间件每请求 `SET LOCAL ROLE polis_app`
  + `set_config('app.current_org', …)`，组织级端点（如花名册）按公司隔离；HTTP 层隔离回归
  `tests/test_integration_orgctx.py`（X-Org-Id A/B 互不可见 + 非成员 403 + 缺头 400）已测通。
- **TD-006 已偿还**：引擎改 FastAPI `lifespan` 管理（`db/session.py` 不再 import 时建引擎）+ `/ready` DB 就绪探针。

### TD-032
**A3 编配生成仅落「拼已有 Skill 成 Agent」，缺 Skill→生成草稿+人审墙延后（设计内切片，design §5.4 line 225 允许）。**
A3 完整定义（docs/design/v2/01 §5.2–5.4）= ① 节点无现成 Agent→拼已审 Skill 成 Agent（自动）+ ② 某能力连 Skill 都没有→生成 Skill 草稿→沙箱→★人审★→发布→能力 active→回到 ①。
本次落 ①（`planner/composer.compose_agent`/`route_or_compose`，已接 `service.plan`）；② 缺 Skill 时 `compose_agent` 返回 None＝「该能力暂不可办」，路由置 None（设计 §5.4 line 225 明确允许检索/拼装期先不做生成）。
- 影响：目标若需要一个**既无 Agent 又无任何 Skill**的能力，该节点无法被覆盖（路由 None），需人工补 Skill 后再跑。`available_capabilities` 已含 published Skill 能力（ADR-0009），故「有 Skill 无 Agent」场景已能自动拼装。
- **机制已落（2026-06-27）**：`planner/skillgen.py`——`generate_skill_draft(cap)` 让 LLM 写 manual playbook，
  落 `Skill(status='draft', trust='private', visibility='org')` + `SkillVersion(content)` + 建 `skill_review`
  审批（**安全红线：绝不自动发布**，CLAUDE.md §4.6）；`publish_skill` 仅在人审通过后置 published/verified
  （能力随之进 `available_capabilities`）。`compose_agent` 缺 Skill → 生成草稿+撞墙（返 None）；approval decide
  approve+skill_review → 自动 `publish_skill`。集成测试 `test_integration_skillgen.py`（草稿/私有/幂等/
  发布/仅本 org/发布后可拼装）。
- **风险分级放行（2026-06-27，ADR-0009 修订）**：洞察「副作用来自工具、不来自提示词」——`manual`
  playbook 过自动 eval(`_auto_eval` 沙箱试用 + judge≥0.6) → **自动 published(community)、无人卡、同轮可用**
  （`compose_agent` 对自动放行能力同轮拼装）；`tool` 类才保留人审墙。留审计痕(approved/decided_by NULL)。
  实测 live：生成 playbook → judge 0.98 → 自动发布。解决「每个任务都等人审、不智能」。
- **tool/MCP 草稿沙箱闸（2026-07-03）**：`create_tool_skill_draft` 支持登记 tool 类私有草稿，强制最小权限
  （`effects ∈ none/read/compute`、无凭证、无网络、无文件系统、`allowed_tools` 只能含当前工具）+ 本地
  `McpRegistry` 沙箱试跑；通过后只创建 `skill_review` pending，**绝不自动发布**。`publish_skill` 对 tool
  额外检查 `permissions.sandbox.passed`，未过沙箱即使审批调用也不发布；审批 API 先确认发布条件再标记
  approval approved，避免「审批已通过但 Skill 仍 draft」的脏状态。测试覆盖 sandbox 通过后人审发布、
  权限越界不落库；补纯单测覆盖最小权限校验与本地 MCP 沙箱调用。
- **goal 端可达（2026-07-03）**：模板未命中进入 A2 生成前，`service.plan` 先让模型输出最多 2 个
  缺失能力提案；提案经 `resolve_capability` 语义去重后接 `generate_skill_draft`。manual 自动 eval 过则同轮
  published 并加入本次 `available`，pending/tool 仍留人审墙、不进入本轮规划。集成测试覆盖「无可用能力 org →
  goal 提案新能力 → 自动发布 Skill → 同轮生成 DAG → route_or_compose 拼 Agent」。
- **剩余（后置增强）**：tool 类 Skill 的 LLM 自动 authoring / 外部真实 MCP server 沙箱仍后置；当前已支持
  显式登记 tool 草稿并过最小权限 + 本地 MCP 沙箱闸。若做公司自定义技能库（TD-034），复用本闸口。

### TD-033
**A4 compose-time 自动背书为 advisory（不硬门控激活），「试产出/执行 eval 硬降级」延后。**
设计（§13.2）原意为 `eval(agent 试产出)→judge≥τ→activate`，即判**真实试跑产出**。本次为控成本/复杂度，
compose 后只用一次轻量 judge 评「岗位说明+技能名+声明能力」的胜任度（`composer._endorse`），写进
`config.eval` 快照（judge/passed/at/kind）。但该 judge **只见技能名、看不到技能实现**，是弱信号
（实测对内容缺失的占位 Skill judge≈0），故**不据此硬门控**——拼装 Agent 仍直接 active，权威背书交给
**S1 执行期质量门**（对真实节点产出 judge→needs_rework，已实现）。
- 影响：compose 出的 Agent 的 `config.eval.passed` 仅供观测/「采纳率」基线，不影响其可用性；真正拦截坏产出靠 S1。
- **已偿还（2026-06-27）**：`composer._trial_endorse`——拼装后让 Agent **试产出**一份示例结果再 judge：
  把 cfg.prompt + 绑定技能的 **playbook 正文**（`_skill_contents`）作 system，让模型产一份示例产出，再用
  `evaluator.score` 评分。judge≥τ(0.6) → active；<τ → 落 draft + 返回 None（硬降级）。两次 LLM 调用、
  无副作用（不落 envelope）。**实测对比**：旧 advisory judge 只见技能名 → 0.0（会误杀）；新试产出 judge
  看真实产出 → 1.0（带 playbook 的 market.sentiment 拼装），分离可靠，故可硬门控。运行期仍有 S1 质量门兜底。
  测试 `test_compose_trial_endorse_hard_gate`（高分 active / 低分 draft+None）。
  注：未用全 AgentRuntime（避免 trial 落 envelope/调用日志副作用）；tool 类技能的工具调用未在 trial 里跑——
  够用，全 runtime trial 留作将来。
- **TD-007 已偿还**：新增 testcontainers 集成测试（`backend/tests/conftest.py` 起临时 pgvector 容器 + 跑 alembic，
  `test_integration_identity.py` 覆盖注册/登录/me/建公司/失败态 + schema/RLS 断言）。Docker 不可用时优雅跳过，
  并自动探测 macOS Docker Desktop 的 `DOCKER_HOST`。
- **org_id RLS 强制已落地（M1 收尾批次）**：`polis_app`(NOLOGIN 非 superuser)角色 + `SET ROLE` 机制 +
  `NULLIF` 健壮策略；隔离回归 `T8.3`（`tests/test_integration_rls.py`）测通 A/B 互不可见 + fail-closed。
  应用按请求 `SET ROLE`+`current_org` 中间件随 M2(T9.2) 接线。

### TD-034
**公司无法主动上传/编写自己的 Skill——现仅系统按需自动生成，无「公司自定义技能库」入口。**
背景（2026-07-02 用户提出）：Skill/角色模板/场景模板三层资产已统一 `visibility`(public/private) +
`owner_org_id` 可见性模型（design [v2/04](design/v2/04-资产仓库（三层·可见性·复用·晋升）.md) §5，R1 已落地），
`skill` 表已有这两个字段。但**唯一产生 Skill 的路径是 `planner/skillgen.py` 的系统自动生成**：
编配器（`composer.compose_agent`）缺某能力的 Skill 时，LLM 才会自动写一份 playbook 草稿 →
按风险分级放行（`manual`/无副作用 → 自动 eval 过了就发布；`tool`/有副作用 → 人审墙）。
公司自己**不能主动**说"我要新增一个技能，内容是这样"——没有对应的上传/编写 UI 或 API。
- **影响**：公司想沉淀自己的专属打法（如内部话术模板、特定审批流程 playbook）只能等系统按需触发生成，
  无法主动维护自己的私有技能库；"公司越用越像自己"的资产沉淀目前偏被动。
- **不阻塞现状**：现有自动生成+风险分级机制已能覆盖"编配器缺能力"场景，属核心闭环已通。此项是
  **锦上添花的主动入口**，非缺陷。
- **触发时机**：用户明确要求做"公司自定义技能库"时再排期。届时落点：
  ① `POST /api/skills`（公司手动创建 private Skill，复用现有 `visibility`/`owner_org_id`/审批墙——
  `manual` 类可能仍需过一次 `skillgen._auto_eval`，`tool` 类必过人审，与自动生成路径公用同一套信任闸）；
  ② 前端"技能库"页（新建/编辑/查看已有私有 Skill，类比现有花名册/工作列表的 IA）；
  ③ 与 R3/R4（场景/角色模板飞轮）是并行独立的两条线，不互相阻塞。

### M3 后技术债清理批次（2026-06-20）
- **TD-004 已偿还**：docker-compose 固定 litellm `main-stable→v1.89.2`、langfuse `2→2.95.11`
  （`docker manifest inspect` 确认存在）；pgvector:pg18 保留（华为云 retag 无 registry digest）。
- **TD-005 已偿还**：bandit/pip-audit 加入 backend dev 依赖组锁定（uv.lock），pre-commit hook
  从 `uvx`/`--with` 临时安装改为 `uv run`（复用锁定版本）。
- **TD-012 已偿还**：登出端点 `POST /api/auth/logout`（吊销 refresh，幂等）+ refresh 轮换（吊销旧发新）+
  `get_active_session_by_hash` 补 `expires_at` 校验 + 会话清理 `cleanup_auth_sessions` + CLI
  (`python -m polis.modules.org.cleanup`)；`test_integration_auth_lifecycle` 覆盖。
- **TD-015 已偿还**：`db/org_scoped.py` 的 `select_org_scoped` 助手 + planner repo 采用为纵深防御示范；
  `test_org_scoped` 覆盖；约定「请求外任务必须用助手」文档化。
- **TD-011/013/014 已偿还**：TD-011 认证/审批成功/失败事件审计；TD-013 生产 fail-closed 校验(JWT/CORS/邮件)、DB 共享登录失败限流、找回密码前后端闭环与 compose 网关认证限流；
  TD-014 静默刷新 + httpOnly cookie token 存储硬化。
- **TD-018 已偿还**：`workflow.py` 在 `imports_passed_through` 块显式 pass through pydantic+pydantic_core，
  消除 Temporal 沙箱 UserWarning（实测计数 0）。
