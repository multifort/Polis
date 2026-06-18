# 《Planner → DAG生成机制设计（AgentOS真正的大脑）》

------

# 1. Planner在AgentOS中的定位

如果说：

```text
Agent Runtime = CPU
Memory Center = RAM
Skill Runtime = 外设
Workflow = 进程调度器
```

那么：

```text
Planner = AgentOS的大脑（Brain）
```

Planner负责解决：

> 用户目标 → AgentOS可执行计划

即：

```text
Goal
 ↓
Task
 ↓
SubTask
 ↓
DAG
 ↓
Workflow
```

------

# 2. 为什么Planner是整个系统最核心模块

大多数Agent系统：

```text
User
 ↓
LLM
 ↓
Tool
```

本质是：

```text
Reactive Agent
```

只能响应。

而企业级AgentOS需要：

```text
Goal Driven Planning
```

例如：

用户：

```text
分析供应商情况并优化采购策略
```

不能直接调用ERP。

必须先思考：

```text
需要哪些数据？
需要哪些Agent？
需要哪些Skill？
执行顺序是什么？
是否需要审批？
```

------

# 3. Planner总体架构

```text
                    User Goal
                        │
                        ▼
              Goal Understanding
                        │
                        ▼
                Task Decomposer
                        │
                        ▼
                 DAG Builder
                        │
                        ▼
                Plan Optimizer
                        │
                        ▼
                 Workflow DAG
```

------

# 4. Planner五层架构

------

## 第一层 Goal Understanding

职责：

```text
理解用户目标
```

输入：

```text
帮我分析供应商绩效并生成采购建议
```

输出：

```json
{
  "goal":"supplier_optimization",
  "domain":"procurement",
  "intent":"analysis"
}
```

------

## 第二层 Task Decomposer

拆解任务：

```text
分析供应商绩效

↓
```

拆解为：

```text
获取供应商数据

获取交付数据

获取质量数据

分析绩效

生成建议
```

形成：

```json
{
  "tasks":[
      "query_supplier",
      "query_delivery",
      "query_quality",
      "analyze",
      "recommend"
  ]
}
```

------

## 第三层 Capability Mapping

映射能力：

```text
query_supplier
 ↓
ERP Skill

query_quality
 ↓
MES Skill

analyze
 ↓
Analysis Agent
```

形成：

```json
{
  "task":"query_supplier",
  "capability":"erp_query"
}
```

------

## 第四层 DAG Builder

生成执行图：

```text
Supplier Data
       \
        \
         → Analysis
        /
Quality Data
```

转换：

```text
      A
     / \
    B   C
     \ /
      D
```

------

## 第五层 Plan Optimizer

优化：

### 并行化

```text
A
↓
B
↓
C
```

优化：

```text
A

B || C
```

------

### 成本优化

选择：

```text
GPT-4
Claude
DeepSeek
```

最优方案

------

# 5. Planner输出模型

最终输出：

```json
{
  "workflow_name":"supplier_analysis",

  "dag":{
      "nodes":[
          {
             "id":"n1",
             "type":"skill",
             "skill":"erp-query"
          },

          {
             "id":"n2",
             "type":"agent",
             "agent":"analysis-agent"
          }
      ]
  }
}
```

------

# 6. DAG节点设计

## Agent Node

```json
{
  "node_type":"agent",
  "agent":"analysis-agent"
}
```

------

## Skill Node

```json
{
  "node_type":"skill",
  "skill":"erp-query"
}
```

------

## Human Node

```json
{
  "node_type":"human",
  "approval":true
}
```

------

## Workflow Node

```json
{
  "node_type":"workflow",
  "workflow":"sub_workflow"
}
```

------

# 7. Dynamic DAG（V3核心）

传统DAG：

```text
固定
```

AgentOS：

```text
运行时生成
```

例如：

分析结果发现：

```text
供应商风险高
```

自动新增：

```text
风险评估节点
```

形成：

```text
Runtime DAG Expansion
```

------

# 8. Planner与Memory协同

Planner不仅看当前任务。

还读取：

```text
Memory Center
```

包括：

```text
历史执行记录

历史Workflow

历史失败案例
```

实现：

```text
Experience-aware Planning
```

------

# 9. Planner与Agent Registry协同

Planner不会硬编码Agent。

通过Registry发现：

```text
Analysis Agent

Finance Agent

Report Agent
```

然后动态选择。

------

# 10. Planner核心升级路线

## V1

Prompt Planner

```text
LLM直接拆任务
```

------

## V2

Task Planner

```text
Goal
↓
Task
↓
DAG
```

------

## V3

Autonomous Planner

```text
Goal
↓
Reasoning
↓
Simulation
↓
Optimization
↓
DAG
```

------

# 一句话总结

> Planner本质是AgentOS的大脑，负责把自然语言目标转换成可执行DAG。

#
