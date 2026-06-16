# AgentOS详细架构设计说明书（V1.0）

---

# 1. 文档目标

本文档定义 AgentOS（Multi-Agent Operating System）核心架构设计。

目标：

构建企业级 Agent 运行平台，实现：

* 多Agent协同
* Agent生命周期管理
* Agent编排调度
* Tool/Skill统一管理
* 长流程执行
* Memory管理
* 模型治理
* 企业级审计与运维

---

# 2. AgentOS总体架构

## 2.1 整体架构图

```text
┌───────────────────────────────────────────────────────────────┐
│                    Portal / Chat / API                        │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                    Organization Center                         │
│ Tenant │ Workspace │ User │ Role │ Permission │ Policy        │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                     Agent Management                           │
│ Agent Registry │ Agent Version │ Agent Policy │ Agent Market  │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                      Planning Center                           │
│ Goal Planner │ Task Planner │ DAG Planner │ Human Approval    │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                     Workflow Runtime                           │
│          Temporal Workflow Engine                              │
└───────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                      Agent Runtime                             │
│ Scheduler │ Lifecycle │ Communication │ State Manager         │
└───────────────────────────────────────────────────────────────┘
               │                │                 │
               ▼                ▼                 ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Memory Center  │ │ Tool Runtime   │ │ Model Runtime  │
└────────────────┘ └────────────────┘ └────────────────┘
               │                │                 │
               └────────────┬───┴────────────┬────┘
                            ▼                ▼
                   ┌─────────────────────────────┐
                   │      Data Infrastructure     │
                   └─────────────────────────────┘

┌───────────────────────────────────────────────────────────────┐
│                    Observability Center                        │
│ Trace │ Audit │ Cost │ Evaluation │ Alert                     │
└───────────────────────────────────────────────────────────────┘
```

---

# 3. 系统分层设计

AgentOS分为10层：

| 层级  | 模块                     | 职责        |
| --- | ---------------------- | --------- |
| L1  | Portal Layer           | 用户入口      |
| L2  | Organization Layer     | 组织管理      |
| L3  | Agent Management Layer | Agent管理   |
| L4  | Planning Layer         | 任务规划      |
| L5  | Workflow Layer         | DAG调度     |
| L6  | Agent Runtime Layer    | Agent运行   |
| L7  | Knowledge Layer        | 上下文/记忆/知识 |
| L8  | Tool Runtime Layer     | Skill执行   |
| L9  | Model Runtime Layer    | 模型调用      |
| L10 | Observability Layer    | 监控治理      |

---

# 4. Organization Center

---

## 4.1 职责

负责：

```text
组织
租户
用户
角色
权限
工作空间
Agent归属
```

---

## 4.2 组件图

```text
Organization Center

├── Tenant Service
├── Workspace Service
├── User Service
├── Role Service
├── Permission Service
└── Policy Service
```

---

## 4.3 数据模型

```text
Tenant
 ├── Workspace
 │     ├── User
 │     ├── Role
 │     └── Agent
```

---

# 5. Agent Management Center

---

## 5.1 Agent定义

Agent是平台核心资源。

Agent ≠ Role

例如：

```text
Role:
采购经理
```

对应：

```text
Agent:
询价Agent
评估Agent
采购执行Agent
```

---

## 5.2 组件图

```text
Agent Registry

├── Agent Definition
├── Agent Version
├── Agent Template
├── Agent Marketplace
├── Prompt Center
├── Capability Center
└── Agent Policy Center
```

---

## 5.3 Agent元模型

```yaml
Agent:
  id:
  name:
  version:

  prompt:

  skills:

  memory:

  model:

  permissions:

  owner:

  status:
```

---

# 6. Planning Center

---

## 6.1 职责

负责：

```text
目标理解
任务拆解
DAG生成
风险分析
成本分析
```

---

## 6.2 组件图

```text
Planning Center

├── Goal Planner
├── Task Planner
├── DAG Planner
├── Cost Planner
├── Risk Planner
└── Human Approval
```

---

## 6.3 工作流程

```text
用户目标

↓

Goal Planner

↓

Task Planner

↓

DAG Planner

↓

Workflow
```

---

# 7. Workflow Runtime

---

## 7.1 组件图

```text
Workflow Runtime

├── Temporal Server
├── Workflow Worker
├── Activity Worker
├── Event Bus
└── Scheduler
```

---

## 7.2 DAG状态机

```text
Created

↓

Running

↓

Waiting

↓

Paused

↓

Completed
```

---

## 7.3 核心职责

```text
长流程管理

状态持久化

重试

超时

补偿

人工审批
```

---

# 8. Agent Runtime

这是整个系统核心。

---

## 8.1 架构图

```text
Agent Runtime

├── Agent Scheduler
├── Agent Lifecycle Manager
├── Agent Communication Bus
├── Agent State Manager
├── Agent Resource Manager
└── Agent Executor
```

---

## 8.2 Agent生命周期

```text
Registered

↓

Ready

↓

Running

↓

Suspended

↓

Completed

↓

Archived
```

---

## 8.3 Agent通信

支持：

### Message

```text
AgentA
 ↓
Message
 ↓
AgentB
```

---

### Event

```text
AgentA

发布事件

↓

Event Bus

↓

AgentB
```

---

### Shared Memory

```text
AgentA
 ↓
Memory
 ↓
AgentB
```

---

# 9. Knowledge Center

---

## 9.1 架构图

```text
Knowledge Center

├── Session Center
├── Memory Center
├── Knowledge Center
└── Vector Retrieval
```

---

## 9.2 Session Center

管理：

```text
会话上下文
```

生命周期：

```text
会话结束即销毁
```

---

## 9.3 Memory Center

管理：

```text
Agent长期记忆
```

例如：

```text
客户偏好

供应商信誉

历史经验
```

---

## 9.4 Knowledge Center

管理：

```text
文档

制度

流程

FAQ
```

---

# 10. Tool Runtime

---

## 10.1 架构图

```text
Tool Runtime

├── Skill Registry
├── MCP Runtime
├── API Runtime
├── Human Runtime
├── Code Runtime
└── Workflow Runtime
```

---

## 10.2 Skill分类

### API Skill

```text
ERP查询
MES查询
CRM查询
```

---

### MCP Skill

```text
浏览器
数据库
搜索
```

---

### Human Skill

```text
审批
确认
反馈
```

---

### Workflow Skill

```text
启动流程

暂停流程

终止流程
```

---

# 11. Model Runtime

---

## 11.1 架构图

```text
Model Runtime

├── Model Router
├── Prompt Manager
├── Credential Broker
├── Model Gateway
└── Model Backend
```

---

## 11.2 Router策略

根据：

```text
成本

响应时间

能力

可用性
```

自动路由。

---

## 11.3 支持模型

```text
OpenAI

Claude

Gemini

DeepSeek

Qwen

Llama
```

---

# 12. Data Infrastructure

---

## 12.1 数据层架构

```text
Data Layer

├── PostgreSQL
├── Redis
├── MinIO
├── ElasticSearch
└── Milvus
```

---

## 12.2 数据分类

### Metadata

```text
Agent

Workflow

Skill

Role
```

---

### Memory

```text
Embedding
```

---

### Artifact

```text
文件

图片

视频

报告
```

---

# 13. Observability Center

企业级Agent平台必须建设。

---

## 13.1 架构图

```text
Observability

├── Trace Center
├── Audit Center
├── Cost Center
├── Evaluation Center
└── Alert Center
```

---

## 13.2 Trace

记录：

```text
用户

Workflow

Agent

Skill

Model
```

完整调用链。

---

## 13.3 Audit

记录：

```text
Agent行为

审批行为

模型输出
```

---

## 13.4 Cost

统计：

```text
Token

模型费用

Agent费用

部门费用
```

---

## 13.5 Evaluation

评估：

```text
Agent成功率

Skill成功率

Workflow成功率

用户满意度
```

---

# 14. 与你当前架构最大的区别

| 当前架构             | AgentOS优化版                   |
| ---------------- | ---------------------------- |
| Role中心           | Agent中心                      |
| Context Manager  | Session + Memory + Knowledge |
| Skill库           | Tool Runtime                 |
| Executor集合       | Agent Runtime                |
| 单规划器             | Planner Cluster              |
| 无Agent注册中心       | Agent Registry               |
| 无Agent生命周期       | Lifecycle Manager            |
| 无Agent通信层        | Communication Bus            |
| 无可观测体系           | Observability Center         |
| Workflow与Agent耦合 | Workflow与Agent解耦             |

---

# 15. 下一阶段详细设计

建议继续拆解：

### 第一优先级

* Agent Registry详细设计
* Agent Runtime详细设计
* Workflow详细设计

### 第二优先级

* Memory Center详细设计
* Skill Runtime详细设计
* Model Router详细设计

### 第三优先级

* 数据库ER设计
* 微服务拆分设计
* Kubernetes部署架构设计
* SaaS多租户设计

这四部分完成后，基本就达到可以指导研发团队实施的PDR（产品详细设计）级别。
