# 04 执行、Temporal 与一致性

## 1. 真相源分工

| 系统 | 负责 | 不负责 |
|---|---|---|
| PostgreSQL | WorkItem 当前状态、定义版本、任职、Plan/Run、结果、评价、审批、事件 | 长时等待与 Activity retry |
| Temporal | 按固定 Plan 编排、等待 signal、超时、重试、崩溃恢复、history | 唯一业务状态、定义选择、权限真相 |
| MinIO | Artifact 正文与导出物 | 状态、权限判断 |
| Langfuse | 模型/Agent trace、token、成本与质量观测 | 业务结果真相 |

用户查询状态必须读 PostgreSQL。Temporal query 只用于诊断，不作为 API 的最终状态来源。

## 2. 执行启动

禁止在 HTTP 数据库事务中先更新为 running，再直接启动 Temporal。正确流程：

```text
start_work Command
→ 锁 WorkItem，完成策略和状态转换
→ 创建 ExecutionRun(status=queued)
→ 写 work.execution_requested + Outbox
→ 提交事务
→ Outbox Worker 启动 Temporal
→ Temporal 首个 Activity 发 record_run_started Command
→ ExecutionRun=running, WorkItem.execution_status=running
```

这样即使 Temporal 不可达，数据库仍保留可恢复的 queued Run，Worker 后续可重试。

### 2.1 Workflow ID

固定为：

```text
work-{work_item_id}-run-{run_sequence}
```

ExecutionRun 上 `(org_id, work_item_id, run_sequence)` 唯一，`temporal_workflow_id` 全局唯一。重复
`start_work` 返回原 Run；Temporal `WorkflowAlreadyStarted` 视为幂等成功并进行对账。

## 3. ExecutionRun 状态

```text
queued → starting → running
                  ├→ waiting
                  ├→ succeeded
                  ├→ partial
                  ├→ failed
                  ├→ timed_out
                  └→ cancelled
```

- `queued`：已在 DB 创建，等待 Outbox；
- `starting`：Worker 已领取，正在启动；
- `running`：Temporal 已确认；
- `waiting`：等待 human signal 或外部条件，仍为活动运行；
- 终态不可反转；
- WorkItem.execution_status 由命令根据活动 Run 派生，不由 SQL trigger 隐式更新。
- Run 进入 succeeded/partial/failed/timed_out 后，WorkItem 必须处于 evaluating 并保留 active_run_id 作为评价目标；该 Run
  已是终态，不计入 task_run 活动唯一索引，评价命令结束后清空引用。
- `cancelled` 只在 Work 已提交 cancel intent 后作为正常 outcome；外部意外取消记
  `failure_class=unexpected_cancel` 并让 Work 进入 evaluating。

## 4. Temporal Workflow 输入

Workflow 启动输入必须是小型、不可变且可重放的引用：

```json
{
  "org_id": "uuid",
  "work_item_id": "uuid",
  "execution_run_id": "uuid",
  "definition_bundle_id": "uuid",
  "plan_id": "uuid",
  "run_manifest_id": "uuid",
  "workflow_schema_version": 1
}
```

不得把完整 Artifact、Memory、凭证、Agent prompt 或可变 DB 行塞入 history。Activity 根据 ID 读取
固定 snapshot。需要在 Workflow 内分支的 Plan 图必须以 Plan snapshot 输入或由首个 Activity 返回
稳定快照，后续不可重新读取可变 Plan。

### 4.1 输入、规划与快照失效

Planner 开始时创建 `WorkSnapshot(phase=planning)`，固定 work version、input revision/checksum、Artifact、
Memory 和有效 binding。Plan 必须保存 `source_work_version/source_input_revision/source_input_checksum/
planning_snapshot_id`。`record_plan_ready` 只接受全部 source 字段仍匹配的 Plan，提交后再写
`registered_work_version` 为增长后的 Work version。`accept_plan` 要求 current_plan_id 匹配、当前 Work version
等于 registered_work_version、input revision/checksum 未变，提交后写 `accepted_work_version`。`start_work`
要求当前 Work version 等于 accepted_work_version；任何介入的 WorkCommand 都必须重新接受或重规划。

`provide_input` 只有 execution_status=idle 时合法；输入 canonical checksum 实际改变才增加 input_revision。
若存在 accepted/ready Plan，命令在同事务把其标记 `superseded(input_changed)`，撤销基于旧 input revision 的
pending/approved Approval，并发 `work.plan_invalidated`。checksum 未变则命令成功但声明
`no_state_change=true`，WorkItem version 不增加，只完成 receipt；不得制造虚假 transition/event。

Run 启动创建 `phase=execution` snapshot；Evaluator 创建 `phase=evaluation` snapshot。三者不可互相覆盖，
每个 phase/attempt/binding 的 snapshot 由唯一键去重。

## 5. RunManifest

启动前必须创建完整 RunManifest：

- DefinitionBundle ID 与 checksum；
- Plan ID、version 与 checksum；
- 每个 role slot 的 WorkRoleBinding ID 与 responsible ScopeRoleAssignment ID；
- 每个执行节点的 Agent ID + AgentVersion ID；
- Skill ID + SkillVersion ID；
- 模型 catalog ID、provider model key 与参数摘要；
- planning/execution WorkSnapshot IDs 与 input revision/checksum；
- Evaluator rule set/version；
- 工具/MCP server 版本；
- Workflow schema/version 和 patch markers；
- kernel contract、definition compiler、condition/policy interpreter 版本；
- 组织/平台 policy revision 与 checksum；
- 预算、超时、重试与平台硬限制；
- 创建时间。

运行时发现 Manifest 引用已 suspended 的执行者：

- 尚未启动：阻止启动并重新进行任职/计划命令；
- 已在运行：平台安全硬禁用可中止；普通停用不改变已固定 run，除非策略明确要求；
- 不得静默换 Agent。需要替换时创建新 attempt/RunManifest。

Run 启动前必须验证 `bundle.min_kernel_version <= running_kernel_version` 且 contract major 相同；解释器低于
bundle 记录版本时返回 `KERNEL_VERSION_INCOMPATIBLE`，Run 保持 queued 并进入运维告警，不降级解释规则。

## 6. Activity 边界

Workflow 内保持确定性。以下全部放 Activity：

- 读写 PostgreSQL；
- 读取 Artifact/Memory；
- AgentRuntime、LiteLLM、MCP 和 Guardrails；
- Context 构建；
- 写 Result/Evaluation；
- 发送内核 Command；
- 任何时间、随机、环境变量与网络 I/O。

每个 Activity 必须：

- 有 `start_to_close_timeout`；
- 长任务有 heartbeat 和 `heartbeat_timeout`；
- 有明确 RetryPolicy，业务拒绝标记 non-retryable；
- 使用 `execution_run_id + node_id + logical_attempt + operation` 幂等；
- 外部工具调用严格使用 11 §11 的 ExternalEffectReceipt；provider 支持时传同一幂等键，不支持且结果
  歧义时标为 uncertain、停止自动重试，不以本地记录冒充外部去重；
- 返回小型引用，不返回大正文。

## 7. 结果与评价顺序

```text
Activity 执行
→ 创建 staging ArtifactDescriptor、上传并校验对象
→ DB 事务将 Artifact ready + 写 ResultEnvelope + 完成 effect receipt
→ 返回 result_id
→ Workflow 聚合节点结果
→ record_run_outcome Command
→ work.execution_* Event
→ Outbox 请求 Evaluation
→ Evaluator 写 EvaluationRecord
→ record_evaluation Command
→ work.evaluation_completed Event
→ Trigger 发 complete_work/request_rework/request_human_review/fail_work Command
```

Result 的状态只能是 `succeeded/partial/failed`。评价 outcome 不能覆盖 Result 原始状态。

MinIO 与 PostgreSQL 不宣称原子写。Result 只能引用 ready Artifact；上传成功而 DB 未提交时按同
artifact id/key 恢复，staging/orphan 由带 checksum 验证的 GC 处理，详见 11 §12。

### 7.1 返工

- `rework` 创建新的 logical attempt，保留原 Result/Evaluation；
- 优先最小作用域：节点返工 → 局部重规划 → 新 Run；
- 上限来自 WorkDefinition，但不能超过平台硬上限；
- 每次返工必须携带上一 Evaluation 的 evidence refs；
- 返工耗尽后只能进入 human_review 或 fail，禁止无界重试。

## 8. Outbox 实现

### 8.1 领取算法

Worker 每批处理：

```sql
SELECT ...
FROM outbox_message
WHERE status IN ('pending','retry')
  AND available_at <= now()
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT :batch_size
```

同一短事务将记录设为 `processing`、增加 attempt 和 lease_until；释放事务后执行外部调用；再用新事务
标记 published 或 retry。不能在持有 DB 行锁时等待 Temporal/网络。

### 8.2 重试

- 指数退避 + jitter；
- 默认最大 12 次，最长退避 15 分钟；
- 明确 4xx/定义错误不重试，转 dead_letter；
- Temporal 不可达、超时和 5xx 可重试；
- dead_letter 必须有指标和人工恢复命令；
- 手工重放不创建新 event_id，保留原消息并增加 replay audit。

## 9. Command 收件幂等

`command_receipt` 状态：

```text
received → processing → succeeded
                      → awaiting_approval → processing → succeeded
                                           ├→ rejected
                                           └→ expired
                      → rejected
```

唯一键 `(org_id, idempotency_key)`。保存 command hash：

- 相同 key + 相同 hash：返回原结果；
- 相同 key + 不同 hash：`409 IDEMPOTENCY_KEY_REUSED`；
- processing 未过 lease：`409 COMMAND_IN_PROGRESS`；
- processing 已过 lease：新处理者可 CAS 领取并重试；
- awaiting_approval 不持 worker lease，必须通过 Approval resume 恢复；
- lease 过期不会把命令业务终结为 expired；只有审批/调度业务 TTL 到期才使用 expired。

## 10. 对账器

对账器是恢复机制，不是正常状态更新的旁路。每次修复仍发 Command。

| 检测 | 修复动作 |
|---|---|
| queued Run 无 outbox | 重建同 idempotency key 的 outbox |
| outbox published，但无 Temporal workflow | 重新幂等启动 |
| Temporal running，DB 仍 starting | `record_run_started` |
| Temporal terminal，DB 仍 active | 读取结果引用，`record_run_outcome` |
| DB Run terminal，Temporal 仍 running，存在 pending execution_gate | 不取消、不反转 Run；标 critical invariant violation，冻结自动动作待人工修复 |
| DB Run terminal，Temporal 仍 running，无 execution_gate | 发幂等 cancel request；quality_review 不得出现该组合 |
| Result 已写，无 Evaluation 请求 | 重建 evaluation outbox |
| Approval 已批准，原 receipt 未继续 | auto 模式重建 resume outbox；manual 模式保持并告警待调用 |
| WorkItem active_run 指向终态 Run，且 Work 不处于 evaluating/quality-review waiting | 发 reconcile command 清理并记录事件 |

对账器按 org 分批扫描，所有查询显式 org_id；修复前检查聚合 version，避免覆盖用户刚完成的动作。
`reconcile_work.payload.action` 只能取下列与表逐行对应的枚举：

```text
rebuild_run_start_outbox
ensure_workflow_started
sync_run_started
sync_run_outcome
request_temporal_cancel
rebuild_evaluation_request
rebuild_approval_resume
clear_stale_active_run
reconcile_external_effect_succeeded
reconcile_external_effect_failed
expire_execution_reservation
```

每个 action 的 `observed_external_ref` 必须等于被修复的 run/result/approval/effect/reservation ID；handler 重新检测表中条件，
条件已消失则返回 no_state_change，不依据扫描器的布尔结论直接写入。

external effect 两个 action 的 observed ref 为 effect receipt ID，且必须携带 provider_ref 与 ready evidence
Artifact；只有 uncertain 可被人工 service actor 处置。reservation action 的 observed ref 为 reservation ID，
只允许 Run 未启动且 lease 已过期时 held→expired；它不得取消正在运行的 Run。

## 11. 故障矩阵

| 故障点 | 数据状态 | 恢复 |
|---|---|---|
| Command 提交前进程崩溃 | 无变更 | 客户端用同幂等键重试 |
| DB 已提交、Outbox 未投递 | queued + pending outbox | Worker 重试 |
| Temporal 启动成功、回写失败 | workflow 存在，Run starting | Worker/对账器 record started |
| Activity 写 Result 后超时 | Result 已存在 | 相同幂等键返回原 Result |
| 无幂等 provider 调用后连接中断 | EffectReceipt uncertain | 停止自动重试，对账/人工确认外部结果 |
| Artifact 上传后 DB 提交失败 | staging/对象存在 | 同 key 校验对象后重试 ready + Result 事务 |
| Temporal 完成、终态 Command 失败 | history terminal，DB active | 对账器补命令 |
| Evaluation 写入后事件失败 | Evaluation 存在 | 唯一键查到后补 record_evaluation |
| Worker 升级导致 history 不兼容 | replay 失败风险 | patch/versioning，先 replay 再发布 |
| MinIO 暂时不可达 | Result 未完整 | Activity 重试，不写伪成功 Result |
| Langfuse 不可达 | 业务仍可继续 | 降级本地 trace ref/outbox，告警 |

## 12. Temporal versioning

任何改变 Workflow command sequence、timer、Activity 名称/参数或分支顺序的代码必须：

1. 使用稳定 patch ID 或新 Workflow type/version；
2. 用旧 Workflow 生成真实 history；
3. 当前代码 Replayer 回放旧 history；
4. 覆盖有在飞 human wait、retry、rework 的 history；
5. 删除 patch 前确认所有旧 history 不再需要 replay，并写 ADR/迁移说明。

Pydantic/Activity payload 只做兼容增加；移除或改义需新 schema_version 和双读期。

## 13. 取消、暂停与人审

- `pause_work`：内核先转 execution_status=waiting，再由 outbox signal Temporal；Activity 需在安全点响应；
- `resume_work`：校验仍有有效任职与权限，再 signal；
- `cancel_work`：DB 先记录取消意图和终态转换，outbox 请求 Temporal cancel；迟到结果仅归档；
- execution gate：Run/Work 均 waiting；Approval 决定先落 DB，再由 outbox 发 Temporal signal；
- quality review：Workflow 已结束，Approval 续接 complete/rework/fail intent，不发送 Temporal signal；
- signal 使用 `approval_id` 幂等，Workflow 维护已处理集合；
- Workflow 不得把“收到 signal”直接视为合法审批，Activity 必须校验 Approval 状态和 fingerprint。

## 14. 并发与公平

- 平台/组织并发上限仍为独立硬限制，不由预算替代；
- 排队顺序以优先级、创建时间和 org 公平权重决定；
- 容量硬上限必须在 start_work 事务通过 ExecutionReservation 保留；预算策略为硬阻断或审批时同样先保留，
  仅告警预算不阻断；
- scheduler 只发 `start_work`/`resume_work` Command，不直接改 Run；
- 同一 WorkItem 不允许两个 active Run；并行节点属于同一个 Run；
- 多 WorkItem 排队由组织级 semaphore/队列控制，最终并发真相是持久化 held reservation，不依赖进程内计数。

## 15. 可观测与告警

至少输出：

- command 处理量、拒绝率、冲突率、P95；
- outbox pending age、retry、dead_letter；
- queued/starting/running Run 数与滞留时间；
- DB/Temporal 状态不一致数量和自动修复数；
- evaluation outcome、rework 次数、人审等待时间；
- trigger suppressed 次数；
- 每 org 成本、token、并发和失败率；
- correlation_id 可从 WorkItem → Command → Event → Run → Trace 全链查询。

告警阈值首版：

- 最老 pending outbox > 5 分钟；
- starting Run > 2 分钟；
- dead_letter > 0；
- 对账不一致连续两轮仍存在；
- 单 correlation trigger depth > 12；
- 人审超过定义 SLA。
