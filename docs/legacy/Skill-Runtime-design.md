# Skill Runtime 详细设计（Skill Runtime Design Spec）

---

# 1. 概述

## 1.1 定义

Skill Runtime 是 AgentOS 的**工具与能力执行层（Capability Execution Layer）**，负责：

> 将“抽象能力（Skill）”转化为“可执行的标准化能力调用单元”。

它是连接：

```text id="sk01"
Agent Runtime → Tool Execution → External Systems / APIs / Human / Code / MCP
```

的核心桥梁。

---

## 1.2 核心定位

Skill Runtime 在 AgentOS 中的定位是：

> **Agent的“手”和“感官系统”**

---

# 2. Skill Runtime 总体架构

## 2.1 架构图

```text id="sk02"
                ┌────────────────────────────┐
                │     Agent Runtime          │
                └────────────┬───────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────┐
│                 Skill Runtime Core                    │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Skill Registry Service                    │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Skill Router Service                      │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Skill Executor Engine                    │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Skill Adapter Layer                      │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Skill Policy Engine                      │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
                             │
         ┌───────────────────┼────────────────────┐
         ▼                   ▼                    ▼
┌──────────────┐   ┌────────────────┐   ┌────────────────┐
│ MCP System   │   │ API System     │   │ Human System   │
└──────────────┘   └────────────────┘   └────────────────┘
         │                   │                    │
         ▼                   ▼                    ▼
   External Tools       Enterprise APIs       Human-in-loop
```

---

# 3. Skill Runtime 核心设计思想

---

## 3.1 Skill = 标准化能力单元

Skill不是函数，而是：

```text id="sk03"
Declarative + Executable Capability Unit
```

---

## 3.2 Skill = 可编排能力

Skill必须支持：

* 调用
* 组合
* 编排
* 复用
* 版本控制

---

## 3.3 Skill = 可治理资源

Skill必须支持：

* 权限控制
* 审计
* 限流
* 成本控制

---

# 4. Skill 定义模型

---

## 4.1 Skill基础结构

```yaml id="sk04"
skill:
  id: erp-query
  name: ERP Query Skill

  version: 1.0.0

  description: 查询ERP系统数据

  type: api

  input_schema:
    type: object
    properties:
      sql:
        type: string

  output_schema:
    type: object

  endpoint:
    url: http://erp-service/query
    method: POST

  auth:
    type: token

  timeout: 3000

  retry:
    max: 3

  policy:
    rate_limit: 100/min
    data_scope: internal

  cost:
    token_cost: 0
    api_cost: low

  tags:
    - enterprise
    - data
```

---

## 4.2 Skill类型

```text id="sk05"
Skill =
  API Skill
+ MCP Skill
+ Code Skill
+ Human Skill
+ Workflow Skill
+ Hybrid Skill
```

---

# 5. Skill Registry（技能注册中心）

---

## 5.1 职责

管理：

* Skill注册
* Skill版本
* Skill权限
* Skill元数据
* Skill生命周期

---

## 5.2 架构

```text id="sk06"
Skill Registry

├── Skill Definition Store
├── Skill Version Manager
├── Skill Metadata Index
├── Skill Capability Index
└── Skill Marketplace
```

---

## 5.3 Skill生命周期

```text id="sk07"
Created
 ↓
Registered
 ↓
Validated
 ↓
Published
 ↓
Deprecated
 ↓
Retired
```

---

# 6. Skill Router（技能路由）

---

## 6.1 职责

负责：

> 选择“最合适Skill执行请求”

---

## 6.2 路由逻辑

### 输入：

```text id="sk08"
Agent request
```

---

### 处理：

```text id="sk09"
intent matching
capability matching
cost evaluation
policy filtering
```

---

### 输出：

```text id="sk10"
best skill
```

---

## 6.3 路由策略

### 1. Semantic Matching

基于embedding匹配

---

### 2. Capability Matching

基于能力标签

---

### 3. Cost-aware Routing

考虑成本

---

### 4. Policy-aware Routing

考虑权限

---

# 7. Skill Executor Engine（执行引擎）

---

## 7.1 执行流程

```text id="sk11"
Agent Runtime
   ↓
Skill Router
   ↓
Skill Executor
   ↓
Skill Adapter
   ↓
External System
```

---

## 7.2 执行状态机

```text id="sk12"
INIT
 ↓
VALIDATING
 ↓
EXECUTING
 ↓
WAITING
 ↓
SUCCESS
 ↓
FAILED
```

---

## 7.3 执行能力

* 同步执行
* 异步执行
* 流式执行
* 批量执行

---

# 8. Skill Adapter Layer（适配层）

---

## 8.1 作用

统一不同外部系统：

---

## 8.2 Adapter类型

### 1. API Adapter

```text id="sk13"
REST / GraphQL / RPC
```

---

### 2. MCP Adapter

```text id="sk14"
Model Context Protocol
```

---

### 3. Code Adapter

```text id="sk15"
Python / JS / Shell
```

---

### 4. Human Adapter

```text id="sk16"
审批 / 人工确认
```

---

### 5. Workflow Adapter

```text id="sk17"
触发Temporal流程
```

---

# 9. Skill Policy Engine（策略引擎）

---

## 9.1 策略类型

### 1. 安全策略

```text id="sk18"
禁止访问外部数据库
```

---

### 2. 权限策略

```text id="sk19"
仅采购Agent可调用ERP Skill
```

---

### 3. 限流策略

```text id="sk20"
100 req/min
```

---

### 4. 成本策略

```text id="sk21"
单次调用 < $0.01
```

---

## 9.2 Policy执行

```text id="sk22"
Skill Request
   ↓
Policy Check
   ↓
Allow / Reject / Modify
```

---

# 10. Skill 与 Agent Runtime关系

---

```text id="sk23"
Agent Runtime
   ↓
Skill Runtime
   ↓
External System
```

---

## 10.1 Agent调用Skill流程

```text id="sk24"
Agent Decision
   ↓
Skill Selection
   ↓
Skill Execution
   ↓
Result Return
```

---

## 10.2 Skill不是Agent能力

区别：

| 层级    | 定义   |
| ----- | ---- |
| Agent | 决策主体 |
| Skill | 执行能力 |

---

# 11. Skill编排机制（重要）

---

## 11.1 Skill Chain

```text id="sk25"
Skill A → Skill B → Skill C
```

---

## 11.2 Skill DAG

```text id="sk26"
        Skill A
       /       \
Skill B       Skill C
       \       /
        Skill D
```

---

## 11.3 Parallel Execution

```text id="sk27"
Skill A || Skill B || Skill C
```

---

# 12. Skill Marketplace（技能市场）

---

## 12.1 功能

* Skill发布
* Skill下载
* Skill复用
* Skill评分

---

## 12.2 类似结构

```text id="sk28"
App Store for AI Capabilities
```

---

# 13. Skill 数据模型

---

## 13.1 Skill表

```sql id="sk29"
Skill(
  id,
  name,
  type,
  version,
  owner,
  status
)
```

---

## 13.2 Skill版本表

```sql id="sk30"
SkillVersion(
  id,
  skill_id,
  config_json,
  created_at
)
```

---

## 13.3 Skill调用日志

```sql id="sk31"
SkillInvocation(
  id,
  agent_id,
  skill_id,
  latency,
  cost,
  status
)
```

---

# 14. Skill Runtime技术选型

---

## 14.1 核心组件

* API Gateway
* gRPC / HTTP
* Kafka（异步）
* Redis（缓存）
* PostgreSQL（元数据）
* MCP Server

---

## 14.2 执行层

* Kubernetes Job
* Serverless Functions
* Sidecar Runtime

---

# 15. 与传统系统对比

| 系统                    | 能力        |
| --------------------- | --------- |
| LangChain Tools       | 简单函数调用    |
| Zapier                | SaaS自动化   |
| RPA                   | UI操作      |
| AgentOS Skill Runtime | 企业级能力执行系统 |

---

# 16. Skill Runtime核心价值

---

## 16.1 从“工具调用”升级为“能力系统”

传统：

```text id="sk32"
function call
```

现在：

```text id="sk33"
capability orchestration system
```

---

## 16.2 从“单点工具”升级为“能力网络”

Skill之间可以：

* 组合
* 编排
* 路由
* 竞争

---

## 16.3 从“执行工具”升级为“治理资产”

Skill变成：

* 可管理
* 可计费
* 可审计
* 可交易

---

# 17. 一句话总结

Skill Runtime 的本质是：

> **把“工具调用体系”升级为“企业级可编排、可治理的能力操作系统”。**

---

如果你下一步继续，我建议进入三个最关键补齐模块：

* 《Planner → DAG 生成机制（AgentOS大脑）》
* 《AgentOS全链路时序图（非常关键）》
* 《Agent Runtime × Skill Runtime × Memory三者协同机制》

这三个是整个系统真正“能跑起来”的核心。
