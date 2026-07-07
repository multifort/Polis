"""R4 role_template 复用率验证门的纯统计口径测试。"""

from __future__ import annotations

import uuid

from scripts.r4.role_template_reuse_gate import (
    RoleTemplateKey,
    compute_reuse_summary,
    is_benchmark_org_name,
)


def test_r4_reuse_gate_marks_benchmark_org_names() -> None:
    assert is_benchmark_org_name("M7验收门-1783332151") is True
    assert is_benchmark_org_name("R4复用率样本公司") is True
    assert is_benchmark_org_name("R4自然复用Smoke公司") is True
    assert is_benchmark_org_name("真实采购公司") is False
    assert is_benchmark_org_name(None) is False


def test_r4_reuse_summary_counts_follow_up_manifest_occurrences() -> None:
    org_id = uuid.uuid4()
    templates = [
        RoleTemplateKey(org_id=org_id, name="弹性组队·market.sentiment"),
        RoleTemplateKey(org_id=org_id, name="弹性组队·risk.scan"),
    ]
    manifests = [
        (org_id, {"n1": "弹性组队·market.sentiment"}),
        (org_id, {"n1": "弹性组队·market.sentiment", "n2": "弹性组队·risk.scan"}),
    ]

    summary = compute_reuse_summary(
        templates,
        manifests,
        threshold=0.6,
        min_occurrences=2,
    )

    assert summary.total == 2
    assert summary.reused == 1
    assert summary.rate == 0.5
    assert summary.passed is False


def test_r4_reuse_summary_ignores_legacy_capability_lists_and_cross_org() -> None:
    org_id = uuid.uuid4()
    other_org = uuid.uuid4()
    template = RoleTemplateKey(org_id=org_id, name="弹性组队·market.sentiment")
    summary = compute_reuse_summary(
        [template],
        [
            (org_id, {"n1": ["market.sentiment"]}),
            (other_org, {"n1": "弹性组队·market.sentiment"}),
            (org_id, {"n1": "弹性组队·market.sentiment"}),
            (org_id, {"n2": "弹性组队·market.sentiment"}),
        ],
        threshold=0.6,
        min_occurrences=2,
    )

    assert summary.occurrences[template] == 2
    assert summary.passed is True
