# ADR-0018：V3 治理 Scope 与 Kernel 模型所有权

- 状态：accepted
- 日期：2026-07-21
- 关联：[V3 稳定内核开发规格](../design/v3/kernel/README.md)
- 前置：[ADR-0015](0015-stable-kernel-and-definition-bundle.md)、
  [ADR-0016](0016-explicit-command-families-and-runtime-protocol-closure.md)、
  [ADR-0017](0017-v3-deterministic-metadata-and-runtime-safety.md)

## 背景

V3 已要求权限决策和资源保留保存组织 policy revision/checksum，但未规定组织政策的唯一持久化位置；
同时 Plan、TaskRun、Approval、RunManifest、ResultEnvelope 和 ArtifactDescriptor 已进入内核语义，ORM 声明
却仍分别由 planner、observability、memory 拥有。前者会迫使实现者自选政策事实源，后者会让 kernel
反向依赖旧模块或重复声明同一数据表。

## 决定

1. 平台以既有 Definition 根 seed `kernel.governance` DomainPackageVersion 和
   `kernel.governance_owner` RoleDefinitionVersion，不增加第四个定义根。
2. 每个组织必须且只能存在一个非归档 `org_governance` Scope；
   `org_kernel_setting.governance_scope_id` 是唯一指针。
3. 组织政策只保存于治理 Scope 的 `attributes.kernel_policy`，严格使用 `OrgPolicyV1`。policy revision 等于
   Scope version，checksum 等于 policy 值对象的 RFC 8785 JCS + SHA-256。
4. `update_scope` 是政策唯一修改入口；运行中的 Plan、Run、Approval 和 Reservation 使用固定 snapshot。
5. `Plan`、`TaskRun`、`RunManifest`、`Approval`、`ResultEnvelope`、`ArtifactDescriptor` 的 SQLAlchemy 声明
   移入 `polis.modules.kernel.models`，保持原表名、主键、数据和迁移历史。
6. planner、observability、memory 的旧 models 模块在兼容期重新导出同一个 class object，不重复创建
   SQLAlchemy Table；`polis.db.models` 显式注册 kernel models 一次。
7. 依赖方向固定为旧模块依赖 kernel；kernel 不得 import 旧模块的 models/service/repository。兼容导出只能
   在 K6 之后通过清理 ADR 移除。

## 后果

组织治理与核心运行数据各自只有一个事实源，自主开发无需选择存储位置或跨模块依赖方向。代价是增加
一个平台 seed、一个组织 Scope 指针和 K0 兼容迁移阶段，但不增加顶级元模型、Command family、数据库表
重写或产品页面改版。

## 禁止的简化

- 不得把组织政策另存到环境变量、Settings JSON 或 DomainPackage 中作为并列事实源；
- 不得允许同一 org 存在两个可用治理 Scope；
- 不得在旧模块和 kernel 同时声明同一 SQLAlchemy table；
- 不得以移动 ORM class 为由重命名或重建既有数据库表；
- 不得让 kernel 为复用旧模型而反向 import planner、observability 或 memory。
