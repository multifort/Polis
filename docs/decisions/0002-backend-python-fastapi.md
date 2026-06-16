# ADR-0002：后端采用 Python 3.12 + FastAPI

- 状态：accepted
- 日期：2026-06-16

## 背景
Polis 后端需承载编排、模型接入、Agent 运行时、记忆/检索、可观测。需选定后端语言与框架。

## 选项
1. Node/TypeScript —— 与既有 hermes 同栈，但 AI/编排生态弱于 Python。
2. Python + FastAPI —— AI/Agent/编排生态最成熟（Temporal SDK、LiteLLM、MCP、LangGraph、Langfuse、pgvector 客户端均一流），异步 + 类型(Pydantic v2) 成熟。

## 决定
**Python 3.12 + FastAPI**，配套 SQLAlchemy 2.0(async) + Pydantic v2 + Alembic + Temporal Python SDK；
依赖锁定（uv/poetry），质量门禁 ruff/mypy/pytest（见 `docs/constraints/12,14`）。

## 后果
- 正面：直接复用 Python AI 生态，减少自研；类型与异步齐备。
- 负面 / 代价：与前端(TS)异构，需靠 OpenAPI 生成前端类型保持一致。
- 影响范围：backend/ 全部；CI 门禁工具链；API 契约以 OpenAPI 为准。
