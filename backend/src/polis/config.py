"""应用配置：全部走环境变量（前缀 POLIS_），不硬编码、密钥不入库（CLAUDE.md §4）。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# JWT dev 占位密钥（生产必须用 POLIS_JWT_SECRET 覆盖；启动校验见 validate_for_prod）
# 公开的 dev 占位值，非真实密钥；validate_for_prod 已阻止它进生产
DEV_JWT_SECRET = "dev-only-insecure-secret-change-in-prod-0123456789"  # nosec B105


class Settings(BaseSettings):
    """运行时配置。来源优先级：环境变量 > .env > 默认值。"""

    model_config = SettingsConfigDict(
        env_prefix="POLIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Polis"
    env: str = "dev"  # dev|staging|prod
    version: str = "0.1.0"

    # 数据库（asyncpg 驱动）。真实连接串走 POLIS_DATABASE_URL（见 backend/.env）。
    database_url: str = "postgresql+asyncpg://polis:polis@localhost:5432/polis"

    # 认证（09 §3）。生产必须用 POLIS_JWT_SECRET 覆盖，禁用默认值。
    jwt_secret: str = DEV_JWT_SECRET
    jwt_alg: str = "HS256"
    access_ttl_min: int = 15
    refresh_ttl_days: int = 14

    # Temporal 编排服务地址（M3-C）
    temporal_addr: str = "localhost:7233"

    # 前端跨域（CORS）。dev 默认放开（用 Bearer token，非 cookie）；生产用 POLIS_CORS_ORIGINS 收紧。
    cors_origins: list[str] = ["*"]

    def is_prod(self) -> bool:
        """非 dev/test/local 即视为需收紧的生产类环境。"""
        return self.env.lower() not in ("dev", "test", "local")

    def validate_for_prod(self) -> None:
        """生产类环境下 fail-closed 校验不安全配置（TD-013）。dev 不受影响。

        覆盖：JWT 默认密钥/过短、CORS 通配。限流/找回密码仍为后续项。
        """
        if not self.is_prod():
            return
        problems: list[str] = []
        if self.jwt_secret == DEV_JWT_SECRET:
            problems.append("POLIS_JWT_SECRET 仍为 dev 默认值")
        elif len(self.jwt_secret) < 32:
            problems.append("POLIS_JWT_SECRET 长度不足 32 字符")
        if "*" in self.cors_origins:
            problems.append("POLIS_CORS_ORIGINS 含通配 '*'，生产须收紧到具体域")
        if problems:
            raise RuntimeError(f"生产配置不安全（env={self.env}）：" + "；".join(problems))


@lru_cache
def get_settings() -> Settings:
    """缓存的单例配置，便于测试时 override / clear。"""
    return Settings()
