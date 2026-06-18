# Polis 基础设施（本地 / MVP）

4 个外部依赖（docs/design/07 §3）。Polis 应用本体不在此容器化（E8 后置），用 `../backend` 的 `make dev` 本地跑。

## 启动
```bash
cd infra
cp .env.example .env        # 按需改密钥（openssl rand -base64 32）
docker compose up -d
docker compose ps
```

## 服务与端口
| 服务 | 镜像 | 端口 | 用途 |
|---|---|---|---|
| postgres | pgvector/pgvector:pg18 | 5432 | 主库(+pgvector) + temporal/langfuse/litellm 各自库 |
| temporal | temporalio/auto-setup | 7233 | 工作流编排（gRPC） |
| temporal-ui | temporalio/ui | 8233 | Temporal 控制台（http://localhost:8233） |
| litellm | ghcr.io/berriai/litellm | 4000 | 模型网关（http://localhost:4000） |
| langfuse | langfuse/langfuse:2 | 3000 | 可观测/评估（http://localhost:3000） |

> 首次启动由 `postgres/init-db.sh` 在主库启用 `vector` 扩展，并建 `temporal`/`temporal_visibility`/`langfuse`/`litellm` 库。
> pg18+ 数据卷挂在 `/var/lib/postgresql`（非旧版 `/data`）。

> 国内拉镜像慢时，可用镜像源拉取后 retag 成上表标签，例如：
> ```bash
> docker pull <mirror>/pgvector/pgvector:pg18-bookworm-linuxarm64
> docker tag  <mirror>/pgvector/pgvector:pg18-bookworm-linuxarm64 pgvector/pgvector:pg18
> docker compose up -d --pull never postgres
> ```

## 应用连接（backend/.env）
```
POLIS_DATABASE_URL=postgresql+asyncpg://polis:<pwd>@localhost:5432/polis
POLIS_TEMPORAL_ADDR=localhost:7233
POLIS_LITELLM_BASE=http://localhost:4000
```

## 停止 / 清空
```bash
docker compose down          # 停服务，保留数据卷
docker compose down -v       # 连数据卷一起删（谨慎）
```
