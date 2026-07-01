"""对象存储模块（V2-P2a，design v2/05 §9/§16.2）：附件输入 + 结果产物。

- 单桶（`POLIS_MINIO_BUCKET`，默认 polis）+ key 前缀 `{org_id}/{task_id}/{name}` 做多租户隔离；
- 调用方只能寻址自己 org 前缀下的对象（无跨 org 绝对 key 读写口）；
- 凭证走 env，永不入库/日志/上下文（CLAUDE §4）。
"""

from __future__ import annotations

from polis.modules.storage.client import (
    ObjectStore,
    StorageError,
    StorageKeyError,
    object_key,
)

__all__ = ["ObjectStore", "StorageError", "StorageKeyError", "object_key"]
