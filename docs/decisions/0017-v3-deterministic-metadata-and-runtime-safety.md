# ADR-0017：V3 确定性元数据与运行安全闭合

- 状态：accepted
- 日期：2026-07-21
- 关联：[V3 声明式协议与运行安全闭合](../design/v3/kernel/11-声明式协议与运行安全闭合.md)
- 前置：[ADR-0015](0015-stable-kernel-and-definition-bundle.md)、
  [ADR-0016](0016-explicit-command-families-and-runtime-protocol-closure.md)

## 背景

三个定义根、三个 Command 家族和 PostgreSQL/Temporal 分工已经确定，但 JSON Schema 子集、条件与映射
语言、子工作编译输入、Approval/Schedule 状态所有权、失败 Run 评价、外部副作用和 Artifact 提交仍存在
多种合理实现。把这些选择留给开发会造成同一 bundle 在不同组件中解释不同，或在重试时重复外部效果。

## 决定

1. 元数据只使用 SchemaProfileV1、RFC 6901 JSON Pointer、类型化 ConditionExprV1/MappingExprV1；
   checksum 统一使用 RFC 8785 JCS + SHA-256。
2. 子工作依赖由 WorkDefinition 声明、compile payload 显式绑定并递归检测 DAG；运行时只读取固定 bundle FK。
3. Approval 与 ScheduledCommand 是三个既有 family 的受控子聚合。每种状态变化由 family 显式命令或唯一
   dispatcher 协议完成，不引入第四类/通用信封。
4. failed/timed_out Run 也进入 Evaluation；execution gate 与 run 完成后的 quality review 分开。
5. 数据库业务效果至多一次；外部 provider 不支持幂等键时不承诺 exactly/at-most-once，歧义结果进入
   `uncertain` 且停止盲重试。
6. Artifact 使用 staging→ready 两阶段协议，成功 Result 只能引用 ready Artifact。
7. RoleSlot 是责任语义唯一来源；ExecutionReservation 持久化容量/预算占用。
8. 组织首次治理复用现有 owner/admin；Definition 写只通过 DefinitionCommandService；shadow 永不阻塞
   已成功的 legacy 业务。
9. `protocol-manifest.yaml` 是实现前的机器一致性清单；生成 schema/代码出现后，CI 必须验证二者完全一致。

## 后果

定义解释、命令恢复和故障结果可以由测试唯一判定；代价是增加若干运行态记录、严格的声明式语法和
更多并发/故障注入测试。该决定不改变 V3 内核边界、顶级元模型数量、Command family 数量或技术栈。

## 禁止的简化

- 不得重新接受 JSONPath、表达式字符串或 provider 特有模板；
- 不得让 Approval/Schedule/Temporal/Artifact worker 直接绕过 family 协议更新业务聚合；
- 不得把本地副作用 receipt 描述成对不支持幂等的外部系统的 exactly-once 证明；
- 不得让 shadow 物化失败回滚已经成功的 legacy 用户请求。
