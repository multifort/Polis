"""业务模块边界（modular monolith，见 docs/design/07 §2）。

每个模块内部再分层 service/domain/repository；模块间通过显式接口调用，不互相掏内部实现。

- org           组织/角色/编配 + 身份·账号·多租户   (design 02, 09)
- planner       规划/编排/能力路由                   (design 03)
- runtime       执行运行时/技能/工具/安全             (design 04)
- memory        记忆与上下文/出处                    (design 05)
- model         模型接入/凭证/可观测/评估            (design 06)
- observability 可观测/审批/Run Manifest             (design 06, 07)
"""
