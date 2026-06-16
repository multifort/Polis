---
description: 对当前改动跑 Polis 评审清单
---
对当前分支相对 `main` 的改动做评审，逐条核对并给出结论（通过/需改/阻断）：

**完成定义 (DoD)**
- [ ] 验收标准全部满足，关联到设计章节/任务ID
- [ ] 有对应测试且通过；核心模块覆盖率 ≥70%
- [ ] 过本地门禁：ruff / mypy / pytest / gitleaks / bandit / pip-audit
- [ ] 文档 / ADR / OpenAPI 同步更新；无遗留 TODO / skip 测试

**架构与风格（docs/constraints/11,12）**
- [ ] 分层依赖正确（api→service→domain→repo，不反向）
- [ ] 禁 `any`、禁裸 dict 传递、Pydantic 校验边界
- [ ] 只经 LiteLLM 网关调模型，只经 MCP 调工具

**安全与多租户（docs/constraints/14 E17 / CLAUDE.md §4）**
- [ ] 所有查询带 `org_id` 过滤；有隔离回归测试
- [ ] 无密钥入码/日志；BYO 凭证短时、用完即焚
- [ ] 危险动作走审批 gate，未自动执行

先看真实 diff 与测试输出，不臆断结论。
