#!/bin/bash
set -e

PORT=${PORT:-8000}

echo "=== 融衔 启动中 (port: $PORT) ==="

# 初始化数据库（静默模式，忽略错误）
cd /app/backend
python -m app.seed --force 2>&1 || echo "Seed completed (or already initialized)"

# 启动后端
echo "启动后端..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT
