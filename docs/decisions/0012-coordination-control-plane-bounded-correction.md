# ADR-0012：协同框架=纯控制面 + 有界分级纠错 + 预算只提示

- 状态：accepted（S1–S4 落地，2026-06-27；含未做项见「落地现状」）
- 日期：2026-06-22（accepted 2026-06-27）
- 关联：[V2 · 协同框架](../design/v2/03-协同框架（控制面·状态机·纠错·并发·长时运行）.md)；演进 [ADR-0007](0007-m4-stub-execution-kernel.md)

## 背景
V1 `TaskWorkflow`（Temporal）需升级：任务动态调整、确保不乱、出错能检测并修正、能长时间运行、多任务并发。用户明确：**协同框架是控制面，本身不做任何任务执行**。

## 选项
- 控制/执行边界：控制面内联执行（耦合）vs **纯控制面**（只调用执行面/内核/Evaluator）。
- 错误检测：只测异常（V1）vs **异常 + 质量(judge)**。
- 纠错：无界重试（烧钱）vs **有界分级**（最小作用域优先）。
- 预算：作为派发/并发**闸**（暂停/拒绝）vs **只提示**。

## 决定
- **纯控制面（非任务执行器）**：只做调度/状态机/检测纠错决策/治理；执行交执行面、重规划交内核、质量判定交 Evaluator、人审交审批收件箱。
- **检测**：异常 + **质量门（仅评关键节点）**（judge<τ 为软失败）。
- **分级纠错（有界、最小作用域优先）**：retry → rework(≤1) → local replan(子图,≤1) → escalate(人审) → abort(全任务 replan≤3)；τ≈0.6。每次动态调整后**强制重 validate + 结构不变量**（确保不乱）。
- **预算只提示、不阻断**（接近/超出告警 owner，绝不暂停/降级/拒绝）；**并发是独立的真实限制**（org 并发上限 + 公平）。
- **长时运行**：Temporal 持久 + **workflow versioning(patching)**（解决"改 worker 必重启、在飞任务崩"）+ heartbeat + durable human gate。

## 后果
- 正面：错能自动修复（有界不烧钱）、跑不乱、长跑稳、并发可控；控制/执行清晰解耦。
- 负面/代价：依赖 Evaluator（质量门）与内核（重规划）；workflow versioning 接入与测试成本。
- 影响范围：编排（TaskWorkflow）、Evaluator、内核、审批收件箱、任务记录。

## 落地现状（2026-06-27）
- **S1** ✅ 状态机加 needs_rework/needs_review + 关键节点质量门。
- **S2** ✅ ② rework（反馈重跑同节点 ≤1）+ ④ escalate（建 rework 审批，超界交人）。
  **③ local replan（重生成失败子图→validate→拼接）未做**——异常仍走 V1 `_bounded_replan`（删节点修依赖的粗版），列为 S2 剩余。
- **S3** ✅ 并发真实闸（org 在跑数达 `org_max_concurrent_runs`→429，最简 reject-when-full）+ 预算只提示（超 `org_budget_cents`→warning 日志，不阻断）。
  **排队/FIFO 公平调度 + 完成自动 dequeue、收件箱预算告警 UI、实际成本聚合** 未做——列为 S3 剩余。
- **S4** ✅ 长 activity heartbeat（`run_node` 后台周期 heartbeat + `heartbeat_timeout` → worker 崩溃快速重试）；human gate durable wait（V1 已有）；Temporal 持久（天然）。
  **workflow versioning 作为纪律确立**：自下次改编排代码起用 `workflow.patched()` 守新分支；本次未对既有分支追加 patch（已部署、无在飞任务受影响）。
