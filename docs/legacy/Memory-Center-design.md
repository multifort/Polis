# Memory Center 详细设计（Memory Center Design Spec）

---

# 1. 概述

## 1.1 定义

Memory Center 是 AgentOS 的**统一记忆系统（Unified Memory System）**，负责管理所有 Agent 的：

> 记忆生成、存储、检索、更新、衰减与共享机制。

它是 AgentOS 中最关键的“智能连续性能力”。

---

## 1.2 核心问题

没有 Memory Center 的 Agent 系统：

* 每次对话都是“失忆”
* Agent无法积累经验
* 多Agent无法共享知识
* 决策无法优化
* 企业无法形成“智能资产”

---

## 1.3 设计目标

Memory Center 解决：

* 记忆结构化
* 记忆长期化
* 记忆可共享
* 记忆可检索
* 记忆可衰减
* 记忆可治理

---

# 2. Memory Center 总体架构

## 2.1 架构图

```text id="mc01"
                 ┌────────────────────────────┐
                 │     Agent Runtime          │
                 └────────────┬───────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│                    Memory Center Core                    │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │         Session Memory Service (短期记忆)          │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │         Long-term Memory Service (长期记忆)       │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │         Shared Memory Service (共享记忆)          │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │         Memory Embedding Service (向量记忆)       │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────┐  │
│  │         Memory Governance Service (治理)          │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │ Vector DB    │  │ PostgreSQL   │  │ Object Store │
   └──────────────┘  └──────────────┘  └──────────────┘
```

---

# 3. Memory Center 核心设计思想

---

## 3.1 Memory ≠ Context

| 概念        | 生命周期 | 作用   |
| --------- | ---- | ---- |
| Context   | 短期   | 当前任务 |
| Memory    | 长期   | 经验沉淀 |
| Knowledge | 稳定   | 企业知识 |

---

## 3.2 Memory = 可学习资产

Memory不是数据，而是：

```text id="mc02"
Experience-based Intelligence Asset
```

---

## 3.3 Memory必须具备4个特性

* 可写入（Write）
* 可检索（Retrieve）
* 可更新（Update）
* 可遗忘（Forget）

---

# 4. Memory 分层设计

---

## 4.1 四层记忆体系

```text id="mc03"
┌──────────────────────────────┐
│  Session Memory (会话记忆)   │
├──────────────────────────────┤
│  Short-term Memory           │
├──────────────────────────────┤
│  Long-term Memory            │
├──────────────────────────────┤
│  Shared Memory               │
└──────────────────────────────┘
```

---

## 4.2 Session Memory（会话记忆）

### 特点

* 生命周期：单次会话
* 不持久化或弱持久化

### 内容

```text id="mc04"
当前任务上下文
用户输入
中间推理过程
临时变量
```

---

## 4.3 Short-term Memory（短期记忆）

### 特点

* 生命周期：小时~天级
* 用于任务连续性

---

### 示例

```text id="mc05"
今天的采购任务列表
当前审批状态
正在执行的DAG节点
```

---

## 4.4 Long-term Memory（长期记忆）

### 特点

* 生命周期：永久（可衰减）
* Agent经验沉淀核心

---

### 示例

```text id="mc06"
供应商A可靠性高
客户B倾向低价策略
某类任务失败模式
```

---

## 4.5 Shared Memory（共享记忆）

### 特点

* 多Agent共享
* Workspace级别

---

### 示例

```text id="mc07"
企业采购规则
项目标准流程
历史审批经验
```

---

# 5. Memory 数据模型

---

## 5.1 Memory基础结构

```json id="mc08"
{
  "memory_id": "m123",
  "type": "long_term",
  "scope": "agent/workspace/global",

  "content": "供应商A交付稳定",

  "embedding": [0.12, 0.98, ...],

  "importance": 0.87,

  "confidence": 0.91,

  "created_at": "2026-01-01",

  "last_accessed": "2026-01-10",

  "decay_rate": 0.01
}
```

---

## 5.2 Memory类型

| 类型         | 说明 |
| ---------- | -- |
| factual    | 事实 |
| procedural | 经验 |
| preference | 偏好 |
| event      | 事件 |
| semantic   | 概念 |

---

# 6. Memory 写入机制（Write Pipeline）

---

## 6.1 写入流程

```text id="mc09"
Agent Runtime
   ↓
Memory Extractor
   ↓
Memory Scoring
   ↓
Memory Filter
   ↓
Memory Store
```

---

## 6.2 Memory Extractor

从对话/执行中提取：

* 关键事实
* 决策
* 经验
* 偏好

---

## 6.3 Memory Scoring（评分机制）

```text id="mc10"
score = importance * confidence * relevance
```

---

## 6.4 Memory Filter（过滤）

过滤条件：

* 噪声
* 重复
* 低价值信息

---

# 7. Memory 检索机制（Retrieval）

---

## 7.1 检索流程

```text id="mc11"
Query
  ↓
Embedding
  ↓
Vector Search
  ↓
Rerank
  ↓
Context Assembly
```

---

## 7.2 检索策略

### 1. Semantic Search

语义匹配

---

### 2. Keyword Search

精确匹配

---

### 3. Hybrid Search

混合模式（推荐）

---

## 7.3 Rerank策略

使用：

* relevance score
* recency
* importance

---

# 8. Memory 更新机制（Update）

---

## 8.1 更新类型

### 1. Strengthen（强化）

重复出现的信息增强权重

---

### 2. Merge（合并）

相似记忆合并

---

### 3. Override（覆盖）

新事实替换旧事实

---

## 8.2 更新规则

```text id="mc12"
if new_memory.confidence > old_memory.confidence:
    replace
```

---

# 9. Memory 衰减机制（Forgetting）

---

## 9.1 衰减模型

```text id="mc13"
importance = importance * e^(-λt)
```

---

## 9.2 衰减策略

| 类型         | 衰减     |
| ---------- | ------ |
| factual    | slow   |
| event      | medium |
| preference | slow   |
| noise      | fast   |

---

## 9.3 自动遗忘

低价值Memory自动清理：

* 噪声
* 过期事件
* 冗余信息

---

# 10. Memory Governance（治理系统）

---

## 10.1 目标

保证 Memory：

* 可控
* 可审计
* 可安全

---

## 10.2 权限模型

```text id="mc14"
Agent A:
  can_read: workspace_memory
  can_write: own_memory
  cannot_access: global_memory
```

---

## 10.3 审计机制

记录：

* 谁写入Memory
* 谁读取Memory
* Memory变化历史

---

## 10.4 数据安全

支持：

* 脱敏
* 加密
* 企业隔离

---

# 11. Memory 与 Agent Runtime关系

---

```text id="mc15"
Agent Runtime
   ↓
Memory Center
   ↓
Vector DB / PostgreSQL
```

---

## 11.1 写入路径

Agent → Memory Extractor → Storage

---

## 11.2 读取路径

Agent → Query → Retrieval → Context Injection

---

# 12. Memory 与 Multi-Agent关系

---

## 12.1 Agent共享记忆

```text id="mc16"
Agent A → Shared Memory ← Agent B
```

---

## 12.2 协作优化

Memory让多Agent具备：

* 经验共享
* 决策一致性
* 学习能力

---

# 13. Memory Center技术选型

---

## 13.1 存储层

* PostgreSQL（结构化）
* Redis（缓存）
* Milvus / Weaviate（向量）
* MinIO（文件）

---

## 13.2 检索层

* Hybrid Search Engine
* Reranker Model
* Embedding Model

---

## 13.3 计算层

* Memory Scoring Engine
* Decay Engine
* Merge Engine

---

# 14. 与传统系统对比

| 系统               | 能力           |
| ---------------- | ------------ |
| ChatGPT Memory   | 单用户          |
| LangChain Memory | 简单缓存         |
| RAG系统            | 知识检索         |
| AgentOS Memory   | 多Agent长期学习系统 |

---

# 15. Memory Center核心价值

---

## 15.1 从“对话系统”升级为“学习系统”

没有Memory：

```text id="mc17"
每次都是第一次
```

有Memory：

```text id="mc18"
系统会成长
```

---

## 15.2 从“工具Agent”升级为“经验Agent”

Agent具备：

* 经验
* 偏好
* 习惯
* 决策历史

---

## 15.3 从“无状态智能”升级为“持续智能”

系统具备：

> 时间维度上的智能进化能力

---

# 16. 一句话总结

Memory Center 的本质是：

> **让 Agent 从“每次重置的大模型调用”进化为“具有经验累积能力的持续学习系统”。**

---

如果你下一步要继续，我建议直接进入三个最关键设计：

* 《Tool Runtime 详细设计（MCP + Skill系统核心）》
* 《Planner → DAG 生成机制设计》
* 《AgentOS全链路数据流与执行时序图（非常关键）》
