# 竞品借鉴：Paperclip 对比分析

> 状态：调研纪要（2026-06-23）｜对象：[paperclipai/paperclip](https://github.com/paperclipai/paperclip)
> 目的：与 Polis V2 设计比对，提炼可借鉴点并映射到里程碑。

## 1. Paperclip 是什么
开源（Node.js + React，TS 98%）的"AI 智能体编排平台，让一队 Agent 像自治公司一样运作"。
**同一隐喻**："If OpenClaw is an _employee_, Paperclip is the _company_."（≈ Polis：Agent=公民、Org=虚拟公司）——**强验证了 Polis 的定位与品类存在**。

子系统：身份与访问 · 组织架构与 Agent · 工作/任务（Issue）系统 · **心跳执行(Heartbeat)** · 治理与审批 · 预算与成本 · 例程/排程(Routines)。

## 2. Polis vs Paperclip（关键差异）
| 维度 | Polis | Paperclip |
|---|---|---|
| 隐喻 | 虚拟公司（Agent/Role/Org） | 同（company/employee） |
| 执行模型 | **编排推送**（Temporal 驱动 DAG，exactly-once/可回放） | **心跳拉取**（Agent 定时唤醒→查活→执行；DB 唤醒队列+coalescing） |
| 规划 | **模板优先 + LLM 生成 DAG + 确定性校验**（退化链） | Issue/工单式（无生成式 DAG，靠 blocker 依赖） |
| 质量 | **Evaluator 自动质量门**（断言+LLM-judge） | 未见自动 eval，偏人审/board 审批 |
| Agent 形态 | 单运行时（lite-agent + LiteLLM 多模型） | **多 provider 适配**（Claude/Codex/Cursor/bash/HTTP）"if it can receive a heartbeat, it's hired" |
| 组织 | 扁平花名册（Agent=岗位） | **层级组织**（reporting lines + 头衔 + 每 Agent 预算） |
| 预算 | **只提示不阻断**（V2 决策） | **硬停**（超支暂停 Agent + 取消排队工作） |
| 多租户 | org_id + RLS（一等公民） | company 隔离 |
| 凭证 | 任务级短时句柄、用完即焚 | "secrets stay out of prompts unless a scoped run needs them"（**同思路**） |
| 记忆/技能 | 三层记忆 + skill 手册注入 | "runtime skill injection，无需重训" + 任务带**目标族谱** |
| 治理 | 审批/出处/审计 | 审批门 + **config 版本化+回滚** + **Agent 生命周期 pause/resume/terminate** |
| 隔离工作区 | 无（产物走 artifact/MinIO 规划中） | **每次运行隔离 workspace**（workspace resolution） |

## 3. 验证了我们的哪些设计（同向）
- 虚拟公司隐喻、角色化 Agent、治理/审计、**凭证不入 prompt 的短时注入**、**runtime skill 注入**、能力门控插件（≈MCP+能力词表）、按 company/agent/project/model 的成本核算。
- **任务带"目标族谱"让 Agent 始终看到 why** —— 正面印证 Polis 的 **F3 修复（goal 贯通 Agent）**，且提示我们应贯通**完整族谱**（公司使命→目标→子任务），不止即时 goal。

## 4. 可借鉴（按对路线的价值排序，映射到里程碑）
| # | 借鉴点 | Paperclip 做法 | Polis 落点 |
|---|---|---|---|
| 1 | **完整目标族谱注入** | "tasks carry full goal ancestry" | 记忆/内核 上下文装配：把 公司使命+任务目标+父任务 一起注入（F3 的增强，便宜高价值） |
| 2 | **预算硬停（可选）** | 超支硬停+取消排队 | **协同 S3**：在"只提示"之外，提供**可配置硬停策略**（默认提示；自治/长跑/例程场景建议硬停防失控） |
| 3 | **例程/排程(Routines)** | cron + webhook 触发的循环任务 | **产品面**新增：可复用任务的**定时/触发运行**（如"每周供应商分析"）——很贴"虚拟公司"做重复工作 |
| 4 | **配置版本化 + 回滚** | "config revisioned, bad changes rolled back" | **仓库(R)**：把版本钉选扩成**生成资产(agent/skill/模板)可回滚**（安全网） |
| 5 | **多 provider 执行适配** | bash/HTTP/外部 CLI agent 皆可"受雇" | **V2+/V3**：把 `executor` 泛化为**适配器**（lite-agent 之外接外部 agent 后端）——潜在大差异化 |
| 6 | **原子签出/执行锁** | "atomic checkout with execution locks 防双工" | **协同 §6 并发**：若引入"Agent 拉取工作"模式需要（当前 Temporal 推送已 exactly-once，先记着） |
| 7 | **Agent 生命周期 + 每 Agent 预算** | pause/resume/terminate + 月度预算 | **治理**：长跑 Agent 的暂停/恢复/终止 + 按 Agent 预算（接成本面） |
| 8 | **每次运行隔离工作区** | isolated workspace + 解析 | **Skill 沙箱 + 产物**（接 #7/MinIO + 私有化方向） |
| 9 | **更厚的工作项** | issue 带 comments/附件/work products/inbox 态 | **产品面(P)**：task 可加评论/附件/产物/收件箱态（当前 task 偏薄） |

## 5. 不照搬 / 保持本色
- **执行模型**：坚持 **Temporal 编排推送为主**（持久/exactly-once/可回放，更适合受治理的多步 DAG）；心跳拉取作为**自治/循环 Agent 的补充模式**（V2+），不替换主轨。
- **生成式规划 + 自动质量门**是 Polis 的差异化（Paperclip 偏工单+人审），不要回退成纯 issue tracker。

## 6. 对当前/后续工作的具体动作
- **即刻（小、顺手）**：S1 之后在记忆/内核上下文里加 **"目标族谱"注入**（公司 charter + 任务 goal）。
- **协同阶段（S3）**：把"预算只提示"改为 **可配置：提示 / 软降级 / 硬停**（默认仍提示，尊重既有决策；硬停作为自治场景 opt-in）。
- **产品阶段**：评估新增 **Routines（定时/触发运行）**。
- **仓库阶段（R）**：版本钉选 → 加**回滚**。
- **V2+/V3 候选**：多 provider 执行适配器、Agent 生命周期治理、隔离工作区。

> 结论：Paperclip 验证了 Polis 的品类与多数核心设计；可借鉴点多为**治理/运维成熟度**（预算硬停、回滚、生命周期、例程）与**执行异构化**（多 provider）。Polis 的**生成式内核 + 自动质量门 + 多租户**是相对其的差异化，应继续强化。
