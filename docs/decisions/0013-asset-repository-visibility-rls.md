# ADR-0013：资产仓库三层 + 可见性(public/private) + RLS 读放行演进

- 状态：proposed
- 日期：2026-06-22
- 关联：[V2 · 资产仓库](../design/v2/04-资产仓库（三层·可见性·复用·晋升）.md)；演进 [ADR-0005](0005-multi-tenancy-strategy.md)

## 背景
"虚拟公司越用越聪明"需要可复用资产底座。资产分层、租户可见性（公共/私有/共享）待定，且共享会动多租户 RLS 根基。

## 选项
- 分层：扁平 vs **三层（Skill / 角色模板 / 场景模板）**。
- 可见性：仅私有（V1 干净）/ public+private / + shared（点对点/Marketplace）。
- RLS：保持"按 org 过滤"（无法表达 public）vs **读放行 public**。

## 决定
- **三层资产**：底 Skill（`skill`）/ 中 角色模板（新 `role_template`）/ 上 场景模板（`plan_template` 演进，**一公司可多个**、按 **大类>小类>具体场景** 归类）；横切能力词表。公司蓝图(`scenario_preset`)是正交的"开办启动包"，打包引用仓库资产。
- 复用**按引用 + 版本钉选**；**可组合信任约束**：上层可信度 ≤ 其依赖下层最低（public 资产不得引用任何 private 依赖）。
- 可见性：**V2 做 public + private**；`shared` 仅留枚举位 + `asset_grant` 表留 V3（不实现）。
- **RLS 演进**：**读** = `org_id = current_org OR visibility='public'`；**写**仍严格 `org_id = current_org`（public 由平台/seed 维护）。隔离不打穿（放宽只在读、只放行 public）。

## 后果
- 正面：复用/自增长底座；公共预置 + 组织私有沉淀；隔离根基稳。
- 负面/代价：RLS policy 演进需谨慎 + 隔离回归覆盖（接 M7-T8.3）；新增 `role_template` 表 + 多表加 `visibility/embedding`。
- 影响范围：仓库三层表、RLS、内核检索/沉淀、公司开办(preset)。
