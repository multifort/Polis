# Polis 后端

FastAPI modular monolith（Python 3.12 + uv）。设计见 [`../docs/design`](../docs/design)，约束见 [`../docs/constraints/12-后端风格约束.md`](../docs/constraints/12-后端风格约束.md)。

## 快速开始
```bash
cd backend
make install        # uv sync 安装依赖（含 dev）
cp .env.example .env
make dev            # uvicorn 起服务 → http://localhost:8000
curl localhost:8000/health     # {"status":"ok",...}
```
文档：`http://localhost:8000/docs`（Swagger）。

## 常用命令
| 命令 | 作用 |
|---|---|
| `make install` | `uv sync` 安装依赖 |
| `make dev` | 起开发服务（热重载，:8000） |
| `make lint` | ruff 检查 |
| `make format` | ruff 格式化 |
| `make type` | mypy 严格类型检查 |
| `make test` | pytest |
| `make check` | lint + type + test（合并门禁本地预演） |

Temporal SDK 自动下载测试服务器受网络或代理限制时，可预先取得官方 `temporal-test-server` 二进制，并用
绝对路径运行同一测试集：

```bash
POLIS_TEMPORAL_TEST_SERVER_PATH=/absolute/path/to/temporal-test-server uv run pytest
```

该变量只传入 SDK 的 `test_server_existing_path`，不跳过 Temporal 测试，也不连接生产或开发 Temporal 数据。

真实对象存储集成测试复用 `backend/.env` 配置的常驻 MinIO：S3 API 使用 `localhost:9000`，`9001` 仅是
Web 控制台。测试使用稳定的 `polis-test` 桶和唯一对象前缀，不会为每轮测试创建新的 MinIO 容器。

## 目录结构
```text
src/polis/
  main.py        应用工厂（组合根）
  config.py      pydantic-settings 配置（环境变量 POLIS_*）
  api/           FastAPI 路由层（health + 聚合 router）
  modules/       业务模块（org/planner/runtime/memory/model/observability）
tests/           pytest（test_health 为 T0.1 验收）
```
> 分层：api → service → domain → repository（单向）。模块边界见 `src/polis/modules/__init__.py`。
> 数据库/迁移（Alembic）、pre-commit 门禁、docker-compose 起栈分别在 M1 / T0.2 / T0.3 落地。
