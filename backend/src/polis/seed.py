"""幂等 seed：能力词表 / 模型目录 / 采购场景预设（批次2，对接 03/06/02）。

运行：`make seed`（= python -m polis.seed）。可重复执行，ON CONFLICT 更新。
embedding 暂留空（接 LiteLLM 后再回填，见 M6）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from polis.config import get_settings
from polis.modules.model.models import ModelCatalog
from polis.modules.org.models import ScenarioPreset
from polis.modules.planner.models import Capability, PlanTemplate

# ---- 能力词表（采购域 + 通用），承重墙，先定（03 §7.3）----
CAPABILITIES: list[dict[str, Any]] = [
    {
        "key": "procurement.supplier_analysis",
        "domain": "procurement",
        "name": "供应商交付分析",
        "description": "分析供应商交付表现、风险与稳定性",
    },
    {
        "key": "procurement.rfq",
        "domain": "procurement",
        "name": "询价比价",
        "description": "对接 ERP/供应商进行询价与比价",
    },
    {
        "key": "procurement.spend_analysis",
        "domain": "procurement",
        "name": "支出分析",
        "description": "采购支出结构与节降机会分析",
    },
    {
        "key": "procurement.contract_review",
        "domain": "procurement",
        "name": "合同审阅",
        "description": "采购合同条款审阅与风险提示",
    },
    {
        "key": "report.generation",
        "domain": "report",
        "name": "报告生成",
        "description": "将分析结果整理为结构化报告",
    },
    {
        "key": "data.cleaning",
        "domain": "data",
        "name": "数据清洗",
        "description": "清洗、去重、标准化结构化数据",
    },
    {
        "key": "data.extraction",
        "domain": "data",
        "name": "数据抽取",
        "description": "从文档/网页抽取结构化字段",
    },
    {
        "key": "web.research",
        "domain": "web",
        "name": "互联网检索",
        "description": "经 MCP 浏览器检索公开信息（带出处）",
    },
]

# ---- 模型目录（系统托管，无密钥；BYO-Key 运行时注入，06）----
MODELS: list[dict[str, Any]] = [
    {
        "id": "deepseek-v4-pro",
        "provider": "deepseek",
        "litellm_name": "deepseek/deepseek-v4-pro",
        "capabilities": ["text-gen"],
        "context_window": 65536,
        "price_in": 0.0005,
        "price_out": 0.001,
    },
    {
        "id": "deepseek-v4-flash",
        "provider": "deepseek",
        "litellm_name": "deepseek/deepseek-v4-flash",
        "capabilities": ["text-gen"],
        "context_window": 65536,
        "price_in": 0.0001,
        "price_out": 0.0002,
    },
    {
        "id": "claude-opus",
        "provider": "anthropic",
        "litellm_name": "anthropic/claude-opus-4-1",
        "capabilities": ["text-gen", "vision"],
        "context_window": 200000,
        "price_in": 0.015,
        "price_out": 0.075,
    },
    {
        "id": "text-embedding-bge",
        "provider": "local-tei",
        "litellm_name": "openai/bge-large-zh-v1.5",  # 本地 TEI，OpenAI 兼容端点
        "capabilities": ["embed"],
        "context_window": 512,
        "price_in": 0.0,
        "price_out": 0.0,
        # base_url 运行时由 POLIS_EMBEDDING_BASE_URL 决定，不写进 DB；仅声明维度
        "connector": {"dim": 1024},
    },
]

# ---- 采购分析公司 预设（02 §4）----
PRESETS: list[dict[str, Any]] = [
    {
        "name": "采购分析公司",
        "version": "v1",
        "description": "面向供应商交付分析的虚拟公司：询价、分析、报告三角色协同。",
        "required_capabilities": [
            "procurement.rfq",
            "procurement.supplier_analysis",
            "procurement.spend_analysis",
            "report.generation",
        ],
        "config": {
            "agentTemplates": [
                {
                    "roleName": "采购经理",
                    "agentName": "询价Agent",
                    "promptSkeleton": "你负责对接供应商询价与比价。",
                    "skills": [],
                    "capabilities": ["procurement.rfq"],
                },
                {
                    "roleName": "分析师",
                    "agentName": "分析Agent",
                    "promptSkeleton": "你负责供应商交付与支出分析，结论需带出处。",
                    "skills": [],
                    "capabilities": ["procurement.supplier_analysis", "procurement.spend_analysis"],
                },
                {
                    "roleName": "报告员",
                    "agentName": "报告Agent",
                    "promptSkeleton": "你负责把分析结论整理为结构化报告。",
                    "skills": [],
                    "capabilities": ["report.generation"],
                },
            ],
            "defaultPlanTemplates": ["supplier_analysis_v1"],
        },
    },
]


# ---- 计划模板（DAG 骨架，串/并结构；供 Planner 模板优先填槽，03）----
PLAN_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "supplier_analysis_v1",
        "version": "v1",
        "dag_skeleton": {
            "workflow_name": "supplier_analysis",
            "goal": "",
            "acceptance_criteria": "产出供应商交付分析报告（带出处）",
            "budget_cents": 50000,
            "nodes": [
                {
                    "id": "n1",
                    "type": "agent",
                    "deps": [],
                    "required_capabilities": ["procurement.rfq"],
                    "input_hint": "向供应商询价比价",
                    "expected_output": "询价/比价结果",
                },
                {
                    "id": "n2",
                    "type": "agent",
                    "deps": ["n1"],
                    "required_capabilities": ["procurement.supplier_analysis"],
                    "input_hint": "分析供应商交付表现与风险",
                    "expected_output": "供应商分析",
                },
                {
                    "id": "n3",
                    "type": "agent",
                    "deps": ["n1"],
                    "required_capabilities": ["procurement.spend_analysis"],
                    "input_hint": "分析采购支出与节降机会",
                    "expected_output": "支出分析",
                },
                {
                    "id": "n4",
                    "type": "agent",
                    "deps": ["n2", "n3"],
                    "required_capabilities": ["report.generation"],
                    "input_hint": "汇总为结构化报告",
                    "expected_output": "分析报告",
                },
            ],
        },
    },
]


async def _upsert(
    conn: AsyncConnection, table: Any, rows: list[dict[str, Any]], conflict: list[str]
) -> int:
    if not rows:
        return 0
    stmt = pg_insert(table).values(rows)
    present = set(rows[0])
    update = {c: stmt.excluded[c] for c in present if c not in conflict}
    stmt = stmt.on_conflict_do_update(index_elements=conflict, set_=update)
    await conn.execute(stmt)
    return len(rows)


async def seed() -> dict[str, int]:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            caps = await _upsert(conn, Capability.__table__, CAPABILITIES, ["key"])
            models = await _upsert(conn, ModelCatalog.__table__, MODELS, ["id"])
            presets = await _upsert(conn, ScenarioPreset.__table__, PRESETS, ["name", "version"])
            plans = await _upsert(conn, PlanTemplate.__table__, PLAN_TEMPLATES, ["name", "version"])
    finally:
        await engine.dispose()
    return {"capabilities": caps, "models": models, "presets": presets, "plan_templates": plans}


def main() -> None:
    counts = asyncio.run(seed())
    print(f"seed 完成：{counts}")


if __name__ == "__main__":
    main()
