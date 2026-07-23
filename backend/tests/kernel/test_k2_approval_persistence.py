"""K2-T2 PostgreSQL contracts for Approval V2 and append-only decisions."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import polis.db.models as model_registry
from polis.db.models import Base
from polis.modules.kernel.application.approval_store import ApprovalMutationStore
from polis.modules.kernel.domain.approval import revoke_approval
from polis.modules.kernel.domain.policy import ActorIdentity
from polis.modules.kernel.errors import KernelProtocolError
from polis.modules.kernel.models import Approval, ApprovalDecision

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _sync_url(pg_url: str) -> str:
    return pg_url.replace("+asyncpg", "+psycopg2")


def _alembic_config(pg_url: str) -> Config:
    config = Config(str(REPOSITORY_ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "backend/migrations"))
    config.set_main_option("sqlalchemy.url", pg_url)
    return config


def _create_org(connection: Any, label: str) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = connection.execute(
        text("INSERT INTO app_user (email) VALUES (:email) RETURNING id"),
        {"email": f"approval_{label}_{uuid.uuid4().hex}@polis.dev"},
    ).scalar_one()
    org_id = connection.execute(
        text("INSERT INTO org (name, owner_user_id) VALUES (:name, :user_id) RETURNING id"),
        {"name": f"Approval {label}", "user_id": user_id},
    ).scalar_one()
    return cast(uuid.UUID, user_id), cast(uuid.UUID, org_id)


def _insert_v2_approval(
    connection: Any,
    *,
    org_id: uuid.UUID,
    requester_id: uuid.UUID,
    command_receipt_id: uuid.UUID,
) -> uuid.UUID:
    domain_id = connection.execute(
        text(
            "SELECT id FROM domain_package_version "
            "WHERE key = 'kernel.governance' AND version = '1.0.0'"
        )
    ).scalar_one()
    return cast(
        uuid.UUID,
        connection.execute(
            text(
                "INSERT INTO approval ("
                "org_id,kind,status,approval_schema_version,command_family,"
                "domain_package_version_id,command_type,command_fingerprint,"
                "approval_purpose,version,requested_by_kind,requested_by_ref,"
                "required_role_slots,expires_at,command_receipt_id,resume_mode,"
                "payload_snapshot) VALUES ("
                ":org,NULL,'pending',2,'definition',:domain,:command,:fingerprint,"
                "'command_policy',1,'human',:requester,ARRAY['owner'],"
                "transaction_timestamp() + interval '1 hour',:receipt,'manual',"
                "CAST(:payload AS jsonb)) RETURNING id"
            ),
            {
                "org": org_id,
                "domain": domain_id,
                "command": "publish_work_definition",
                "fingerprint": "a" * 64,
                "requester": requester_id,
                "receipt": command_receipt_id,
                "payload": '{"key":"core.example"}',
            },
        ).scalar_one(),
    )


def test_models_register_approval_v2_and_decision_table() -> None:
    assert model_registry.kernel_models is not None
    assert Approval.__tablename__ == "approval"
    assert ApprovalDecision.__tablename__ == "approval_decision"
    assert "approval_decision" in Base.metadata.tables
    approval_columns = set(Approval.__table__.columns.keys())
    assert {
        "approval_schema_version",
        "command_family",
        "command_fingerprint",
        "command_receipt_id",
        "required_role_slots",
        "version",
    } <= approval_columns


def test_approval_v2_schema_constraints_decision_uniqueness_and_rls(pg_url: str) -> None:
    engine = create_engine(_sync_url(pg_url))
    connection = engine.connect()
    transaction = connection.begin()
    try:
        user_a, org_a = _create_org(connection, "A")
        user_b, org_b = _create_org(connection, "B")
        receipt_a = uuid.uuid4()
        approval_a = _insert_v2_approval(
            connection,
            org_id=org_a,
            requester_id=user_a,
            command_receipt_id=receipt_a,
        )
        approval_b = _insert_v2_approval(
            connection,
            org_id=org_b,
            requester_id=user_b,
            command_receipt_id=uuid.uuid4(),
        )

        # Legacy V1 remains writable for the old adapter during gradual migration.
        connection.execute(
            text(
                "INSERT INTO approval (org_id,kind,ref_id,status) "
                "VALUES (:org,'plan','legacy-plan','pending')"
            ),
            {"org": org_a},
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO approval (org_id,kind,ref_id,status) "
                    "VALUES (:org,'plan','legacy-invalid','expired')"
                ),
                {"org": org_a},
            )
        with pytest.raises(IntegrityError), connection.begin_nested():
            _insert_v2_approval(
                connection,
                org_id=org_a,
                requester_id=user_a,
                command_receipt_id=receipt_a,
            )

        family_command_id = uuid.uuid4()
        decision_id = connection.execute(
            text(
                "INSERT INTO approval_decision ("
                "org_id,approval_id,approval_version,family_command_id,"
                "requested_action,outcome_status,"
                "decided_by_kind,decided_by_ref) VALUES "
                "(:org,:approval,2,:command,'approve','approved','human',:actor) "
                "RETURNING id"
            ),
            {
                "org": org_a,
                "approval": approval_a,
                "command": family_command_id,
                "actor": user_a,
            },
        ).scalar_one()
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                text("UPDATE approval_decision SET reason_note = 'tampered' WHERE id = :decision"),
                {"decision": decision_id},
            )

        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO approval_decision ("
                    "org_id,approval_id,approval_version,family_command_id,"
                    "requested_action,outcome_status,"
                    "decided_by_kind,decided_by_ref) VALUES "
                    "(:org,:approval,2,:command,'approve','approved','human',:actor)"
                ),
                {
                    "org": org_a,
                    "approval": approval_a,
                    "command": uuid.uuid4(),
                    "actor": user_a,
                },
            )

        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO approval ("
                    "org_id,kind,status,approval_schema_version,command_family,"
                    "command_type,command_fingerprint,approval_purpose,version,"
                    "requested_by_kind,requested_by_ref,required_role_slots,expires_at,"
                    "command_receipt_id,resume_mode,payload_snapshot) VALUES ("
                    ":org,NULL,'pending',2,'definition','publish_work_definition',"
                    ":fingerprint,'command_policy',1,'human',:requester,ARRAY['owner'],"
                    "transaction_timestamp() + interval '1 hour',:receipt,'manual','{}')"
                ),
                {
                    "org": org_a,
                    "fingerprint": "b" * 64,
                    "requester": user_a,
                    "receipt": uuid.uuid4(),
                },
            )

        connection.execute(text("SET LOCAL ROLE polis_app"))
        connection.execute(
            text("SELECT set_config('app.current_org', :org, true)"),
            {"org": str(org_a)},
        )
        assert connection.execute(
            text("SELECT id FROM approval_decision ORDER BY id")
        ).scalars().all() == [decision_id]
        assert connection.execute(
            text("SELECT id FROM approval WHERE id IN (:a,:b) ORDER BY id"),
            {"a": approval_a, "b": approval_b},
        ).scalars().all() == [approval_a]
        connection.execute(text("SELECT set_config('app.current_org', '', true)"))
        assert connection.execute(text("SELECT count(*) FROM approval_decision")).scalar_one() == 0
        connection.execute(text("RESET ROLE"))
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_concurrent_family_mutations_lock_approval_and_write_one_decision(
    pg_url: str,
) -> None:
    sync_engine = create_engine(_sync_url(pg_url))
    with sync_engine.begin() as connection:
        user_id, org_id = _create_org(connection, "Concurrent")
        approval_id = _insert_v2_approval(
            connection,
            org_id=org_id,
            requester_id=user_id,
            command_receipt_id=uuid.uuid4(),
        )

    async def exercise() -> tuple[str, str]:
        engine = create_async_engine(pg_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_locked = asyncio.Event()
        release_first = asyncio.Event()

        async def mutate(*, first: bool) -> str:
            try:
                async with factory() as session, session.begin():
                    store = ApprovalMutationStore(session)
                    row = await store.lock_v2(
                        org_id=org_id,
                        approval_id=approval_id,
                    )
                    if first:
                        first_locked.set()
                        await release_first.wait()
                    snapshot = store.snapshot(row)
                    mutation = revoke_approval(
                        snapshot,
                        family_command_type="revoke_definition_approval",
                        expected_approval_version=snapshot.version,
                        actor=ActorIdentity("service", str(uuid.uuid4())),
                        occurred_at=snapshot.expires_at,
                        reason="TARGET_CHANGED",
                    )
                    await store.stage(
                        row=row,
                        mutation=mutation,
                        family_command_id=uuid.uuid4(),
                    )
                return "succeeded"
            except KernelProtocolError as exc:
                return exc.code

        try:
            first_task = asyncio.create_task(mutate(first=True))
            await first_locked.wait()
            second_task = asyncio.create_task(mutate(first=False))
            await asyncio.sleep(0.05)
            release_first.set()
            return await first_task, await second_task
        finally:
            await engine.dispose()

    try:
        assert asyncio.run(exercise()) == ("succeeded", "APPROVAL_INVALID")
        with sync_engine.connect() as connection:
            row = connection.execute(
                text("SELECT status,version FROM approval WHERE id = :id"),
                {"id": approval_id},
            ).one()
            assert row == ("revoked", 2)
            assert (
                connection.execute(
                    text("SELECT count(*) FROM approval_decision WHERE approval_id = :approval"),
                    {"approval": approval_id},
                ).scalar_one()
                == 1
            )
    finally:
        with sync_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM org WHERE id = :org"),
                {"org": org_id},
            )
        sync_engine.dispose()


def test_approval_v2_migration_downgrade_upgrade_and_no_drift(pg_url: str) -> None:
    config = _alembic_config(pg_url)
    command.downgrade(config, "b2c3d4e5f6a7")
    engine = create_engine(_sync_url(pg_url))
    try:
        inspector = inspect(engine)
        assert "approval_decision" not in inspector.get_table_names()
        assert "approval_schema_version" not in {
            column["name"] for column in inspector.get_columns("approval")
        }
    finally:
        engine.dispose()
    command.upgrade(config, "head")
    command.check(config)
