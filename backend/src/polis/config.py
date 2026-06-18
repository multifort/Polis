"""应用配置：全部走环境变量（前缀 POLIS_），不硬编码、密钥不入库（CLAUDE.md §4）。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    jwt_secret: str = "dev-insecure-change-me"
    jwt_alg: str = "HS256"
    access_ttl_min: int = 15
    refresh_ttl_days: int = 14

    # 前端跨域（CORS）
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """缓存的单例配置，便于测试时 override / clear。"""
    return Settings()
