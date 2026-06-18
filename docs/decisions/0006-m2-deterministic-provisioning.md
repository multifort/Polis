# ADR-0006：M2 立邦走确定性「模板优先」，LLM 编配延后到 M6

- 状态：accepted
- 日期：2026-06-18

## 背景
M2「立邦闭环」设计原含依赖 LLM/embedding 的能力：`IntentParser`（自然语言意图→结构化）、
`GapGenerator`（缺口能力→LLM 生成 Agent + judge）、`PresetMatcher` 语义检索。
这些需要模型网关（LiteLLM，M6）与可用 API Key；本地无网关/无 Key 时无法真跑、无法端到端演示。

## 选项
1. M2 内先搭最小 LiteLLM 网关，让 LLM 编配真跑 —— 需 BYO Key，增大 M2 工期与复杂度。
2. M2 走确定性「模板优先」路线，LLM 部分延后 M6 —— 无需 Key、端到端可见；与设计 03「模板优先兜可靠性」同思路。

## 决定
采用**选项 2**：
- **立邦入口** = 选预设 + 关键词匹配（按 `required_capabilities`/名称确定性匹配到 `scenario_preset`），不依赖 LLM。
- **OrgInstantiator** 按预设 `agentTemplates` 实例化 role + agent + agent_version；预设来源**受信**，实例化的 Agent **直接 active**（不走完整审批收件箱，T6.7 留 M6）。
- **延后到 M6**：`IntentParser`、`GapGenerator + AgentValidator`、`PresetMatcher` 的 embedding 语义检索、完整审批收件箱。

## 后果
- 正面：M2 无需 API Key、可端到端演示（登录→选预设立邦→花名册）；不被 M6 阻塞。
- 负面 / 代价：M2 的立邦是「选已有预设」而非「自然语言意图自动编配」；自然语言/缺口生成体验待 M6。
- 影响范围：02 编配（T2.3/T2.6 延后）、03 PresetMatcher（embedding 版后置）、06 审批收件箱（M6）；研发计划 M2 范围按本 ADR 收敛。
