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
| [TD-004](#td-004) | 基础设施镜像用浮动 tag | Low-Med | open | 进 staging/共享环境前 |
| [TD-005](#td-005) | bandit/pip-audit 临时安装未锁版本 | Low | open | 随 CI 或下次依赖整理 |
| [TD-006](#td-006) | db 引擎模块级单例、无 readiness | Med | open | M1 接真实模型/集成测试时 |
| [TD-007](#td-007) | 无 DB 集成测试(testcontainers) | Med | open | M1 首批模型落地 |
| [TD-008](#td-008) | 早期提交作者归属错误 | Low | accepted(won't-fix) | — |
| [TD-009](#td-009) | 应用本体未容器化 | Low | open(设计内 E8 后置) | E8 启用时 |

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

---

## 偿还记录
（暂无。偿还某项时在此追加：`TD-00X 已偿还 @<commit> <说明>`。）
