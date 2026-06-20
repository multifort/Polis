# ADR-0007：M4 执行内核用桩驱动，真实 LLM/记忆/凭证延后到 M5/M6

- 状态：accepted
- 日期：2026-06-20

## 背景
M4「执行运行时」的核心是 lite-agent 执行循环 `_loop`：调 LLM 做多轮工具调用。
按 `docs/design/04`，它强依赖：ModelGateway(LiteLLM, M6)、CredentialBroker(M6)、
MemoryCenter(M5, RAG 检索+写回)、Guardrails-AI(M6)。研发计划 §3 也将 M4 定为
「M3/M5/M6 的汇流点，安排在三者各自最小可用之后」。

但 M5/M6 尚未实现，且真实 LLM 需要 API Key（ADR-0006 当初延后 LLM 即因本地无 Key）。
若严格按依赖顺序须先完整做 M6+M5 才能动 M4，工期长且把 M4 差异化价值（执行内核、
技能双形态、三道安全防线、MCP 集成）压在最后。

## 选项
1. 严格按计划先 M6 再 M5 再 M4 —— 最稳妥，但 M4 推迟最久，且 M6 需先解决 Key。
2. 先插做 M6 最小 ModelGateway（需 LLM Key）再 M4 真跑 —— M4 能真演示，但需现在引入 Key、增大工期。
3. **M4 执行内核用桩驱动先行** —— 搭全部内核结构，依赖项用对齐接口的桩，不需 Key、不阻塞；
   M5/M6 就绪后替换桩实现，调用方不动。延续 ADR-0006「确定性优先、LLM 延后」哲学。

## 决定
选 **选项 3**：M4 执行内核用桩驱动先行。桩边界（接口对齐 `docs/design/04`，换实现不改调用方）：
- **ModelGateway.chat** → 确定性 `StubModel`（支持脚本化 tool_call 序列供多轮测试）；M6 换 LiteLLM。
- **CredentialBroker.scoped** → 桩短时句柄；M6 换信封加密 + 任务级短时凭证。
- **MemoryCenter.retrieve/write** → DB 直写/空检索桩；M5 换 RAG 检索 + 评分去噪 + 衰减。
- **Guardrails** → 规则版注入检测/回流过滤；M6 换 Guardrails-AI。
- **MCP** → 内置本地工具（echo/计算）作可调通工具；真实外部 MCP server(browser-pilot 等)留后续。

M4 内**真实实现**的部分：SkillLoader 双形态 + 最小权限过滤、lite-agent `_loop` 多轮+超步保护、
McpRegistry/McpRuntime 结构、ContextAssembler 三样注入编排、AgentRuntime.execute、
ResultEnvelope 出处入库、SkillInvocation 计费日志、Temporal run_node 接入真实执行内核。

## 后果
- 正面：M4 不被 Key/M5/M6 阻塞即可推进；执行内核/安全防线/技能加载/MCP 集成结构完整可测；
  M5/M6 就绪后按接口替换桩，迁移面小且清晰。
- 负面/代价：M4 阶段无法演示真实 LLM 自主决策（桩模型为脚本化响应）；真实注入防御/语义检索/
  凭证隔离的有效性要等 M5/M6 接真实实现后才能验证。
- 影响范围：`modules/{runtime,model,memory}` 新增 service 层；`AgentConfig` 扩 `model`/`authority`；
  `planner/workflow.run_node` 由桩改为调 `AgentRuntime.execute`（编排/重规划/human-gate/retry 不变）。
- 切换提示：真实化时按上述 5 处桩边界逐个替换；登记的相关技术债见 `docs/tech-debt.md`（M5/M6 偿还项）。
