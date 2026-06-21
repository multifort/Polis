# ADR-0008：可观测用 Langfuse v2（自建观测页），v3 延后到高负载

- 状态：accepted
- 日期：2026-06-21

## 背景
M6 可观测复用 Langfuse。Langfuse 有两条线：
- **v2**：单容器 + 复用 postgres，轻量；官方已进入维护模式（仍可用，新功能不再进 v2）。
- **v3**：架构重构，需 postgres + ClickHouse + Redis + S3/MinIO 多组件，运维重；主线，高吞吐异步摄取、
  ClickHouse 级分析、更强评估/dataset/playground。

同时确定的产品方向：**Langfuse 只做采集后端，Polis 自建产品化可观测页面**（不暴露 Langfuse 自带 UI），
数据分两层（Polis 自有 result_envelope/run_manifest/skill_invocation 基础 + Langfuse LLM 调用级下钻）。

## 选项
1. 直接上 v3 —— 功能最全，但引入 ClickHouse/Redis/MinIO，违背 MVP「复用优先、不引入多余组件」（CLAUDE §1），本地与部署都变重。
2. **用 v2 + 自建观测页** —— 单容器轻量；自建页面只依赖 Langfuse 的采集 + trace 查询 API，v2 完全够。
3. 不用 Langfuse，纯自研采集 —— 重复造轮子，放弃成熟 trace/成本聚合。

## 决定
选 **选项 2**：V1 用 **Langfuse v2**（headless 容器开箱即用，端口 3001），作为**采集后端**；
可观测 UI 由 Polis 自建页面承载。因为自建页面降低了对 Langfuse UI 的依赖，v3 的 UI/分析增强对当前价值有限。

## 后果
- 正面：单容器轻量、契合自建页面方案、不引入 ClickHouse 等重组件；采集 + API 查询满足 V1。
- 负面/代价：v2 维护模式（无新功能）；高 trace 量下 postgres 摄取/分析有上限。
- **升级 v3 触发点**：生产 trace 量大到 postgres 扛不住、或需要 ClickHouse 级跨任务分析、或要 v3 独有功能时；
  届时连同应用容器化（TD-009）+ K8s（V3）一起规划，含 v2→v3 数据迁移。
- 影响范围：`infra/docker-compose.yml`(langfuse v2)、`LiteLLMGateway`(litellm langfuse callback)、
  后续 H-2/H-3 自建观测页（见续接指南 / TD-025）。
