# Polis 技术债台账

> 记录开发中有意/被迫做的妥协与延后项，便于后续回溯与偿还。
> **纪律**：每当为推进而走捷径、留 TODO、延后某项工程实践，在此登记一条（属 DoD 的一部分，见 `docs/constraints/15`）。
> 偿还后把状态改为 `closed` 并注明提交。严重度：High（须尽快）/ Med（择机）/ Low（可接受，留痕）。

## 台账

| ID | 标题 | 严重度 | 状态 | 偿还触发 |
|---|---|---|---|---|
| [TD-001](#td-001) | main 分支保护未启用 | Med | open | 引入第二贡献者 / V1 正式开发前 |
| [TD-002](#td-002) | 无 CI，门禁仅本地 | Med | open(设计内 E4 后置) | 团队 >1 或进入 V2 |
| [TD-003](#td-003) | gitleaks 非自举/跨平台 | Low | open | 随 CI(TD-002) |
| [TD-004](#td-004) | 基础设施镜像用浮动 tag | Low-Med | **closed** | 已固定 litellm/langfuse，见偿还记录 |
| [TD-005](#td-005) | bandit/pip-audit 临时安装未锁版本 | Low | **closed** | 已锁入 dev 依赖，见偿还记录 |
| [TD-006](#td-006) | db 引擎模块级单例、无 readiness | Med | **closed** | 已补，见偿还记录 |
| [TD-007](#td-007) | 无 DB 集成测试(testcontainers) | Med | **closed** | 已补，见偿还记录 |
| [TD-008](#td-008) | 早期提交作者归属错误 | Low | accepted(won't-fix) | — |
| [TD-009](#td-009) | 应用本体未容器化 | Low | open(设计内 E8 后置) | E8 启用时 |
| [TD-010](#td-010) | 运行时 RLS 未接线 | Med | **closed** | 已补（M2 T9.2），见偿还记录 |
| [TD-011](#td-011) | 审计仅覆盖 org 写操作（auth 事件未） | Med | open(部分) | 登录失败审计随限流做 |
| [TD-012](#td-012) | 认证缺登出/刷新轮换/会话清理 | Med | **closed** | 已补，见偿还记录 |
| [TD-013](#td-013) | 安全配置生产前须收紧（CORS `*`/JWT 默认密钥/无限流/找回密码桩） | Med | open(部分) | 限流/找回密码仍待对外前 |
| [TD-014](#td-014) | 前端 token 存 localStorage + 无静默刷新 | Low-Med | open(部分) | localStorage→cookie 待前端硬化 |
| [TD-015](#td-015) | org 过滤 repo 基类未建 | Low | **closed** | 已提供 select_org_scoped 助手 |
| [TD-016](#td-016) | 权限矩阵未完整落地（approver/member 区分 + 成员邀请/移除） | Low-Med | open | 审批/成员管理接入时 |
| [TD-017](#td-017) | 预设关键词匹配对中文弱（无分词/无语义） | Low | open | M6 embedding 语义匹配 |
| [TD-018](#td-018) | Temporal worker 沙箱 pydantic_core 延迟导入 UserWarning | Low | **closed** | 已消除，见偿还记录 |
| [TD-019](#td-019) | 节点终态仅靠 GET /run 触发回写（无 workflow 完成回调） | Low-Med | open | M6 审批/Manifest 接线时 |
| [TD-020](#td-020) | M3 Planner 仅模板优先，全自动 LLM 拆解兜底延后 | Low | open(设计内后置) | M6 模型网关接入时 |
| [TD-021](#td-021) | M4 执行内核 5 处桩待真实化（模型/凭证/记忆/护栏/MCP） | Med | open(设计内·ADR-0007) | M5/M6 |
| [TD-022](#td-022) | run_node 真实执行路径未经 Temporal worker 端到端测试 | Low-Med | open | worker+temporal 常驻测试环境就绪时 |
| [TD-023](#td-023) | SkillInvocation 计费/可观测为桩（latency/cost=0、聚合一条） | Low | open | M6 模型网关+Langfuse 接线时 |
| [TD-024](#td-024) | M5 记忆用确定性检索/去重，embedding/向量RAG/reranker/语义近邻延后 | Med | **部分偿还(M6)** | reranker/语义去重待续 |
| [TD-025](#td-025) | Langfuse 采集+自建观测页(H-1/2/3) 完成；trace_ref 表落库未用(直查 API) | Low | **closed** | trace_ref 表后续按需 |
| [TD-028](#td-028) | execute 写 result_envelope 未关联 task_run.id | Med | **closed** | 已贯通 task_run.id |
| [TD-029](#td-029) | 部署：组件地址 dev 默认 localhost，生产需 env 覆盖 + 容器化用 service name | Low-Med | open | 应用容器化(TD-009)/进 staging 前 |
| [TD-026](#td-026) | M6 仍有桩：Guardrails 规则版/MCP 内置工具/单模型(无主模型·Agent选型) | Low-Med | open | Guardrails-AI/真实MCP/多模型第二步 |
| [TD-027](#td-027) | TEI 模型须预下载离线挂载（hf-mirror 不返回 etag，在线下载失败） | Low | open(运维已知) | 换可返回 etag 的源 / 自建镜像 |

---

## 详情

### TD-001
**main 分支保护未启用。** trunk-based 规定"`main` 受保护、禁直推"（CLAUDE.md §3 / 约束 14 E1），
但 GitHub 上未开 ruleset，M0 期间多次直推/快进合并到 `main`。
- 影响：无强制 PR/评审，可能误推；规范与现实不一致。
- 偿还：GitHub `Settings → Rules → Rulesets`，对 `main` 勾选 *Require a pull request before merging* + *Require review* + *Require status checks*（配合 TD-002 的 CI）。需仓库管理员（人工，CLI/`gh` 当前不可用）。

### TD-002
**无 CI，质量门禁仅本地 pre-commit/pre-push。** 这是约束 14 明确的 E4 后置项，非疏漏。
- 影响：`--no-verify` 可绕过；未执行 `pre-commit install` 的环境完全不设防；门禁不在服务端强制。
- 偿还：引入 CI（GitHub Actions 等）跑同一套 ruff/mypy/pytest/gitleaks/bandit/pip-audit + alembic check + 隔离测试，作为 `main` 的必过检查。

### TD-003
**gitleaks 用本机预编译二进制，非自举、未跨平台。** 官方 pre-commit hook 需现编译 Go，曾因网络失败；
改用 `~/.local/bin/gitleaks`（见 `.pre-commit-config.yaml` 头注）。
- 影响：新成员 / Linux / CI 需自行安装 gitleaks，非"clone 即用"。
- 偿还：CI 内用容器化 gitleaks，或固定二进制版本的安装脚本；随 TD-002 一并解决。

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
**应用本体未容器化。** `infra/docker-compose.yml` 仅含 4 个基础设施，Polis 后端用 `make dev` 本地跑。
这是约束 14 的 E8 后置项，非疏漏。
- 影响：尚无"一键起含应用"的整栈；部署形态待补。
- 偿还：E8 启用时新增 `backend/Dockerfile` 与 compose 的 app/web 服务（前端就绪后）。

### TD-010
**运行时 RLS 未接线。** RLS 角色/策略/隔离回归(T8.3)已就位并测通，但**运行中的应用仍以 superuser `polis` 连接**
（`backend/.env` 的 `POLIS_DATABASE_URL`），会绕过 RLS——目前仅靠应用层 org 过滤，且现有端点只触达非 RLS 表（app_user/org/org_member）故无暴露。
- 影响：组织级数据表(role/agent/memory…)开始被读写后，若无 `SET ROLE`+`current_org` 则 RLS 不生效。
- 偿还：M2 当前公司中间件(T9.2)——每请求 `SET ROLE polis_app` + `set_config('app.current_org', org, true)`，请求结束 `RESET`。

### TD-011
**审计日志写入（部分完成）。** `audit_log` 表已建（T8.1）。
已覆盖：org 增改删 + provision（M2）；**认证 register/login/refresh/logout + 审批 plan.approve/plan.signal**（技术债清理批次3/4）。
- 剩余：**登录失败审计**（防暴力破解）需独立事务（失败路径回滚会丢审计），与登录限流(TD-013剩余)一并做。
- 偿还：批次3 `write_audit` 接入认证/审批成功路径（`test_integration_audit`）；失败审计待限流。

### TD-012
**认证缺登出/刷新轮换/会话清理。** 已有 register/login/refresh，但**无 `/api/auth/logout`**（吊销 refresh）、
refresh **不轮换**（refresh 复用同值）、`auth_session` 行**不清理**（过期/吊销记录累积）。
- 影响：无法主动登出失效、refresh 长期有效面增大、session 表膨胀。
- 偿还：补 logout(吊销)、refresh 轮换(旋转+吊销旧)、过期 session 清理任务；M2。

### TD-013
**安全配置生产前须收紧（部分完成）。** dev 便利项：CORS `["*"]`、JWT 默认密钥、无限流、找回密码桩。
- 已完成（批次2）：`Settings.validate_for_prod()` 在 `env` 非 dev/test/local 时 fail-closed 校验——
  拒绝 JWT 默认密钥/长度<32、拒绝 CORS 通配 `*`；`create_app()` 启动调用；`test_config_prod` 覆盖。
- 剩余：**登录限流**（暴力破解）、**找回密码**实现；进 staging/对外前做。
- 偿还：CORS/JWT env 化已落地；限流/找回密码待对外前。

### TD-014
**前端 token 存 localStorage（部分完成）。**
- 已完成（批次5）：api client 加 401→静默 refresh→重试一次（并发去重）；刷新失败清 token 跳登录；
  `api.logout()` 调后端吊销会话。浏览器实测坏 access+有效 refresh 自动续期成功。
- 剩余：access/refresh 仍存 `localStorage`（XSS 面），httpOnly cookie 方案待评估。
- 偿还：静默刷新已落地；存储方案硬化待前端安全专项。

### TD-015
**org 作用域查询助手（已提供）。** 原"统一 org_id 注入的 repo 基类"在 RLS-first 架构下改为更契合的**函数式助手**。
- 已完成（批次6）：`db/org_scoped.py` 的 `select_org_scoped[T: OrgScopedMixin](model, org_id)`；
  planner repo（get_plan/get_task_run_by_plan/update_plan_status）采用为纵深防御示范；`test_org_scoped` 覆盖。
- 约定：请求内查询靠 RLS + 本助手做纵深防御；**请求外任务/脚本（无 RLS 上下文）必须用本助手**，否则跨租户。
- 偿还：助手 + 示范采用 + 约定文档化完成；后续新组织级查询按约定采用。

### TD-016
**权限矩阵未完整落地。** M2 已用 owner 守卫（service 层内联 403）保护公司改名/删除/成员查看；
**M3 收尾**首次启用 `require_role`：`POST /api/plans/{id}/approve`、`/signal` 限 owner/approver（提交 `80ac672`，单测 `test_require_role.py`）。
仍缺：**成员邀请/移除**端点（成员列表只读，对接 09 T9.5）；**前端按角色隐藏审批按钮**（当前 member 点「批准并运行」收 403 → 提示「权限不足」降级）。
- 影响：审批权后端已区分；成员管理与前端角色门控是后续能力。
- 偿还：审批收件箱(M6)/成员管理接入时，补成员邀请流程 + 前端角色门控。

### TD-017
**预设关键词匹配对中文弱。** `provisioning.match_preset` 关键词按空格分词做子串匹配，
中文不分词时需空格分隔或精确子串；语义检索（embedding）按 ADR-0006 留 M6。
- 影响：中文自由关键词命中率低；当前 UI 以"选预设"为主，影响有限。
- 偿还：M6 接 LiteLLM embedding 后改语义检索（preset.embedding 已建 hnsw 索引）。

### TD-018
**Temporal worker 沙箱 pydantic_core 延迟导入 UserWarning（已偿还）。**
`workflow.py` 用 `workflow.unsafe.imports_passed_through()` 引入 `schemas`（PlanDag/validate），pydantic_core 曾在沙箱内延迟导入。
- 偿还（批次1）：在 `imports_passed_through` 块显式 `import pydantic` + `import pydantic_core`，
  让其在 workflow 模块初始加载时即 pass through；重起 worker 跑 workflow 实测告警计数 0。

### TD-019
**节点/任务终态仅在 `GET /run` 被调用时回写 DB（无 workflow 完成的主动回调）。**
`finish_task_run` 在轮询 `GET /run` 发现终态时才更新 `task_run`/`plan` 状态；若前端不再轮询，DB 状态可能滞留 `running`。
- 影响：M3 桩执行可接受（前端运行页持续轮询直到终态）；但无轮询场景下 DB 不最终一致。
- 偿还：M6 审批/Run Manifest 接线时，由 Temporal workflow 完成钩子或 Activity 主动回写终态（含 finished_at）。

### TD-020
**M3 Planner 只实现「模板优先」，T3.2 设计的「全自动拆解兜底」延后。**
研发任务 T3.2 原为「模板优先 + 全自动拆解兜底」；当前 `planner.service.plan` 仅模板优先，
无模板匹配时 `raise NoTemplateMatch`（404）。全自动拆解需 LLM 生成 DAG，依赖模型网关（M6）。
- 影响：当前公司能力不匹配任何模板时无法出图（404），需先有匹配模板；与 ADR-0006 确定性路线一致，M3 演示不受影响。
- 偿还：M6 接 LiteLLM 后补 LLM 拆解兜底（无模板→LLM 生成 DAG→过 `validate`→落库），与模板优先同构。属设计内后置（同 ADR-0006 思路），非疏漏。

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

### TD-024
**M5 记忆为确定性实现，语义能力延后 M6（设计内，复用 ADR-0006/0007）。**
M5 写入/检索/衰减/共享并发/治理均真实落地，但依赖 embedding 的部分用确定性桩：
- `ModelGateway.embed` 桩返 None → `memory.embedding` 列写入为 NULL（hnsw 索引暂无数据）。
- 检索 `retrieve` 用关键词 token 重叠（中文按单字，弱，同 TD-017）+ importance/recency，非向量 `<=>`。
- rerank 为确定性加权排序，非 LiteLLM reranker。
- 去重 `find_by_content` / 共享并发 `find_similar` 用内容精确匹配，非语义近邻。
- 影响：跨表述/近义的检索与去重召回弱；M5 演示（写回→再检索闭环）在关键词重叠下可用。
- 偿还：M6 接 LiteLLM embed/reranker——write 自动填充 embedding、retrieve 切向量 RAG、去重/近邻切语义。
- **进展(M6)**：embed 已接本地 TEI(bge,1024)，write 自动填充 embedding、retrieve 切向量 RAG（M6-D）；
  剩 **LiteLLM reranker** 与 **语义去重/近邻**（find_by_content/find_similar 仍内容精确匹配）待续。

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
架构正确，但部署时须显式配置：
- `POLIS_DATABASE_URL` / `POLIS_TEMPORAL_ADDR` / `POLIS_EMBEDDING_BASE_URL` / `POLIS_LANGFUSE_HOST` 指向真实地址。
- 应用容器化（TD-009）后，env 用容器网络 **service name**（`postgres:5432` / `temporal:7233` /
  `text-embeddings:80` / `langfuse:3000`），而非 localhost。
- 已修：`seed.py` 不再把 `connector.base_url=localhost` 写进 model_catalog（改为运行时由 `POLIS_EMBEDDING_BASE_URL` 决定）。
- 偿还：进 staging / 应用容器化时，提供生产 env 清单 + compose `app` 服务示例（service name）+ 可选 `.env.production` 模板。

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

---

## 偿还记录
- **TD-010 已偿还**：运行时 RLS 接通——`OrgContext` 中间件每请求 `SET LOCAL ROLE polis_app`
  + `set_config('app.current_org', …)`，组织级端点（如花名册）按公司隔离；HTTP 层隔离回归
  `tests/test_integration_orgctx.py`（X-Org-Id A/B 互不可见 + 非成员 403 + 缺头 400）已测通。
- **TD-006 已偿还**：引擎改 FastAPI `lifespan` 管理（`db/session.py` 不再 import 时建引擎）+ `/ready` DB 就绪探针。
- **TD-007 已偿还**：新增 testcontainers 集成测试（`backend/tests/conftest.py` 起临时 pgvector 容器 + 跑 alembic，
  `test_integration_identity.py` 覆盖注册/登录/me/建公司/失败态 + schema/RLS 断言）。Docker 不可用时优雅跳过，
  并自动探测 macOS Docker Desktop 的 `DOCKER_HOST`。
- **org_id RLS 强制已落地（M1 收尾批次）**：`polis_app`(NOLOGIN 非 superuser)角色 + `SET ROLE` 机制 +
  `NULLIF` 健壮策略；隔离回归 `T8.3`（`tests/test_integration_rls.py`）测通 A/B 互不可见 + fail-closed。
  应用按请求 `SET ROLE`+`current_org` 中间件随 M2(T9.2) 接线。

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
- **TD-011/013/014 部分偿还**：TD-011 认证/审批成功事件审计；TD-013 生产 fail-closed 校验(JWT/CORS)；
  TD-014 前端静默刷新。三者剩余项（登录失败审计/限流/找回密码、token 存储硬化）见各自详情。
- **TD-018 已偿还**：`workflow.py` 在 `imports_passed_through` 块显式 pass through pydantic+pydantic_core，
  消除 Temporal 沙箱 UserWarning（实测计数 0）。
