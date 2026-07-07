# Polis 基础设施与整栈 compose（本地 / MVP）

默认只起基础设施；应用本体（后端 API、worker、前端）通过 `app` profile 启用。

## 启动基础设施
```bash
cd infra
cp .env.example .env        # 按需改密钥（openssl rand -base64 32）
docker compose up -d
docker compose ps
```

## 启动整栈
```bash
cd infra
cp .env.example .env
docker compose --env-file .env --profile app up -d
docker compose ps
```

`api` 容器启动时会先执行 `alembic upgrade head`，再启动 FastAPI；`worker` 复用同一个后端镜像；`web` 镜像在构建时读取 `NEXT_PUBLIC_API_BASE`，本地默认指向 `http://localhost:8000`。
本地 `.env.example` 默认给 `NODE_IMAGE` 配了 arm64 镜像源，便于国内网络 / Apple Silicon 构建；Docker Hub 可达时可改回 `node:22-alpine`。
找回密码邮件本地默认写入后端容器内 `var/mail-outbox.jsonl`；生产或 staging 使用 `.env.production.example` 中的 SMTP 配置。

## 服务与端口
| 服务 | 镜像 | 端口 | 用途 |
|---|---|---|---|
| postgres | pgvector/pgvector:pg18 | 5432 | 主库(+pgvector) + temporal/langfuse/litellm 各自库 |
| temporal | temporalio/auto-setup | 7233 | 工作流编排（gRPC） |
| temporal-ui | temporalio/ui | 8233 | Temporal 控制台（http://localhost:8233） |
| litellm | ghcr.io/berriai/litellm | 4000 | 模型网关（http://localhost:4000） |
| langfuse | langfuse/langfuse | 3001 | 可观测/评估（http://localhost:3001） |
| minio | minio/minio | 9000 / 9001 | S3 API / 控制台 |
| text-embeddings | TEI | 8082 | 本地 embedding |
| api | polis-api:local | 8000 | FastAPI / OpenAPI |
| worker | polis-api:local | — | Temporal worker |
| web | polis-web:local | 3000 | Next.js 前端 |

> 首次启动由 `postgres/init-db.sh` 在主库启用 `vector` 扩展，并建 `temporal`/`temporal_visibility`/`langfuse`/`litellm` 库。
> pg18+ 数据卷挂在 `/var/lib/postgresql`（非旧版 `/data`）。

> 国内拉镜像慢时，可用镜像源拉取后 retag 成上表标签，例如：
> ```bash
> docker pull <mirror>/pgvector/pgvector:pg18-bookworm-linuxarm64
> docker tag  <mirror>/pgvector/pgvector:pg18-bookworm-linuxarm64 pgvector/pgvector:pg18
> docker compose up -d --pull never postgres
> ```

## 本地源码运行连接（backend/.env）
```
POLIS_DATABASE_URL=postgresql+asyncpg://polis:<pwd>@localhost:5432/polis
POLIS_TEMPORAL_ADDR=localhost:7233
POLIS_LITELLM_BASE=http://localhost:4000
```

## 容器内应用连接
compose 的 `api`/`worker` 使用 service name，不使用 localhost：

```text
postgres:5432
temporal:7233
text-embeddings:80
minio:9000
langfuse:3000
```

生产或 staging 可从 `.env.production.example` 复制模板，再由密钥系统注入真实值。

## 停止 / 清空
```bash
docker compose down          # 停服务，保留数据卷
docker compose down -v       # 连数据卷一起删（谨慎）
```
