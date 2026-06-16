"""Polis 后端：多 Agent 协同平台（FastAPI modular monolith）。

分层约定（见 docs/constraints/12）：api → service → domain → repository，单向依赖。
模块边界（见 docs/design/07 §2）见 `polis.modules`。
"""

__version__ = "0.1.0"
