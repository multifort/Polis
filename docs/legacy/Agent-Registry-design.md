# Agent Registry 详细设计（Agent Registry Design Spec）

---

# 1. 概述

## 1.1 定义

Agent Registry 是 AgentOS 的**核心元数据与治理中心**，用于统一管理：

> 所有 Agent 的定义、版本、能力、权限、生命周期与分发。

它是 AgentOS 中的：

```text id="reg0"
“Docker Registry for Agents”
```

但比 Docker Registry 更复杂，因为 Agent 是：

* 有状态
* 有记忆
* 有能力（Skill）
* 有策略（Policy）
* 有模型依赖
* 有执行上下文

---

## 1.2 核心目标

Agent Registry 解决：

* Agent如何定义
* Agent如何版本化
* Agent如何发布与回滚
* Agent如何被发现与复用
* Agent如何权限控制
* Agent如何能力治理
* Agent如何跨团队共享

---

# 2. Agent Registry 总体架构

## 2.1 架构图

```text id="ar01"
                ┌────────────────────────────┐
                │   Agent Marketplace UI     │
                └────────────┬───────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────┐
│                    Agent Registry Core                │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Agent Definition Service                 │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Agent Version Service                    │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Agent Capability Service                 │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Agent Policy Service                     │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Agent Distribution Service               │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
                             │
         ┌───────────────────┼────────────────────┐
         ▼                   ▼                    ▼
┌──────────────┐   ┌────────────────┐   ┌────────────────┐
│ Skill Center │   │ Memory Center  │   │ Model Registry │
└──────────────┘   └────────────────┘   └────────────────┘
```

---

# 3. 核心设计思想

---

## 3.1 Agent = 可版本化智能体

Agent必须具备：

* 版本（Versioned）
* 可回滚（Rollbackable）
* 可发布（Publishable）
* 可组合（Composable）

---

## 3.2 Agent = 配置驱动实体

Agent不是代码，而是：

```text id="reg1"
Declarative Definition
```

---

## 3.3 Agent = 可治理资源

必须支持：

* 权限
* 审计
* 使用统计
* 生命周期管理

---

# 4. Agent Definition（Agent定义模型）

---

## 4.1 核心结构

```yaml id="reg2"
agent:
  id: purchase-agent
  name: Purchase Agent
  description: 负责企业采购决策

  version: 1.0.0

  role: procurement-manager

  prompt: |
    你是一个采购分析Agent...

  model:
    provider: deepseek
    model: deepseek-chat

  skills:
    - erp-query
    - supplier-score
    - contract-check

  memory:
    enabled: true
    namespace: procurement

  tools:
    - erp-api
    - db-query

  policies:
    max_tokens: 8000
    max_tool_calls: 50
    data_access: restricted

  tags:
    - finance
    - procurement

  owner: team-a
```

---

## 4.2 Agent组成模型

```text id="reg3"
Agent =
  Prompt
+ Model
+ Skills
+ Memory
+ Tools
+ Policies
+ Runtime Config
```

---

# 5. Agent Versioning（版本管理）

---

## 5.1 版本模型

采用：

```text id="reg4"
Semantic Versioning
MAJOR.MINOR.PATCH
```

---

## 5.2 版本策略

| 类型    | 说明        |
| ----- | --------- |
| MAJOR | Agent能力重构 |
| MINOR | 新增技能      |
| PATCH | prompt修复  |

---

## 5.3 版本管理能力

### 支持：

* 多版本共存
* 灰度发布
* 回滚
* A/B测试

---

## 5.4 示例

```text id="reg5"
purchase-agent:1.0.0
purchase-agent:1.1.0
purchase-agent:2.0.0
```

---

# 6. Agent Capability Model（能力模型）

---

## 6.1 能力定义

能力不是Skill，而是：

```text id="reg6"
Agent可以完成的任务类别
```

例如：

* 数据分析
* 决策支持
* 文档生成
* 代码生成

---

## 6.2 能力结构

```json id="reg7"
{
  "capability": "procurement-analysis",
  "level": "advanced",
  "confidence": 0.92
}
```

---

## 6.3 能力用途

用于：

* Agent路由
* Planner选择Agent
* 自动调度
* 多Agent协作分配

---

# 7. Agent Policy Service（策略系统）

---

## 7.1 Policy类型

### 1. 安全策略

```text id="reg8"
禁止访问敏感数据库
```

---

### 2. 资源策略

```text id="reg9"
max_tokens = 8000
max_tool_calls = 30
```

---

### 3. 行为策略

```text id="reg10"
必须审批才能执行采购
```

---

### 4. 数据策略

```text id="reg11"
禁止外发数据
```

---

## 7.2 Policy执行机制

```text id="reg12"
Agent Runtime → Policy Engine → Decision
```

---

# 8. Agent Distribution（分发机制）

---

## 8.1 分发方式

### 1. 内部部署

企业私有Agent库

---

### 2. Marketplace

类似：

```text id="reg13"
App Store for Agents
```

---

### 3. Workspace共享

团队内部共享Agent

---

## 8.2 分发流程

```text id="reg14"
开发Agent
  ↓
注册Registry
  ↓
版本控制
  ↓
审核
  ↓
发布
  ↓
消费
```

---

# 9. Agent Registry API设计

---

## 9.1 注册Agent

```http id="reg15"
POST /agents/register
```

---

## 9.2 获取Agent

```http id="reg16"
GET /agents/{id}
```

---

## 9.3 版本列表

```http id="reg17"
GET /agents/{id}/versions
```

---

## 9.4 发布版本

```http id="reg18"
POST /agents/{id}/publish
```

---

## 9.5 回滚版本

```http id="reg19"
POST /agents/{id}/rollback
```

---

# 10. Agent Registry 数据模型

---

## 10.1 Agent表

```sql id="reg20"
Agent(
  id,
  name,
  description,
  owner,
  created_at
)
```

---

## 10.2 Version表

```sql id="reg21"
AgentVersion(
  id,
  agent_id,
  version,
  config_json,
  status
)
```

---

## 10.3 Capability表

```sql id="reg22"
AgentCapability(
  agent_id,
  capability,
  score
)
```

---

## 10.4 Policy表

```sql id="reg23"
AgentPolicy(
  agent_id,
  policy_type,
  policy_value
)
```

---

# 11. Agent Registry 与其他系统关系

---

## 11.1 与Agent Runtime

```text id="reg24"
Registry → Runtime加载Agent定义
```

---

## 11.2 与Planner

```text id="reg25"
Planner → 选择最优Agent
```

---

## 11.3 与Skill System

```text id="reg26"
Agent → 绑定Skill
```

---

## 11.4 与Memory System

```text id="reg27"
Agent → Memory Namespace
```

---

## 11.5 与Model Runtime

```text id="reg28"
Agent → Model Provider绑定
```

---

# 12. Agent Registry核心价值

---

## 12.1 从“代码管理”升级为“智能体治理”

传统：

```text id="reg29"
Git Repo
```

现在：

```text id="reg30"
Agent Registry
```

---

## 12.2 从“函数调用”升级为“智能体资产”

Agent变成：

* 可复用资产
* 可交易资产
* 可治理资产

---

## 12.3 从“系统组件”升级为“组织资源”

Agent属于：

* 企业
* 部门
* 项目

---

# 13. 与传统系统对比

| 维度   | Docker    | LangChain | AgentOS Registry |
| ---- | --------- | --------- | ---------------- |
| 管理对象 | 容器        | Prompt    | Agent            |
| 状态   | 无状态       | 半状态       | 强状态              |
| 生命周期 | 简单        | 无         | 完整               |
| 版本   | image tag | 无         | 完整语义版本           |
| 权限   | 基础        | 无         | 企业级              |
| 治理   | limited   | none      | full             |

---

# 14. 一句话总结

Agent Registry 的本质是：

> **把“Prompt + Tool + Model”升级为“可治理、可版本化、可分发的智能体资产系统”。**

---

如果你下一步继续，我可以帮你补三块最关键的：

* 《Agent Registry UI / Marketplace 设计》
* 《Agent Capability 路由机制设计（非常关键）》
* 《Agent 与 Planner 的匹配算法设计》
* 《AgentOS整体微服务拆分（可直接开发）》
