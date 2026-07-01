# ADR-0014：任务为独立可复用实体 + 引入对象存储(MinIO)

- 状态：accepted
- 日期：2026-06-22（对象存储部分 2026-07-01 随 T7.6 落地）
- 关联：[V2 · 产品形态](../design/v2/05-产品形态（场景·任务·执行记录·结果·看板）.md)；[07-数据·部署·演进路线](../design/07-数据·部署·演进路线.md)

## 背景
V1 产品只有"任务/计划清单"：看不到历史、无附件上传入口、结果无法导出。用户要"任务可复用 + 每次执行记录（过程+结果下载）"，并把产品主线串起来。

## 选项
- 任务建模：复用现有 `plan`（加 name/输入/允许多次跑）vs **新建 `task` 表**（任务为独立实体，plan 退为运行 DAG 快照）。
- 附件/结果存储：内联 DB / 文件系统 / **对象存储(MinIO)**。
- 导出格式：md+pdf 起步 vs 一上来 Word/Excel。

## 决定
- **任务=独立可复用实体（新 `task` 表）**：`task(name/scenario_ref/goal/input_schema/inputs/...)`；`plan` 退为"某次运行的 DAG 快照"；`task_run` 加 `task_id`（1 任务 : N 执行记录）。
- **场景/任务/执行记录三层**（模板→实例→运行）；任务为主入口，场景可选/自动沉淀。
- **引入 MinIO** 作对象存储：附件上传 + 结果产物，`artifact_descriptor.uri = s3://{bucket}/{org_id}/...`（按 org 前缀隔离），凭证走 env。
- 导出**先 Markdown + PDF**，Word/Excel 后置。

## 后果
- 正面：历史可追溯、任务可复用、结果可移植导出；产品主线打通；附件输入入口补齐。
- 负面/代价：新增 MinIO 运维（docker-compose 一服务）；`task`/`plan` 语义迁移（向后兼容：task_id nullable，旧 plan/run 仍可用）。
- 影响范围：planner（plan 语义）、task_run、artifact、前端 IA、infra（MinIO）、RLS（task/artifact 带 org_id）。

## 落地口径（对象存储部分，T7.6，2026-07-01）
- **单桶** `POLIS_MINIO_BUCKET`（默认 `polis`），多租户靠 **key 前缀** `{org_id}/{task_id}/{name}`——不按 org 建桶。
- `artifact_descriptor.uri = s3://{bucket}/{org_id}/{task_id}/{name}`；key 三段做路径穿越校验，寻址不逃逸出本 org 前缀。
- 下载走 **presigned URL（短时，默认 15min）**，不做公开读；上传/读取/删除均经 `modules/storage.ObjectStore`（minio SDK 同步 + `asyncio.to_thread`）。
- 凭证走 env（`POLIS_MINIO_*`），永不入库/日志。生产 fail-closed 校验（SECURE=true + secret 已设）随 **P2b** 把存储接进启动链时补。
- 隔离经 testcontainers MinIO 集成测试验证（org A 读不到 org B 前缀）；实测 compose 服务 healthy、9000 API / 9001 控制台可达、客户端回环通。
- MVP **不引** S3 生命周期/版本化（后置）。
