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

    # 模型接入（M6）。密钥走 env / credential 信封加密，永不入库。
    deepseek_api_key: str = ""  # 开发期系统级 Key；正式走 credential（owner 配置）
    deepseek_base_url: str = "https://api.deepseek.com"
    default_chat_model: str = "deepseek-v4-flash"  # model_catalog.id（同一 DeepSeek Key）
    embedding_base_url: str = "http://localhost:8082"  # 本地 TEI(bge-large-zh-v1.5, arm64)
    kms_master_key: str = ""  # 信封加密主密钥（base64 32B）；生产必填

    # 预算治理（V2-B4）：分层可配置（节点>任务>全局）缺省。tokens 为粗估，非精确计费。
    default_ctx_budget_tokens: int = 4000  # 每节点输入上下文预算（截输入，绝不截输出）
    default_output_max_tokens: int = 2500  # 每节点输出上限（max_tokens）

    # Langfuse 可观测（M6-H）。Polis 自建可观测页面用，Langfuse 只做采集后端。
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3001"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

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
        if not self.kms_master_key:
            problems.append("POLIS_KMS_MASTER_KEY 未设置（凭证信封加密必需）")
        if problems:
            raise RuntimeError(f"生产配置不安全（env={self.env}）：" + "；".join(problems))


@lru_cache
def get_settings() -> Settings:
    """缓存的单例配置，便于测试时 override / clear。"""
    return Settings()
