# Polis 文档索引

> 阅读顺序：先 `design/00` 总览 → 按需深入 02–08 → 落地看 `constraints/` → 重大选型看 `decisions/`。

## design/ — 系统设计
| 文档 | 内容 |
|---|---|
| [0a Polis 理念与隐喻](design/0a-Polis理念与隐喻.md) | **产品身份**：城邦隐喻→概念映射、术语表（先读） |
| [00 总览与设计原则](design/00-总览与设计原则.md) | 平台总览、原则、关键决策 |
| [01 设计原则与技术选型](design/01-设计原则与技术选型.md) | Python 栈、复用优先选型 |
| [02 组织角色与编配](design/02-组织角色与编配.md) | Org/Role/Agent、Provisioner、DDL |
| [03 规划编排与能力路由](design/03-规划编排与能力路由.md) | Planner、Plan 校验、能力路由 |
| [04 执行运行时·工具·安全](design/04-执行运行时·工具·安全.md) | 无状态 worker、MCP 工具、护栏 |
| [05 记忆与上下文](design/05-记忆与上下文.md) | 三层记忆 + RAG 检索 |
| [06 模型接入·凭证·可观测·评估](design/06-模型接入·凭证·可观测·评估.md) | LiteLLM、凭证 Broker、Langfuse |
| [07 数据·部署·演进路线](design/07-数据·部署·演进路线.md) | 数据模型、部署、里程碑 M1–M7 |
| [08 关键技术与知识产权](design/08-关键技术与知识产权.md) | IP 候选点 P1–P8 |
| [09 身份·账号·多租户](design/09-身份·账号·多租户.md) | app_user/认证、用户↔多 Org、权限矩阵、RLS 双保险 |

## constraints/ — 工程化约束
| 文档 | 内容 |
|---|---|
| [00 约束清单与选型](constraints/00-约束清单与选型.md) | 约束总清单与采纳项 |
| [10 UI 设计约束](constraints/10-UI设计约束.md) | A1–A14 设计系统 |
| [10a 色彩规范](constraints/10a-色彩规范.md) | **颜色唯一来源**（靛蓝 `#3F51B5` + 令牌 + 对比度 + 深色） |
| [11 前端风格约束](constraints/11-前端风格约束.md) | B1–B14 |
| [12 后端风格约束](constraints/12-后端风格约束.md) | C1–C17 |
| [13 移动端约束](constraints/13-移动端约束.md) | D1–D9 |
| [14 工程化约束](constraints/14-工程化约束.md) | 仓库/门禁/治理 |
| [15 过程约束](constraints/15-过程约束.md) | DoR/DoD/ADR/IP 流程 |

## plan/ — 研发计划与任务
| 文档 | 内容 |
|---|---|
| [研发计划](plan/研发计划.md) | 里程碑 M0–M7 + 前端轨、关键路径、V1 验收门、风险 |
| [研发任务清单](plan/研发任务清单.md) | WBS 全量任务（依赖/验收/估时/轨道） |

## decisions/ — 架构决策记录 (ADR)
| ADR | 决定 |
|---|---|
| [0001](decisions/0001-independent-system.md) | 与 hermes-test 完全独立 |
| [0002](decisions/0002-backend-python-fastapi.md) | 后端 Python + FastAPI |
| [0003](decisions/0003-project-name-polis.md) | 项目命名 Polis |
| [0004](decisions/0004-reuse-first-stack.md) | 复用优先技术栈 |
| [0005](decisions/0005-multi-tenancy-strategy.md) | 多租户：逻辑隔离 + RLS 兜底 |

## legacy/ — 早期讨论稿
已被 `design/` 取代，留作历史追溯，不作为现行设计依据。
