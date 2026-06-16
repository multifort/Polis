# ADR-0005：多租户隔离策略 = 逻辑隔离 + RLS 兜底

- 状态：accepted
- 日期：2026-06-16

## 背景
Polis 是单一共享后台、对外多租户的 Web SaaS：所有城邦(Org)共享一个后台与一个 PostgreSQL，
但各 Org 数据需"分别独立存储"。需定隔离强度与实现方式，并定其落地时机。

## 选项
1. 仅应用层 `org_id` 过滤 —— 轻，但漏写一个 `WHERE org_id` 即串数据，风险高。
2. **逻辑隔离 + PostgreSQL RLS 兜底** —— 同库 `org_id` 行级 + DB 层 RLS 双保险；低运维、纵深防御。
3. schema-per-tenant —— 隔离更强，但连接路由/迁移复杂度上升。
4. 物理分库 —— 隔离最强、运维最重，与"低运维优先"冲突。

## 决定
采用**选项 2**：同一库内 `org_id` 行级隔离（应用层 repo 统一注入过滤）+ **PostgreSQL RLS** 作为数据库层兜底；
每请求经认证中间件 `SET LOCAL app.current_org`，RLS 策略 `USING (org_id = current_setting('app.current_org')::uuid)`。
平台级表(app_user/auth_session/org_invite)不带 org_id、不启用 RLS。
**时机调整**：RLS 从原 V3 提前——基线随 M1 数据底座落地（T9.4），与隔离回归测试(T8.3)同期。
schema-per-tenant / 物理分库**仅在特定大客户合规要求时**按需提供（接口不变）。

## 后果
- 正面：单库低运维 + DB 层兜底，显著降低串租户风险；演进到 schema/物理隔离的接口可保持稳定。
- 负面 / 代价：RLS 需规范连接角色（业务角色 vs `BYPASSRLS` 运维角色）与每请求设会话变量；迁移需为每张业务表生成策略。
- 影响范围：09 身份/多租户、05 记忆、07 部署与路线图（RLS 提前）、研发计划 M1/M2、T8.x/T9.x 任务。
