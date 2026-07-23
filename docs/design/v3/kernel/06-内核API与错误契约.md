# 06 内核 API 与错误契约

## 1. 定位

本章定义内核的开发接口，不代表最终用户页面。上层行业产品、旧 Task API、Temporal Activity 和
Outbox Consumer 都应调用 application service；HTTP 只是其中一个适配器。

公开新接口使用 `/api/v1`。现有 `/api/*` 在兼容期保留。

## 2. 通用 HTTP 规则

请求头：

| Header | 要求 |
|---|---|
| `Authorization` | protected route 必填 |
| `X-Org-Id` | 组织接口必填 |
| `Idempotency-Key` | 所有状态变更 POST/PUT 必填，1–128 字符；GET/validate query 不需要 |
| `If-Match` | 修改既有 Definition/Scope/Work 时必填，分别为 revision/scope version/work version；create 不需要 |
| `X-Correlation-Id` | 可选；无则服务生成 |

响应头返回 `ETag: "<target_version>"` 和 `X-Correlation-Id`。Definition 写使用 definition revision，Scope
写使用 scope version，Work 写使用 work version；不得互换或省略。

统一错误：

```json
{
  "error": {
    "code": "WORK_VERSION_CONFLICT",
    "message": "工作已被其他操作更新",
    "details": {
      "expected_version": 4,
      "current_version": 5,
      "allowed_commands": ["request_rework", "cancel_work"]
    },
    "correlation_id": "uuid"
  }
}
```

message 面向人说明原因和下一步；客户端逻辑只依赖 code/details。

## 3. 定义接口

### 3.1 创建草稿

```text
POST /api/v1/kernel/definitions/domain-packages
POST /api/v1/kernel/definitions/work-definitions
POST /api/v1/kernel/definitions/role-definitions
```

Body：

```json
{
  "key": "core.document_review",
  "version": "1.0.0",
  "visibility": "private",
  "definition": {}
}
```

返回 `201` draft。创建同 key/version 用相同 idempotency key 返回原对象；不同内容返回
`IDEMPOTENCY_KEY_REUSED` 或 `DEFINITION_VERSION_EXISTS`。

### 3.2 校验与发布

```text
POST /api/v1/kernel/definitions/{type}/{id}/validate
POST /api/v1/kernel/definitions/{type}/{id}/publish
POST /api/v1/kernel/definitions/{type}/{id}/deprecate
GET  /api/v1/kernel/definitions/{type}/{id}
GET  /api/v1/kernel/definitions/{type}?key=&status=&cursor=&limit=
```

validate 是只读 POST，返回：

```json
{"valid": false, "errors": [{"path": "...", "code": "...", "message": "..."}]}
```

publish 成功后内容不可改。首版不提供 published PATCH；draft 编辑可用
`PUT .../{id}` + If-Match。

上述 create/update/publish/deprecate/compile HTTP 适配器必须分别构造
`DefinitionCommandEnvelope`；不得直接调用 Repository。validate/get/list 是 query，不生成 receipt/event。
组织 `governance_state=uninitialized` 时，写接口仅允许现有 org owner/admin 且仅用于 private definition、
唯一 org_governance Scope 和首批任职；状态 active 后完全按正常任职授权。HTTP 路径不另设无审计
bootstrap 旁路。

### 3.3 编译 bundle

```text
POST /api/v1/kernel/definition-bundles
```

```json
{
  "domain_package_version_id": "uuid",
  "work_definition_version_id": "uuid",
  "role_versions_by_slot": {
    "owner": "uuid",
    "reviewer": "uuid"
  },
  "child_dependencies_by_key": {}
}
```

子依赖值递归使用同一结构，key 集必须与 WorkDefinition 声明完全相等；规则见 11 §7。相同编译 checksum
返回 `200` 现有 bundle；新 bundle 返回 `201`。

## 4. Scope 接口

```text
POST /api/v1/kernel/scopes
PUT  /api/v1/kernel/scopes/{id}
GET  /api/v1/kernel/scopes/{id}
GET  /api/v1/kernel/scopes?scope_type=&parent_scope_id=&cursor=
POST /api/v1/kernel/scopes/{id}/archive
POST /api/v1/kernel/scopes/{id}/relations
POST /api/v1/kernel/scopes/{id}/relations/{relation_id}/end
POST /api/v1/kernel/scopes/{id}/role-assignments
POST /api/v1/kernel/scopes/{id}/role-assignments/{assignment_id}/activate
POST /api/v1/kernel/scopes/{id}/role-assignments/{assignment_id}/suspend
POST /api/v1/kernel/scopes/{id}/role-assignments/{assignment_id}/end
POST /api/v1/kernel/scopes/{id}/schedules/{schedule_id}/cancel
```

Scope 属性必须按 DomainPackageVersion 校验。更新首版仅允许通过专用 command/PUT 修改 display_name 和
attributes，不允许改 scope_type/domain version；需要变化时创建新 Scope 或领域迁移。

`org_governance` 使用同一 Scope API，不增加第四类命令或专用写旁路。create body 必须显式携带平台 seed
`kernel.governance` 的 version ID、`scope_type=org_governance` 和完整 OrgPolicyV1；parent/external_ref 必须
为空。激活该 Scope 的 `kernel.governance_owner` assignment 时，ScopeCommandService 在同一事务写
`org_kernel_setting.governance_scope_id` 并 CAS active。后续 `PUT` 只允许 active 治理 owner 修改
`attributes.kernel_policy`；相同 checksum 返回 `no_state_change`，不增长 ETag/version。

当前 org membership 合同只有 `owner/approver/member`，没有 `admin`；因此 K1 bootstrap 的
“owner/admin”在本仓库中的无歧义映射固定为 `Org.owner_user_id` 且 active `OrgMember.role=owner`。
`approver` 不等同 admin。未来若 org 模块正式增加 admin，必须通过新的协议版本显式扩展，不得在本实现中
预留字符串旁路。

所有写接口构造 `ScopeCommandEnvelope`，使用 Scope ETag。relation body 固定
`to_scope_id/relationship_type/attributes`；调用方不得决定无向关系存储方向。Scope 任职不携带
role_slot_key，因为它绑定 RoleDefinition，不绑定某个工作定义。

## 5. WorkItem 接口

### 5.1 创建

```text
POST /api/v1/work-items
```

```json
{
  "scope_id": "uuid",
  "definition_bundle_id": "uuid",
  "title": "待复核文档",
  "inputs": {"document_artifact_id": "uuid"},
  "priority": 50,
  "due_at": null,
  "parent_work_item_id": null
}
```

返回 `201 WorkItemView`。服务内部转换为 `create_work` Command。

### 5.2 查询

```text
GET /api/v1/work-items/{id}
GET /api/v1/work-items?scope_id=&lifecycle_state=&execution_status=&cursor=&limit=
GET /api/v1/work-items/{id}/timeline?cursor=&limit=
GET /api/v1/work-items/{id}/available-commands
```

WorkItemView 至少包含：

- id/scope/bundle/title；
- lifecycle_state/execution_status/version；
- inputs 中可返回字段；
- active_run；
- role slot 填充摘要；
- pending approvals；
- allowed_commands（仅作为 UX 提示，执行时仍重新鉴权）；
- timestamps。

timeline 合并 Transition/Event/Run/Evaluation/Approval 的安全摘要，不返回敏感 payload。

### 5.3 Work Command 入口

```text
POST /api/v1/work-items/{id}/commands
```

```json
{
  "command_type": "submit_for_review",
  "payload": {}
}
```

version 从 If-Match 获取，actor 从 auth 获取。响应：

```json
{
  "command_id": "uuid",
  "status": "succeeded",
  "work_item": {},
  "events": [{"event_id": "uuid", "event_type": "work.transitioned"}]
}
```

需要审批时返回 `202`：

```json
{
  "command_id": "uuid",
  "status": "awaiting_approval",
  "approval_id": "uuid",
  "work_item": {}
}
```

命令实际修改聚合字段时 version +1 并产生 transition/event。`provide_input` canonical checksum 未变化时
返回 `status=succeeded/no_state_change=true`，WorkItem
version/input_revision 不增长且不产生伪 transition/event。实际变化会使旧 Plan/Approval 失效，响应必须
返回 `invalidated_plan_ids/invalidated_approval_ids`。

## 6. 工作槽位绑定接口

```text
POST /api/v1/work-items/{id}/role-bindings
POST /api/v1/work-items/{id}/role-bindings/{binding_id}/delegate
POST /api/v1/work-items/{id}/role-bindings/{binding_id}/revoke-delegation
POST /api/v1/work-items/{id}/role-bindings/{binding_id}/unbind
GET  /api/v1/work-items/{id}/role-bindings
```

创建 binding 的 body 固定 `role_slot_key/responsible_assignment_id`；责任类型由 bundle slot 决定；delegate body 固定
`executor_kind/executor_ref`。均构造 WorkCommandEnvelope，受 Work If-Match、策略和幂等保护。范围任职由
§4 Scope API 管理；工作 API 不可创建隐式任职。

## 7. 审批接口

```text
GET  /api/v1/approvals?status=pending&work_item_id=&cursor=
GET  /api/v1/approvals/{id}
POST /api/v1/approvals/{id}/decisions
POST /api/v1/approvals/{id}/resume
```

Decision 必须携带 `If-Match` Approval version；resume 不接受新的业务 payload，只读取原 receipt。GET 返回
command_family、purpose、安全摘要、expires_at、version 和可决定角色，不暴露完整 command payload。

Decision body：

```json
{"decision": "approve", "reason_note": "证据与范围已确认"}
```

服务端从 JWT 决定 decided_by。成功决定返回 Approval；是否自动续行由 definition 决定：

HTTP adapter 必须先读取 Approval 的 command_family 与显式目标，再构造且只构造
`decide_definition_approval`、`decide_scope_approval` 或 `decide_work_approval`；请求 body 不能选择 family、
target 或 command_type。family envelope 的 expected target version 必须取 Approval/原 receipt 保存的版本，
不得替换为当前版本以掩盖 stale。后台过期/撤销同理构造对应
`expire_*_approval/revoke_*_approval`。不存在通用
`decide_approval` application 命令。

- `resume_mode=manual`：调用方 POST resume，不提交原 payload；服务读取 receipt；
- `resume_mode=automatic`：写 outbox，以原 command fingerprint 衍生幂等键重发。

旧 `/api/approvals/{id}/decide` 在适配器中映射到新接口。

## 8. 内部服务接口

application service 必须使用以下类型化方法：

```python
class DefinitionCommandService(Protocol):
    async def handle(self, command: DefinitionCommandEnvelope) -> CommandResult: ...

class ScopeCommandService(Protocol):
    async def handle(self, command: ScopeCommandEnvelope) -> CommandResult: ...

class WorkCommandService(Protocol):
    async def handle(self, command: WorkCommandEnvelope) -> CommandResult: ...

class DefinitionValidator(Protocol):
    async def validate_version(...) -> DefinitionValidationResult: ...

class DefinitionCompiler(Protocol):
    async def compile_bundle(...) -> DefinitionBundleView: ...

class KernelQueryService(Protocol):
    async def get_work_item(...) -> WorkItemView: ...
    async def list_timeline(...) -> CursorPage[TimelineItem]: ...

class ActorResolver(Protocol):
    async def resolve(...) -> ResolvedActor: ...

class ExecutionPort(Protocol):
    async def ensure_workflow_started(...) -> ExternalStartResult: ...
    async def request_cancel(...) -> None: ...
```

`DefinitionValidator/DefinitionCompiler` 是无 session、无 commit、无持久化的纯内部组件；发布与编译写入
只能由 DefinitionCommandService 完成。Repository 不 commit；三个 application service 按 02 §6 控制 T1/T2 事务。Domain 纯函数接收已解析对象，
不持有 session。不得再增加接收 `CommandEnvelope` 通用 union 后靠 if/else 分派目标的公开 service。

## 9. 内部消息 topic

首版 topic：

| topic | consumer | 幂等键 |
|---|---|---|
| `kernel.plan.requested.v1` | Planner adapter | event_id |
| `kernel.run.start.v1` | Temporal adapter | execution_run_id |
| `kernel.run.cancel.v1` | Temporal adapter | execution_run_id + cancel |
| `kernel.evaluation.requested.v1` | Evaluator | run/result + rule version |
| `kernel.trigger.evaluate.v1` | Trigger worker | event_id |
| `kernel.approval.resume.v1` | Command worker | approval_id |
| `kernel.command.schedule.v1` | Scheduler | schedule_id + version |
| `kernel.shadow.materialize.v1` | Legacy adapter worker | task_id + org kernel config_version |
| `kernel.external_effect.reconcile.v1` | Effect reconciler | external_effect_receipt_id + version |
| `kernel.trace.publish.v1` | Observability adapter | event_id |

首版只在 PostgreSQL Outbox 内使用 topic，不引入 broker。payload 使用 Pydantic discriminated union。

## 10. 错误目录

| code | HTTP | 含义/下一步 |
|---|---:|---|
| `DEFINITION_INVALID` | 422 | 修复 details 中定义路径 |
| `DEFINITION_NOT_PUBLISHED` | 409 | 先发布或选择已发布版本 |
| `DEFINITION_VERSION_EXISTS` | 409 | 提升版本号 |
| `DEFINITION_IMMUTABLE` | 409 | 创建新版本 |
| `BUNDLE_INCOMPATIBLE` | 422 | 修复 domain/work/role 引用 |
| `BUNDLE_DEPENDENCY_MISSING` | 409/内部 | 父 bundle 未固定子工作依赖，修订并重编译定义 |
| `BUNDLE_DEPENDENCY_CYCLE` | 422 | 修复 compile payload 的子依赖环 |
| `BUNDLE_DEPENDENCY_LIMIT_EXCEEDED` | 422 | 缩短依赖深度或拆分定义，不能放宽平台上限 |
| `SCHEMA_KEYWORD_UNSUPPORTED` | 422 | 只使用 SchemaProfileV1 keyword |
| `CONDITION_TYPE_MISMATCH` | 422/内部 | 修复 condition 两侧类型；不得隐式转换 |
| `MAPPING_SOURCE_MISSING` | 422/内部 | 补齐 required mapping 来源或修订定义 |
| `KERNEL_VERSION_INCOMPATIBLE` | 503 | 升级内核/解释器后重试 |
| `SCOPE_NOT_FOUND` | 404 | 检查组织与 scope |
| `BOOTSTRAP_FORBIDDEN` | 403 | 只有已有 org owner/admin 可完成首次治理启动 |
| `GOVERNANCE_NOT_ACTIVE` | 409 | 先激活治理 Scope owner assignment 完成治理启动 |
| `GOVERNANCE_SCOPE_MISSING` | 409/内部 | 修复治理 Scope 指针、归属或状态，不得回退到默认政策 |
| `GOVERNANCE_SCOPE_EXISTS` | 409 | 使用本组织已有的唯一治理 Scope |
| `GOVERNANCE_SCOPE_PROTECTED` | 409 | 治理 Scope 不允许归档或替换，只能更新其政策 |
| `ORG_POLICY_INVALID` | 422 | 按 OrgPolicyV1 修复字段、范围或枚举 |
| `SCOPE_TYPE_INVALID` | 422 | 使用领域包声明类型 |
| `SCOPE_RELATION_INVALID` | 422 | 修复关系类型、方向、基数或属性 |
| `WORK_NOT_FOUND` | 404 | 工作不存在或不可见 |
| `WORK_VERSION_CONFLICT` | 409 | 刷新后基于最新 version 重试 |
| `WORK_TERMINAL` | 409 | 创建后续 WorkItem，不重开终态 |
| `TRANSITION_NOT_ALLOWED` | 409 | 查看 allowed_commands |
| `GUARD_NOT_SATISFIED` | 422 | 补足 details 指定输入/条件 |
| `POLICY_DENIED` | 403 | 无法执行，查看 reason codes |
| `APPROVAL_REQUIRED` | 202 | 等待或完成审批 |
| `APPROVAL_INVALID` | 409 | 内容/version 已变化，重新申请 |
| `APPROVAL_EXPIRED` | 409 | 重新申请 |
| `APPROVAL_STALE` | 409 | version/input/危险字段已变化，重新发起原动作 |
| `APPROVAL_VERSION_CONFLICT` | 409 | 刷新 Approval 后基于最新 version 决定 |
| `ASSIGNMENT_MISSING` | 409 | 给 required role slot 任职 |
| `ASSIGNMENT_CONFLICT` | 409 | 解决职责分离/容量/时间冲突 |
| `CAPACITY_EXHAUSTED` | 409 | 等待/释放保留或选择有容量的任职 |
| `BUDGET_RESERVATION_FAILED` | 409/202 | 按策略拒绝或进入精确审批 |
| `EXTERNAL_EFFECT_UNCERTAIN` | 409/内部 | 禁止自动重试，先对账外部系统 |
| `ARTIFACT_NOT_READY` | 409 | 完成上传校验后再引用 |
| `ARTIFACT_CHECKSUM_MISMATCH` | 422/内部 | Artifact 转 quarantined，不创建成功 Result |
| `CAPABILITY_UNSATISFIED` | 422 | 更换有效任职或补已发布 Skill |
| `INPUT_SCHEMA_INVALID` | 422 | 修复输入 |
| `PLAN_INVALID` | 422 | 修复 DAG/role slot/预算 |
| `PLAN_STALE` | 409 | Work version/input/binding 已变化，重新规划或接受 |
| `RUN_ALREADY_ACTIVE` | 409 | 等待、暂停或取消当前 Run |
| `RUN_OUTCOME_STALE` | 409 | 迟到结果已归档 |
| `RESULT_SCHEMA_INVALID` | 422 | 执行输出不符合定义 |
| `EVALUATION_PENDING` | 409 | 等待评价 |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | 提供 header |
| `IDEMPOTENCY_KEY_REUSED` | 409 | 不同请求使用新 key |
| `COMMAND_IN_PROGRESS` | 409 | 按 Retry-After 重试 |
| `COMMAND_FAMILY_MISMATCH` | 422 | 使用命令目录指定的信封/API |
| `SCHEDULE_ALREADY_DISPATCHED` | 409 | 已派发；需要时取消目标工作 |
| `SCHEDULE_TARGET_CHANGED` | 409/内部 | 计划创建后目标已变化；由新业务命令重新安排 |
| `SCHEDULE_TEMPLATE_CORRUPT` | 内部 | schedule 转 failed、告警，不创建 receipt |
| `TRIGGER_SUPPRESSED` | 409/内部 | 循环/深度保护 |
| `ORCHESTRATOR_UNAVAILABLE` | 503 | Run 已排队，系统自动恢复 |

内部异常不把 SQL、stack、模型 prompt 或凭证返回给客户端；日志使用 correlation_id 关联。

## 11. 兼容旧 API

兼容 API 是当前页面在 K0–K6 期间持续可用的正式合同，不是可以提前删除的临时代码。它的生命周期
和下线条件见 [09 渐进演化与产品连续性](09-渐进演化与产品连续性.md)。

| 旧接口 | 新内部行为 |
|---|---|
| `POST /api/tasks` | 建 Task；flag 开启时创建 legacy WorkItem 和 link |
| `POST /api/tasks/{id}/plan` | `request_plan` Command |
| `POST /api/plans/{id}/approve` | `accept_plan` + `start_work` |
| `GET /api/plans/{id}/run` | 读 ExecutionRun DB 快照；Temporal query 仅补 node diagnosis |
| `POST /api/plans/{id}/signal` | 决定 Approval 或发送受控 human command |
| `POST /api/approvals/{id}/decide` | 新 decisions adapter |

兼容层不得继续直接调用 `update_plan_status`/`update_task_run_status`。K3 之后若发现直接写，架构测试失败。
