#!/bin/bash
# Postgres 首次初始化：在主库启用 pgvector，并为 temporal/langfuse/litellm 建独立库。
# 仅在数据卷为空的首次启动时执行（docker-entrypoint-initdb.d）。
set -euo pipefail

# 主库(polis)启用 pgvector（记忆/向量检索用，见 docs/design/05）
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'SQL'
  CREATE EXTENSION IF NOT EXISTS vector;
SQL

# 共享同一 Postgres 实例，但各组件独立数据库（低运维：少一组容器）
for db in temporal temporal_visibility langfuse litellm; do
  exists=$(psql -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'" \
            --username "$POSTGRES_USER" --dbname "$POSTGRES_DB")
  if [ "$exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      -c "CREATE DATABASE ${db}"
    echo "created database ${db}"
  fi
done
