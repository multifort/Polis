# 《Capability Routing设计（Agent如何自动选择Agent）》

------

# 1. Capability Routing定位

这是AgentOS区别于：

```text
LangChain
CrewAI
AutoGen
LangGraph
```

最重要的一层。

因为：

这些框架通常是：

```text
Planner
 ↓
指定Agent
```

而AgentOS要做到：

```text
Planner
 ↓
Capability Routing
 ↓
自动选择Agent
```

------

# 2. 为什么需要Capability Routing

假设系统有：

```text
1000个Agent
```

Planner不可能写：

```text
if task == xxx:
    use agent_a
```

必须自动路由。

------

# 3. Capability Routing架构

```text
                 Task
                   │
                   ▼
          Capability Extractor
                   │
                   ▼
           Capability Matcher
                   │
                   ▼
             Rank Engine
                   │
                   ▼
            Agent Selector
                   │
                   ▼
               Agent
```

------

# 4. Capability模型

Agent注册时声明：

```json
{
  "agent":"analysis-agent",

  "capabilities":[
      "data_analysis",
      "report_generation",
      "forecast"
  ]
}
```

------

# 5. Capability Taxonomy设计

建议采用三层体系：

```text
Domain
 └─ Capability
      └─ Skill
```

------

例如：

```text
Procurement
 ├─ Supplier Analysis
 ├─ Cost Analysis
 └─ Forecast
```

------

# 6. Capability Extractor

任务：

```text
分析供应商交付质量
```

提取：

```json
{
  "domain":"procurement",
  "capability":"supplier_analysis"
}
```

------

# 7. Capability Matcher

匹配Agent：

```text
Agent A
Agent B
Agent C
```

计算：

```text
Similarity Score
```

------

# 8. Ranking Engine

评分模型：

```text
Score =
0.35 Capability Match
+
0.25 Historical Success
+
0.15 Cost
+
0.15 Latency
+
0.10 Memory Affinity
```

------

## 示例

| Agent | Score |
| ----- | ----- |
| A     | 0.93  |
| B     | 0.87  |
| C     | 0.76  |

------

选择：

```text
Agent A
```

------

# 9. Memory Affinity（非常重要）

如果Agent历史处理过：

```text
供应商分析
```

记忆已经积累。

则加分：

```text
Affinity +0.1
```

这样避免：

```text
每次换Agent
```

------

# 10. 多Agent选择

复杂任务：

```text
供应商分析
采购优化
风险评估
报告生成
```

路由：

```text
Analysis Agent

Optimization Agent

Risk Agent

Report Agent
```

形成：

```text
Multi-Agent Plan
```

------

# 11. Capability Graph

V3建议建立：

```text
Capability Graph
```

结构：

```text
Supplier Analysis
      │
      ├── Risk Analysis
      │
      ├── Cost Analysis
      │
      └── Forecast
```

这样Planner能够：

```text
自动扩展Agent能力
```

------

# 12. Capability Registry

独立于Agent Registry：

```text
Capability Registry
```

存储：

```text
Capability

Agent

Skill

Workflow
```

映射关系。

------

# 13. Routing决策流程

```text
Task
 ↓
Capability Extract
 ↓
Registry Search
 ↓
Capability Match
 ↓
Rank
 ↓
Select Agent
 ↓
Workflow
```

------

# 14. 与你当前架构最大的区别

你当前架构：

```text
Planner
 ↓
Agent
```

属于：

```text
Static Routing
```

------

优化后：

```text
Planner
 ↓
Capability Routing
 ↓
Agent Pool
 ↓
Best Agent
```

属于：

```text
Dynamic Routing
```

------

# 15. V1 → V3演进路线

### V1

```text
Rule Routing
```

------

### V2

```text
Capability Matching
```

------

### V3

```text
Autonomous Routing
```

支持：

```text
Agent自动发现

Agent自动组合

Agent自动替换

Agent自动优化
```

------

# 最终结论

如果说：

```text
Workflow = AgentOS的骨架
Memory = AgentOS的记忆
Skill = AgentOS的双手
```

那么：

```text
Planner = 大脑
Capability Routing = 神经系统
```

二者共同决定：

> **系统是否真正具备“自主规划 + 自主协作 + 自主选择能力”。**

这也是你的架构从“多Agent平台”进化为“AgentOS”的关键分水岭。