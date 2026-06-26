"""planner 领域异常（独立模块，避免 service ↔ generator 循环导入）。"""

from __future__ import annotations


class NoTemplateMatch(Exception):
    """无 active 能力可满足任何模板，且不具备生成条件（→ 404）。"""


class PlanInvalid(Exception):
    """模板填充 / LLM 生成的 DAG 经确定性校验仍不合法（→ 422）。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors
