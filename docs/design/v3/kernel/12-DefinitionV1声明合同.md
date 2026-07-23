# 12 Definition V1 声明合同

## 1. 地位与适用范围

本章是 V3.4 对三个 Definition JSON 及其内嵌值对象的唯一结构合同，关闭 K1-T1 实现发现的字段、默认值、
枚举、Effect payload 和 Mapping 上限缺口。若 01、02、08 的旧示例省略本章必填字段，以本章、11 和
`protocol-manifest.yaml` 为准。三个 Definition 仍是唯一可独立发布的定义聚合根；本章不新增第四个定义根。

所有对象使用 Pydantic V2 `strict=true, extra=forbid`。标为“必填”的字段即使值为空数组或 `null` 也必须
出现在输入 JSON 中；首版不使用会在验证时静默补出的业务默认值。`schema_version` 和
`definition_kind` 也必须显式提供。验证后的完整 JSON 按 11 §2 计算 checksum。

## 2. 公共标量与闭集

### 2.1 Key 与版本

- `KeyV1`：`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`；用于定义、能力、工具、数据范围、策略和命令 key；
- `LocalKeyV1`：`^[a-z][a-z0-9_]*$`；用于单个 Definition 内的 state、slot、rule、trigger、dependency key；
- `ReasonCodeV1`：`^[A-Z][A-Z0-9_]*$`；
- Definition row 的 `version` 只接受无前缀、无预发布/构建段的 `MAJOR.MINOR.PATCH`，各段禁止多余前导零；
- 字符串长度不在协议层任意截断；数据库使用 `TEXT`，规范 JSON 总大小和各 AST 上限承担资源保护。

### 2.2 固定枚举

```text
definition_kind: domain_package | role | work
visibility:      public | private
risk_level:      low | medium | high | critical
actor_kind:      human | agent | service
policy_decision: allow | deny | require_approval
cardinality:     one_to_one | one_to_many | many_to_one | many_to_many
responsibility:  accountable | contributor | reviewer | observer
execution_policy: responsible_actor_only | delegation_allowed | autonomous
inheritance_mode: none | nearest | merge
state_category:  open | active | success | failure | cancelled
evaluation_outcome: pass | rework | human_review | fail
misfire_policy:  fire_once | skip
```

数据库 check、Pydantic Literal、fixture 与 `protocol-manifest.yaml` 必须来自同一枚举源。

## 3. DomainPackageDefinitionV1

全部字段必填：

| 字段 | 类型与约束 |
|---|---|
| `schema_version` | integer，const `1` |
| `definition_kind` | const `domain_package`；参与 checksum |
| `key` | KeyV1 |
| `display_name` | 非空 string |
| `scope_types` | `ScopeTypeV1[]`，至少一项，key 唯一 |
| `relationship_types` | `RelationshipTypeV1[]`，key 唯一，可空 |
| `policy_defaults` | `DomainPolicyDefaultsV1` |
| `compatible_work_definition_keys` | 去重后的 KeyV1[] |
| `compatible_role_definition_keys` | 去重后的 KeyV1[] |

`ScopeTypeV1`：`key:LocalKeyV1`、`parent_types:LocalKeyV1[]`、`attributes_schema:SchemaProfileV1`。
每个 parent 必须在同一定义中存在，父图无环。

`RelationshipTypeV1`：`key:LocalKeyV1`、`from_scope_types:LocalKeyV1[]`、
`to_scope_types:LocalKeyV1[]`、`cardinality`、`directed:boolean`、
`attributes_schema:SchemaProfileV1`。from/to 数组至少一项，且全部引用本定义 scope type。

`DomainPolicyDefaultsV1` 仅含 `unknown_action`、`dangerous_action`，二者均为 `policy_decision`。平台硬策略
仍可把领域 allow 收紧为 deny/require_approval，不能被该对象放宽。

## 4. RoleDefinitionV1

全部字段必填：

| 字段 | 类型与约束 |
|---|---|
| `schema_version` | integer，const `1` |
| `definition_kind` | const `role`；参与 checksum |
| `key/display_name/mission` | KeyV1 / 非空 string / 非空 string |
| `accountabilities` | 非空 string[]，至少一项 |
| `required_capabilities` | 去重后的 KeyV1[] |
| `authority` | `RoleAuthorityV1` |
| `collaboration` | `RoleCollaborationV1` |
| `quality_bar` | `RoleQualityBarV1` |
| `capacity` | `RoleCapacityV1` |

`RoleAuthorityV1`：

| 字段 | 类型与约束 |
|---|---|
| `commands/tools/data_scopes` | 去重后的 KeyV1[]；可空 |
| `max_risk_level` | risk_level |
| `budget_cents` | integer，`0..1_000_000_000_000_000` |

`RoleCollaborationV1` 含 `receives_from/hands_off_to/escalates_to:LocalKeyV1[]`，都允许空数组；这些 key
表示 WorkDefinition slot，不在 RoleDefinition 发布时跨定义解析，在 bundle 编译时解析。

`RoleQualityBarV1.evaluation_rule_keys:LocalKeyV1[]` 允许空；bundle 编译时必须存在于目标 WorkDefinition。
`RoleCapacityV1.max_active_work_items` 为 `1..10_000`。

## 5. WorkDefinitionV1

全部字段必填：

| 字段 | 类型与约束 |
|---|---|
| `schema_version` | integer，const `1` |
| `definition_kind` | const `work`；参与 checksum |
| `key/display_name` | KeyV1 / 非空 string |
| `supported_scope_types` | 非空、去重 LocalKeyV1[] |
| `input_schema/result_schema` | SchemaProfileV1 |
| `assignment_mode` | `fixed/elastic` |
| `role_slots` | RoleSlotV1[]；至少一个 accountable slot |
| `state_machine` | StateMachineV1 |
| `policy_bindings` | PolicyBindingV1[] |
| `planning_profile` | PlanningProfileV1 |
| `execution_profile` | ExecutionProfileV1 |
| `evaluation_rules` | EvaluationRuleV1[]；至少一项 |
| `evaluation_default_outcome` | evaluation_outcome |
| `human_review_reject_action` | `rework/fail` |
| `child_dependencies` | ChildDependencyV1[] |
| `triggers` | TriggerV1[] |

同类内嵌对象的 `key` 必须唯一。数组顺序具有语义并参与 checksum：state/transition 顺序用于解释与展示，
policy 按全部匹配合并，evaluation rule 按声明顺序 first-match，trigger 按声明顺序产生独立 receipt。

### 5.1 RoleSlotV1

全部字段必填：`key`、`role_definition_key`、`required`、`min_assignments>=0`、
`max_assignments>=1`、`responsibility_kind`、`execution_policy`、`inheritance_mode`、
`allowed_actor_kinds:actor_kind[]`、`separation_of_duties_from:LocalKeyV1[]`、
`required_for_commands:KeyV1[]`、`assignment_policy_keys:KeyV1[]`。

`min_assignments <= max_assignments`；required/accountable 的 min 至少 1；allowed_actor_kinds 不得为空；SoD
不得引用自身，所有引用 slot 必须存在，SoD 按无向冲突处理。

### 5.2 StateMachineV1 与 EffectV1

StateMachineV1：

```text
initial_state: LocalKeyV1
states: [{key, terminal:boolean, category:state_category}, ...]
transitions: [WorkTransitionV1, ...]
```

WorkTransitionV1 全部字段必填：`key`、`command_type:KeyV1`、`from:LocalKeyV1[]`（非空）、
`to:LocalKeyV1`、`required_role_slots:LocalKeyV1[]`、`guards:ConditionExprV1[]`、
`policy_keys:KeyV1[]`、`effects:EffectV1[]`。state/slot/policy 引用必须存在，command_type 在本定义唯一；
初始状态存在、至少一个 terminal、terminal 的 category 只能是 success/failure/cancelled，非 terminal 只能是
open/active。可达性与固定 execution matrix 在 compiler 校验。

EffectV1 是以 `type` 为 discriminator 的闭集，所有未列字段拒绝：

| type | 额外必填字段 |
|---|---|
| `request_plan` | 无 |
| `start_run` | 无 |
| `cancel_run` | `reason_code:ReasonCodeV1` |
| `request_evaluation` | `evaluation_rule_keys:LocalKeyV1[]`，非空且引用本定义 |
| `request_approval` | `approval_purpose:command_policy/execution_gate/quality_review`、`required_role_slots:LocalKeyV1[]`、`ttl_seconds:60..604800` |
| `emit_event` | `event_type:KeyV1`（必须含点号）、`payload_mapping:MappingExprV1` |
| `create_child_work` | `dependency_key:LocalKeyV1`、`input_mapping:MappingExprV1` |
| `schedule_command` | `command_type:KeyV1`、`delay_seconds:1..604800`、`timezone:IANA zone`、`misfire_policy`、`payload_mapping:MappingExprV1` |

schedule 只派发当前 Work family 的同一 `work_item_id/definition_bundle_id`；不得从 Work transition 调度 Scope
或 Definition 命令。运行时 schedule key 固定为
`{work_item_id}:{transition_key}:{effect_index}:{target_version}:{correlation_id}`。

### 5.3 PolicyBindingV1

全部字段必填：`key`、`applies_to_commands:KeyV1[]`（非空）、`when:ConditionExprV1[]`、`decision`、
`required_role_slots:LocalKeyV1[]`、`approval_ttl_seconds:integer|null`、`reason_code`。

decision=require_approval 时 ttl 必须 `60..604800` 且 required slots 非空；其他 decision 的 ttl 必须 null。
Policy 禁止 `event_field_matches/evaluation_outcome_is`，路径还须通过 03 章 policy 子路径白名单。

### 5.4 PlanningProfileV1

全部字段必填且首版无其他模式：

```json
{
  "mode": "required",
  "max_nodes": 64,
  "max_parallel_nodes": 8,
  "max_replans": 1,
  "acceptance": "required"
}
```

限制：mode/acceptance 为 const；`max_nodes 1..256`、`max_parallel_nodes 1..64` 且不大于 max_nodes、
`max_replans 0..3`。禁止通过 Definition 绕过 accepted Plan 后启动的固定协议。

### 5.5 ExecutionProfileV1

全部字段必填：

```json
{
  "run_timeout_seconds": 86400,
  "node_timeout_seconds": 3600,
  "heartbeat_timeout_seconds": 60,
  "max_parallel_nodes": 8,
  "max_rework_attempts": 2,
  "retry_policy": {
    "max_attempts": 3,
    "initial_interval_seconds": 1,
    "max_interval_seconds": 60,
    "backoff_multiplier_milli": 2000,
    "retryable_failure_classes": ["dependency_error", "timeout", "infrastructure_error"]
  }
}
```

限制：run `60..604800`；node `1..86400` 且不大于 run；heartbeat 为 null 或 `1..node_timeout`；
parallel `1..64` 且不大于 planning max_parallel_nodes；rework `0..10`。RetryPolicy：attempts `1..10`，
initial `1..3600`，max `initial..86400`，multiplier_milli `1000..10000`。retryable_failure_classes 仅允许
`dependency_error/timeout/infrastructure_error/unknown`；业务拒绝、platform_safety、unexpected_cancel 不得自动重试。

### 5.6 EvaluationRuleV1

全部字段必填：`key:LocalKeyV1`、`when:ConditionExprV1[]`（非空）、`outcome:evaluation_outcome`、
`reason_code:ReasonCodeV1`、`required_evidence_paths:PathV1[]`。Evaluator 按数组顺序选择第一条全部 condition
为 true 的 rule；无匹配使用 `evaluation_default_outcome`。evidence path 必须存在且指向 ready Artifact 引用，
否则该 rule 不匹配并记录稳定诊断。Evaluation rule 禁止 `event_field_matches/evaluation_outcome_is`。

模型 judge 不在此处执行。若需要模型判断，执行层先产生带 model/version/prompt checksum/provenance 的 ready
Result/Artifact，规则只读取该不可变事实；因此相同 snapshot 的解释保持确定性。

### 5.7 ChildDependencyV1 与 TriggerV1

ChildDependencyV1 全部字段必填：`dependency_key:LocalKeyV1`、`work_definition_key:KeyV1`、
`allowed_scope_types:LocalKeyV1[]`（非空）。key 唯一，bundle compile payload 必须按 11 §7 完全匹配。

TriggerV1 全部字段必填：

```text
key: LocalKeyV1
on_event: KeyV1（必须含点号）
conditions: ConditionExprV1[]
emit_command: TriggerCommandV1
max_fires_per_correlation: 1..32
```

TriggerCommandV1：`command_type:KeyV1`、`payload_mapping:MappingExprV1`、
`child_bundle_dependency_key:LocalKeyV1|null`。command_type=create_child_work 时 dependency key 必填并引用
child_dependencies；其他命令必须为 null。Trigger condition 允许 `event_field_matches` 和
`evaluation_outcome_is`；payload 映射结果必须通过目标 command schema。

## 6. MappingExprV1 资源上限

MappingExprV1 延续 11 §6 语义，新增强制资源上限：AST 深度 16、节点 256、规范 JSON 64 KiB。
Object.fields 的 key 是目标 JSON 字段名，可为任意非空 Unicode string，但不得重复；数组中 MISSING 仍按
11 §6 拒绝。ConditionExprV1 保持深度 16、节点 256，并增加规范 JSON 64 KiB 上限。

## 7. Definition discriminator 与数据库交叉校验

`definition_kind` 存在于 Definition JSON 内并参与 checksum；它不是第四个路由字段。Command envelope 的
definition_kind、命令 discriminator、目标物理表和 JSON definition_kind 必须四者一致：

```text
domain_package → domain_package_version → *_domain_package_definition
role           → role_definition_version → *_role_definition
work           → work_definition_version → *_work_definition
```

不一致返回 `DEFINITION_KIND_MISMATCH`，不得尝试根据 JSON 字段猜表或把三个表合并为多态 JSON 表。

## 8. 稳定错误码

本章新增/固定：

```text
DEFINITION_KIND_MISMATCH
DEFINITION_KEY_INVALID
DEFINITION_REFERENCE_UNKNOWN
DEFINITION_ENUM_INVALID
DEFINITION_DUPLICATE_KEY
DEFINITION_LIMIT_EXCEEDED
STATE_UNKNOWN
STATE_CATEGORY_INVALID
TRANSITION_COMMAND_DUPLICATE
EFFECT_TYPE_UNSUPPORTED
EFFECT_PAYLOAD_INVALID
PLANNING_PROFILE_INVALID
EXECUTION_PROFILE_INVALID
EVALUATION_RULE_INVALID
TRIGGER_COMMAND_INVALID
MAPPING_DEPTH_EXCEEDED
MAPPING_NODE_LIMIT_EXCEEDED
MAPPING_SIZE_EXCEEDED
```

错误必须包含 RFC 6901 path；Definition publish/compile 将 Pydantic 原始错误映射为上述稳定码，不向 API 暴露
Python class 名、正则实现或 traceback。

## 9. 实现 Gate

K1-T1 只有同时满足以下条件才完成：

1. 三个 Definition 使用 `definition_kind` discriminated union，合法完整 fixture 往返后 checksum 不变；
2. 本章所有闭集与 `protocol-manifest.yaml`、Pydantic Literal、测试参数完全相等；
3. 缺字段、额外字段、非法枚举、未知 effect、远程 ref、表达式字符串、超 AST/JSON 上限均稳定拒绝；
4. Planning/Execution 交叉上限、RoleSlot/SoD、State 引用、Policy TTL、Trigger child dependency 均测试；
5. fixture 至少包含 Domain、两个 Role、父/子两个 Work，能覆盖 child dependency 和四种 Evaluation outcome；
6. domain 代码不 import FastAPI、SQLAlchemy、Temporal、LiteLLM 或 MCP；
7. K1-T1 不建表、不开放 API、不改变当前产品行为。
