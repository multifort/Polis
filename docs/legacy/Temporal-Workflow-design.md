# 基于 Temporal 的 Workflow 设计（AgentOS Workflow Engine Design Spec）

---

# 1. 概述

## 1.1 定义

在 AgentOS 中，Workflow 是：

> **将用户目标拆解为可执行 DAG，并通过 Temporal 进行可靠调度与状态管理的执行系统。**

Temporal 在这里不是“执行器”，而是：

```text id="tw01"
Reliable Distributed Workflow Runtime
```

---

## 1.2 核心目标

基于 Temporal 的 Workflow 系统解决：

* 长流程任务执行
* 分布式状态管理
* 可恢复执行
* 人工审批插入
* Agent协作编排
* 多Step DAG执行
* 失败补偿机制

---

# 2. Workflow 在 AgentOS 中的位置

## 2.1 系统位置

```text id="tw02"
User Goal
   ↓
Planner Layer
   ↓
Workflow Layer (Temporal)
   ↓
Agent Runtime
   ↓
Skill Runtime
   ↓
External Systems
```

---

## 2.2 职责边界（非常关键）

| 层级                 | 职责    |
| ------------------ | ----- |
| Planner            | 生成DAG |
| Workflow（Temporal） | 执行DAG |
| Agent Runtime      | 智能决策  |
| Skill Runtime      | 执行能力  |

---

# 3. Workflow 总体架构

## 3.1 架构图

```text id="tw03"
                ┌────────────────────────────┐
                │      Planner Layer         │
                └────────────┬───────────────┘
                             │ DAG
                             ▼
┌──────────────────────────────────────────────────────────┐
│                 Temporal Workflow Engine                │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │   Workflow Orchestrator                          │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │   Workflow State Manager                        │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │   Activity Scheduler                            │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │   Event & Signal Handler                        │   │
│  └──────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │   Retry / Compensation Engine                   │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
                             │
                             ▼
                    Agent Runtime Layer
```

---

# 4. Workflow 核心设计思想

---

## 4.1 Workflow = 可恢复 DAG 执行器

Workflow本质：

```text id="tw04"
Deterministic DAG Executor
```

---

## 4.2 Workflow ≠ Agent

| 概念       | 职责   |
| -------- | ---- |
| Workflow | 执行流程 |
| Agent    | 决策智能 |

---

## 4.3 Temporal 在系统中的角色

Temporal负责：

* 状态持久化
* 任务调度
* 重试机制
* 长事务
* 人工审批挂起

---

# 5. Workflow 数据模型

---

## 5.1 Workflow定义

```json id="tw05"
{
  "workflow_id": "wf_001",
  "name": "采购流程",

  "dag": [
    "task_1",
    "task_2",
    "task_3"
  ],

  "nodes": {
    "task_1": {
      "type": "agent_task",
      "agent": "purchase-agent",
      "skill": "erp-query"
    },

    "task_2": {
      "type": "human_task",
      "approval": true
    },

    "task_3": {
      "type": "agent_task",
      "agent": "finance-agent"
    }
  }
}
```

---

## 5.2 Workflow状态

```text id="tw06"
CREATED
RUNNING
WAITING_SIGNAL
PAUSED
FAILED
COMPLETED
```

---

# 6. Workflow Execution Model（执行模型）

---

## 6.1 执行流程

```text id="tw07"
DAG Input
   ↓
Temporal Workflow Start
   ↓
Activity Execution
   ↓
Agent Invocation
   ↓
Skill Execution
   ↓
Return Result
   ↓
Next Node
```

---

## 6.2 Activity类型

### 1. Agent Activity

```text id="tw08"
调用 Agent Runtime
```

---

### 2. Skill Activity

```text id="tw09"
直接调用 Skill Runtime
```

---

### 3. Human Activity

```text id="tw10"
人工审批节点
```

---

### 4. System Activity

```text id="tw11"
系统任务（DB/HTTP）
```

---

# 7. Workflow Orchestrator（编排器）

---

## 7.1 职责

* DAG解析
* Workflow启动
* 分支管理
* 节点调度

---

## 7.2 DAG调度策略

### 1. Sequential

```text id="tw12"
A → B → C
```

---

### 2. Parallel

```text id="tw13"
A || B || C
```

---

### 3. Conditional Branch

```text id="tw14"
if condition:
   A
else:
   B
```

---

### 4. Dynamic DAG

Agent运行时动态扩展节点

---

# 8. Workflow State Manager（状态管理）

---

## 8.1 状态持久化

Temporal提供：

* event sourcing
* snapshot

---

## 8.2 状态结构

```json id="tw15"
{
  "workflow_id": "wf_1",
  "current_node": "task_2",
  "history": [],
  "context": {}
}
```

---

## 8.3 状态恢复

```text id="tw16"
Crash → Replay Event → Restore State
```

---

# 9. Event & Signal System（事件系统）

---

## 9.1 Signal（外部输入）

```text id="tw17"
用户审批通过
```

---

## 9.2 Event（内部事件）

```text id="tw18"
TaskCompleted
TaskFailed
AgentInvoked
```

---

## 9.3 Event Flow

```text id="tw19"
Workflow → EventBus → Workflow Resume
```

---

# 10. Retry & Compensation Engine（核心）

---

## 10.1 Retry机制

```text id="tw20"
max_retry = 3
backoff = exponential
```

---

## 10.2 Compensation（补偿机制）

```text id="tw21"
失败 → 执行补偿Workflow
```

---

### 示例

```text id="tw22"
下单失败
   ↓
取消预留库存
   ↓
通知Agent
```

---

# 11. Human-in-the-loop（人机协同）

---

## 11.1 人工节点

```text id="tw23"
Approval Task
```

---

## 11.2 暂停机制

```text id="tw24"
Workflow → WAITING_SIGNAL
```

---

## 11.3 恢复机制

```text id="tw25"
Signal → Resume Workflow
```

---

# 12. Workflow 与 Agent Runtime关系

---

## 12.1 调用关系

```text id="tw26"
Workflow
   ↓
Agent Runtime
   ↓
Skill Runtime
```

---

## 12.2 职责分离

| 层级       | 职责   |
| -------- | ---- |
| Workflow | 流程控制 |
| Agent    | 智能决策 |
| Skill    | 执行   |

---

# 13. Workflow 与 Planner关系

---

## 13.1 Planner输出

```text id="tw27"
DAG Graph
```

---

## 13.2 Workflow输入

```text id="tw28"
Executable DAG
```

---

## 13.3 转换过程

```text id="tw29"
User Goal
   ↓
Planner
   ↓
DAG
   ↓
Temporal Workflow
```

---

# 14. 多Agent Workflow编排

---

## 14.1 协作模型

### Hierarchical

```text id="tw30"
Manager Agent
   ↓
Worker Agents
```

---

### Pipeline

```text id="tw31"
Agent A → Agent B → Agent C
```

---

### Mesh

```text id="tw32"
A ↔ B ↔ C
```

---

# 15. Workflow容错设计

---

## 15.1 失败类型

* Agent失败
* Skill失败
* External API失败
* Timeout

---

## 15.2 恢复策略

| 类型        | 策略                 |
| --------- | ------------------ |
| transient | retry              |
| logical   | compensation       |
| critical  | human intervention |

---

# 16. Workflow性能设计

---

## 16.1 并发模型

* Workflow级并发
* Node级并发
* Agent级并发

---

## 16.2 扩展能力

Temporal提供：

* horizontal scaling
* worker pool
* queue partition

---

# 17. 技术选型

---

## 17.1 核心组件

* Temporal Server
* Temporal Worker
* Kafka（事件扩展）
* Redis（缓存）
* PostgreSQL（状态）
* K8s（部署）

---

# 18. 与传统系统对比

| 系统               | 能力                 |
| ---------------- | ------------------ |
| Airflow          | 批处理                |
| Camunda          | BPM                |
| LangGraph        | LLM DAG            |
| Temporal         | 企业级分布式Workflow     |
| AgentOS Workflow | Agent + DAG + AI决策 |

---

# 19. Workflow核心价值

---

## 19.1 从“任务执行”升级为“智能流程系统”

---

## 19.2 从“流程编排”升级为“Agent驱动执行系统”

---

## 19.3 从“静态DAG”升级为“动态智能DAG”

---

# 20. 一句话总结

基于 Temporal 的 Workflow 本质是：

> **一个“可恢复、可插入Agent智能决策的企业级分布式流程执行内核”。**

---

如果你下一步继续，我建议补三块最关键的系统级设计（这三块决定能不能“真正做成平台”）：

* 《Planner → DAG生成机制（AgentOS大脑）》
* 《AgentOS全链路执行时序图（端到端）》
* 《Agent Runtime × Workflow × Skill 三者协同执行模型》

这三块是整个系统从“设计”走向“可落地产品”的关键分水岭。
