# ADR-0015：第三轮采用稳定工作内核 + 不可变 DefinitionBundle

- 状态：accepted
- 日期：2026-07-20
- 关联：[第三轮稳定内核开发规格](../design/v3/kernel/README.md)
- 后续协议闭合：[ADR-0016](0016-explicit-command-families-and-runtime-protocol-closure.md)

## 背景

现有 Polis 已具备通用任务拆解、Agent/Skill 管理、计划 DAG、Temporal 执行、记忆、审批与评价。
如果直接在这些能力上增加企业、业务线、项目和行业字段，内核会跟随每个行业和产品形态不断变化；
如果只用自然语言自动生成企业结构，又无法保证真实企业的责任、权限和业务事实。

第三轮需要先固定一套足够小的内核，使创业者创生、现有企业共建和成熟企业嵌入都能使用同一运行
协议，同时避免一次性重写现有 Task/Plan/TaskRun。

## 选项

1. **把企业五主体写入内核**：直接建立 Enterprise/BusinessLine/Project/Task/Role。
   直观，但行业差异会持续侵入核心表和状态机。
2. **继续以 Task/Plan 为中心扩展 JSONB**：改动小，但状态、责任、权限和版本关系继续分散，
   无法形成稳定闭环。
3. **稳定工作内核 + 领域包**：内核固定定义版本、范围、工作、责任、命令、执行、评价和事件；
   企业五主体由领域包映射为 Scope 与 WorkDefinition。

## 决定

采用选项 3，并作以下约束：

- 可独立创作和发布的元数据聚合根只保留
  `DomainPackageVersion`、`WorkDefinitionVersion`、`RoleDefinitionVersion`；
- 状态机、Schema、策略绑定、评价规则、执行配置和触发器先内嵌在 WorkDefinition 中；
- 发布或安装时把所需版本编译为不可变 `DefinitionBundle`；
- WorkItem 创建时固定 bundle，运行中不自动升级；
- 所有 WorkItem 状态变化只由幂等 Command Handler 完成；
- Command 家族、Scope 关系、责任/执行绑定、审批续接、持久调度和迁移模式由 ADR-0016 进一步固定，
  不改变本 ADR 的三个定义聚合根与稳定内核边界；
- PostgreSQL 是业务真相源，Temporal 只负责可靠编排；
- 企业、业务线、项目等业务含义由 `scope_type` 和领域包定义，内核不硬编码；
- 现有 Task/Plan/TaskRun 采用 additive migration 和兼容适配器渐进接入；
- K1–K6 期间保留现有 API、页面和历史数据访问；每阶段以功能开关按 org 灰度，当前产品合同测试
  不通过不得扩量；
- 内核完成不等于旧产品下线；内核稳定后另走 PX 产品交互重构与可用性验证，旧页面下线必须单独 ADR。

只有当某一内嵌定义需要跨多个 WorkDefinition 独立复用、独立授权和独立版本生命周期，且有实际
重复证据时，才允许经新 ADR 提升为顶级元模型。

## 后果

正面：

- 行业和产品变化被限制在领域包与适配器；
- 工作、责任、执行、评价和事件形成可测试闭环；
- 定义与运行固定版本，可审计和重现；
- 可在不破坏现有 API 的情况下渐进迁移。

代价：

- 需要引入 DefinitionBundle、WorkItem、ScopeRoleAssignment、WorkRoleBinding、Command/Event/Outbox 等基础表；
- 现有直接状态更新和能力直路由必须逐步收口；
- 迁移期会存在旧 Task 与新 WorkItem 的双模型，需要明确兼容窗口和对账。

## 不在本 ADR 决定的事项

- 首个商业行业与客户；
- 用户界面和业务术语；
- 领域包市场、计费和发布流程；
- 是否未来拆微服务；
- 某一行业的企业五主体具体 Schema。
