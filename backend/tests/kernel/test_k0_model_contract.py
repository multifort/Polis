"""K0 characterization contract for the six legacy runtime ORM models.

The contract intentionally describes database-facing metadata and public import/API
surfaces.  K0 may move Python declarations, but none of these values may change.
"""

from __future__ import annotations

import ast
from pathlib import Path

import polis.db.models as model_registry
from polis.db.models import Base
from polis.main import app
from polis.modules.kernel.models import Approval as KernelApproval
from polis.modules.kernel.models import ArtifactDescriptor as KernelArtifactDescriptor
from polis.modules.kernel.models import Plan as KernelPlan
from polis.modules.kernel.models import ResultEnvelope as KernelResultEnvelope
from polis.modules.kernel.models import RunManifest as KernelRunManifest
from polis.modules.kernel.models import TaskRun as KernelTaskRun
from polis.modules.memory.models import ArtifactDescriptor, ResultEnvelope
from polis.modules.observability.models import Approval, RunManifest
from polis.modules.planner.models import Plan, TaskRun

EXPECTED_TABLE_CONTRACTS = {
    "plan": {
        "columns": (
            ("goal", "TEXT", True, False, None),
            ("dag", "JSONB", False, False, None),
            ("version", "TEXT", True, False, None),
            ("status", "TEXT", False, False, "draft"),
            ("estimated_cost_cents", "BIGINT", True, False, None),
            ("created_at", "DATETIME", False, False, "now()"),
            ("id", "CHAR(32)", False, True, "gen_random_uuid()"),
            ("org_id", "CHAR(32)", False, False, None),
        ),
        "foreign_keys": (("org_id", "org.id", "CASCADE"),),
        "checks": (
            (
                "ck_plan_status",
                "status IN ('draft','approved','running','done','failed','needs_review')",
            ),
        ),
        "indexes": (("ix_plan_org_id", ("org_id",), False),),
    },
    "task_run": {
        "columns": (
            ("task_id", "CHAR(32)", True, False, None),
            ("plan_id", "CHAR(32)", True, False, None),
            ("temporal_workflow_id", "TEXT", True, False, None),
            ("status", "TEXT", False, False, "pending"),
            ("priority", "INTEGER", False, False, "0"),
            ("started_at", "DATETIME", True, False, None),
            ("finished_at", "DATETIME", True, False, None),
            ("id", "CHAR(32)", False, True, "gen_random_uuid()"),
            ("org_id", "CHAR(32)", False, False, None),
            ("created_at", "DATETIME", False, False, "now()"),
            ("updated_at", "DATETIME", False, False, "now()"),
        ),
        "foreign_keys": (
            ("org_id", "org.id", "CASCADE"),
            ("plan_id", "plan.id", None),
            ("task_id", "task.id", None),
        ),
        "checks": (
            (
                "ck_task_run_status",
                "status IN ('pending','running','paused','done','failed','needs_review')",
            ),
        ),
        "indexes": (("ix_task_run_org_id", ("org_id",), False),),
    },
    "run_manifest": {
        "columns": (
            ("task_id", "CHAR(32)", False, True, None),
            ("started_at", "DATETIME", True, False, None),
            ("agents_used", "JSONB", True, False, None),
            ("skills_used", "JSONB", True, False, None),
            ("models_used", "JSONB", True, False, None),
            ("plan_version", "TEXT", True, False, None),
            ("plan_snapshot", "JSONB", True, False, None),
            ("org_id", "CHAR(32)", False, False, None),
        ),
        "foreign_keys": (
            ("org_id", "org.id", "CASCADE"),
            ("task_id", "task_run.id", "CASCADE"),
        ),
        "checks": (),
        "indexes": (("ix_run_manifest_org_id", ("org_id",), False),),
    },
    "approval": {
        "columns": (
            ("kind", "TEXT", False, False, None),
            ("ref_id", "TEXT", True, False, None),
            ("payload", "JSONB", True, False, None),
            ("status", "TEXT", False, False, "pending"),
            ("assignee", "CHAR(32)", True, False, None),
            ("decided_by", "CHAR(32)", True, False, None),
            ("decided_at", "DATETIME", True, False, None),
            ("id", "CHAR(32)", False, True, "gen_random_uuid()"),
            ("org_id", "CHAR(32)", False, False, None),
        ),
        "foreign_keys": (
            ("assignee", "app_user.id", None),
            ("decided_by", "app_user.id", None),
            ("org_id", "org.id", "CASCADE"),
        ),
        "checks": (
            (
                "ck_approval_kind",
                "kind IN ('plan','dangerous_action','provision_review','skill_review','rework')",
            ),
            ("ck_approval_status", "status IN ('pending','approved','rejected')"),
        ),
        "indexes": (("ix_approval_org_id", ("org_id",), False),),
    },
    "result_envelope": {
        "columns": (
            ("task_id", "CHAR(32)", True, False, None),
            ("node_id", "TEXT", True, False, None),
            ("agent_id", "CHAR(32)", True, False, None),
            ("status", "TEXT", True, False, None),
            ("artifacts", "JSONB", True, False, None),
            ("facts", "JSONB", True, False, None),
            ("summary", "TEXT", True, False, None),
            ("content", "TEXT", True, False, None),
            ("tokens", "INTEGER", True, False, None),
            ("needs_human", "BOOLEAN", False, False, "false"),
            ("created_at", "DATETIME", False, False, "now()"),
            ("id", "CHAR(32)", False, True, "gen_random_uuid()"),
            ("org_id", "CHAR(32)", False, False, None),
        ),
        "foreign_keys": (
            ("agent_id", "agent.id", None),
            ("org_id", "org.id", "CASCADE"),
            ("task_id", "task_run.id", None),
        ),
        "checks": (),
        "indexes": (("ix_result_envelope_org_id", ("org_id",), False),),
    },
    "artifact_descriptor": {
        "columns": (
            ("task_id", "CHAR(32)", True, False, None),
            ("node_id", "TEXT", True, False, None),
            ("modality", "TEXT", True, False, None),
            ("uri", "TEXT", True, False, None),
            ("mime", "TEXT", True, False, None),
            ("caption", "TEXT", True, False, None),
            ("provenance", "JSONB", True, False, None),
            ("meta", "JSONB", True, False, None),
            ("created_at", "DATETIME", False, False, "now()"),
            ("id", "CHAR(32)", False, True, "gen_random_uuid()"),
            ("org_id", "CHAR(32)", False, False, None),
        ),
        "foreign_keys": (
            ("org_id", "org.id", "CASCADE"),
            ("task_id", "task_run.id", None),
        ),
        "checks": (),
        "indexes": (("ix_artifact_descriptor_org_id", ("org_id",), False),),
    },
}

LEGACY_MODELS = (Plan, TaskRun, RunManifest, Approval, ResultEnvelope, ArtifactDescriptor)
KERNEL_MODELS = (
    KernelPlan,
    KernelTaskRun,
    KernelRunManifest,
    KernelApproval,
    KernelResultEnvelope,
    KernelArtifactDescriptor,
)
CORE_CLASS_NAMES = {model.__name__ for model in KERNEL_MODELS}
BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODEL_FILES = {
    "kernel": BACKEND_ROOT / "src/polis/modules/kernel/models.py",
    "planner": BACKEND_ROOT / "src/polis/modules/planner/models.py",
    "observability": BACKEND_ROOT / "src/polis/modules/observability/models.py",
    "memory": BACKEND_ROOT / "src/polis/modules/memory/models.py",
}


def _default(column: object) -> str | None:
    server_default = getattr(column, "server_default", None)
    return str(server_default.arg) if server_default is not None else None


def _table_contract(table_name: str) -> dict[str, object]:
    table = Base.metadata.tables[table_name]
    checks = tuple(
        sorted(
            (constraint.name, str(constraint.sqltext))
            for constraint in table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        )
    )
    return {
        "columns": tuple(
            (column.name, str(column.type), column.nullable, column.primary_key, _default(column))
            for column in table.columns
        ),
        "foreign_keys": tuple(
            sorted(
                (foreign_key.parent.name, foreign_key.target_fullname, foreign_key.ondelete)
                for foreign_key in table.foreign_keys
            )
        ),
        "checks": checks,
        "indexes": tuple(
            sorted(
                (index.name, tuple(column.name for column in index.columns), index.unique)
                for index in table.indexes
            )
        ),
    }


def test_legacy_model_imports_register_expected_tables_once() -> None:
    table_names = [model.__table__.name for model in LEGACY_MODELS]
    assert table_names == list(EXPECTED_TABLE_CONTRACTS)
    assert len({id(model.__table__) for model in LEGACY_MODELS}) == len(LEGACY_MODELS)
    for model in LEGACY_MODELS:
        assert Base.metadata.tables[model.__table__.name] is model.__table__


def test_legacy_table_contract_fingerprint() -> None:
    actual = {name: _table_contract(name) for name in EXPECTED_TABLE_CONTRACTS}
    assert actual == EXPECTED_TABLE_CONTRACTS


def test_legacy_paths_reexport_kernel_class_objects() -> None:
    assert LEGACY_MODELS == KERNEL_MODELS
    for legacy_model, kernel_model in zip(LEGACY_MODELS, KERNEL_MODELS, strict=True):
        assert legacy_model is kernel_model
        assert legacy_model.__table__ is kernel_model.__table__
        assert legacy_model.__module__ == "polis.modules.kernel.models"


def test_core_models_are_declared_only_by_kernel() -> None:
    declarations: dict[str, set[str]] = {}
    for module_name, path in MODEL_FILES.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        declarations[module_name] = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name in CORE_CLASS_NAMES
        }

    assert declarations["kernel"] == CORE_CLASS_NAMES
    assert declarations["planner"] == set()
    assert declarations["observability"] == set()
    assert declarations["memory"] == set()


def test_kernel_models_do_not_reverse_import_legacy_modules() -> None:
    tree = ast.parse(MODEL_FILES["kernel"].read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    forbidden = {
        "polis.modules.planner",
        "polis.modules.runtime",
        "polis.modules.memory",
        "polis.modules.observability",
    }
    assert not any(
        imported == blocked or imported.startswith(f"{blocked}.")
        for imported in imported_modules
        for blocked in forbidden
    )


def test_model_registry_registers_kernel_owned_tables_once() -> None:
    assert model_registry.kernel_models.Plan is KernelPlan
    table_objects = [Base.metadata.tables[model.__tablename__] for model in KERNEL_MODELS]
    assert table_objects == [model.__table__ for model in KERNEL_MODELS]
    assert len({id(table) for table in table_objects}) == len(table_objects)


def test_legacy_http_contract_routes_remain_registered() -> None:
    paths = app.openapi()["paths"]
    routes = {(path, method.upper()) for path, item in paths.items() for method in item}
    assert {
        ("/api/plans", "POST"),
        ("/api/plans/{plan_id}", "GET"),
        ("/api/plans/{plan_id}/run", "GET"),
        ("/api/plans/{plan_id}/manifest", "GET"),
        ("/api/tasks", "POST"),
        ("/api/tasks/{task_id}/runs", "GET"),
        ("/api/approvals", "POST"),
        ("/api/approvals", "GET"),
        ("/api/approvals/{approval_id}/decide", "POST"),
    } <= routes
