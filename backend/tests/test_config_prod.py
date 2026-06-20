"""单元测试：生产配置 fail-closed 校验（TD-013）。纯逻辑，无 DB。"""

from __future__ import annotations

import pytest

from polis.config import DEV_JWT_SECRET, Settings

_STRONG = "x" * 40  # ≥32 的强密钥占位


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "env": "prod",
        "jwt_secret": _STRONG,
        "cors_origins": ["https://a.com"],
    }
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_dev_env_skips_validation() -> None:
    # dev 即使用默认密钥 + 通配 CORS 也不报错
    s = Settings(env="dev", jwt_secret=DEV_JWT_SECRET, cors_origins=["*"])
    s.validate_for_prod()  # 不抛


def test_prod_safe_config_passes() -> None:
    _settings().validate_for_prod()  # 不抛


def test_prod_default_jwt_rejected() -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _settings(jwt_secret=DEV_JWT_SECRET).validate_for_prod()


def test_prod_short_jwt_rejected() -> None:
    with pytest.raises(RuntimeError, match="长度不足"):
        _settings(jwt_secret="tooshort").validate_for_prod()


def test_prod_wildcard_cors_rejected() -> None:
    with pytest.raises(RuntimeError, match="CORS"):
        _settings(cors_origins=["*"]).validate_for_prod()


def test_prod_reports_multiple_problems() -> None:
    with pytest.raises(RuntimeError) as exc:
        _settings(jwt_secret=DEV_JWT_SECRET, cors_origins=["*"]).validate_for_prod()
    msg = str(exc.value)
    assert "JWT_SECRET" in msg and "CORS" in msg
