# ADR-0016：显式 Command 家族与运行协议闭合

- 状态：accepted
- 日期：2026-07-21
- 关联：[第三轮稳定内核开发规格](../design/v3/kernel/README.md)
- 前置：[ADR-0015](0015-stable-kernel-and-definition-bundle.md)

## 背景

ADR-0015 固定了稳定内核、三个定义聚合根和不可变 `DefinitionBundle`，但首版规格仍把所有写操作
放入一个以 `work_item_id` 为中心的 Command 信封。定义发布、Scope 关系、范围任职和 WorkItem 转换
具有不同目标、版本字段、锁与事件；强行通用化会产生可空字段、分支推断和无法确定的事务边界。

同时，审批后的原命令续接、定时命令、子工作版本、责任与执行者分离、输入快照和新旧内核模式尚未
形成一组相互闭合的协议。若把这些选择留给实现者，不同模块会得到互不兼容的答案。

## 选项

1. 使用一个 `aggregate_type + aggregate_id` 通用信封，由 handler 在运行时解释目标。
2. 每条命令定义完全独立的请求模型，不共享任何头字段和基础设施。
3. 共享不可变 `CommandHeader`，显式定义 Definition、Scope、Work 三类信封、目录和处理管线。

## 决定

采用选项 3，并固定以下规则：

1. Command 只存在三个家族：`DefinitionCommandEnvelope`、`ScopeCommandEnvelope`、
   `WorkCommandEnvelope`；禁止增加对外的通用聚合信封。
2. 三类信封只共享身份、幂等、追踪和时间字段；目标 ID、预期版本、定义固定信息及 payload 均由各自
   信封明确声明，不使用 `target_type/target_id` 组合。
3. 三个 handler 共享 receipt、策略、审计和 outbox 基础设施，但分别锁定 DefinitionVersion、Scope
   或 WorkItem，并发布 `definition.*`、`scope.*`、`work.*` 事件。
4. `ScopeRelation`、`ScopeRoleAssignment`、`WorkRoleBinding`、`WorkSnapshot`、`ScheduledCommand` 和
   `CommandReceipt` 是运行协议对象，不是新的可独立发布元模型。
5. `ScopeRoleAssignment` 表达在范围内承担责任；`WorkRoleBinding` 把有效任职绑定到具体工作槽位。
   责任类型由 RoleSlot 唯一决定，executor 仅表达委派。能力路由不得替代责任绑定。
6. 需要审批的命令先持久化为 `CommandReceipt(status=awaiting_approval)`；审批决定只改变 Approval，
   随后由确定的 manual/automatic 续接规则恢复同一 receipt。不得从日志或客户端临时重构原命令。
7. 定时执行通过持久化 `ScheduledCommand`，只保存某一具体家族的已验证命令模板；调度器只能派生
   新 command_id/idempotency_key 和 requested_at，不能改变业务 payload。
8. 子工作使用父 bundle 编译时固定的 `child_work_bundle_dependencies`；运行时不得查询“最新发布版”。
9. WorkItem 采用本规格定义的双状态合法组合与转换表；同一工作只允许一个活动 Run。
10. 迁移模式使用持久化的组织级 `kernel_mode` 和实例级 `execution_mode`，不由进程环境变量或是否
    存在某个外键推断。
11. Approval 与 ScheduledCommand 的状态所有权、确定性声明语言和外部副作用安全按 ADR-0017 展开，
    不因此增加 Command family 或定义根。

## 后果

正面：

- 每条请求的验证、锁、版本冲突、事件和恢复路径可以静态确定；
- Scope 配置、定义发布和工作执行不再被迫经过 WorkItem；
- 审批、调度和重试可在进程崩溃后恢复；
- 自动开发可以从 command_type 唯一定位 schema、handler、状态转换和测试。

代价：

- API/application 层需要三个类型化 command service，而不是一个接收任意聚合的入口；
- 共享基础设施要通过明确接口复用，不能靠包含大量可空字段的基类复用；
- 增加若干运行态表和交叉约束，迁移与集成测试数量上升。

## 禁止的实现简化

- 不得合并成 `GenericCommandEnvelope`、`aggregate_type` 或任意 JSON target；
- 不得把 Scope 任职与 Work 槽位绑定重新合为一个可空字段表；
- 不得在 Approval 中只保存 command fingerprint 而丢失可恢复的命令引用；
- 不得让 scheduler、Trigger、Temporal 或兼容适配器直接更新聚合状态；
- 不得在运行时自动选择最新定义版本创建子工作；
- 不得使用 JSONB 替代本 ADR 明确要求的关键 FK、状态列和唯一约束。
