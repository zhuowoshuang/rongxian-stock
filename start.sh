#!/bin/bash
set -e

echo "=== 融衔 启动中 ==="

# 初始化数据库
cd /app/backend
python -m app.seed

# 启动后端（后台）
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# 等待后端启动
echo "等待后端启动..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "后端已启动"
        break
    fi
    sleep 1
done

# 启动前端
cd /app/frontend
echo "启动前端..."
PORT=3000 npm start &
FRONTEND_PID=$!

echo "=== 融衔 已启动 ==="
echo "前端: http://localhost:3000"
echo "后端: http://localhost:8000"
echo "API 文档: http://localhost:8000/docs"

# 等待任一进程退出
wait -n $BACKEND_PID $FRONTEND_PID
