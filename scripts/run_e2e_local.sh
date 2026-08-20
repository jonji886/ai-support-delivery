#!/usr/bin/env bash
# 本地浏览器级 E2E：启动 Mock 客户系统 + API + Vite dev server，再运行 Playwright。
# 用法：
#   scripts/run_e2e_local.sh                # 全部本地
#   BASE_URL=https://<domain> scripts/run_e2e_local.sh   # 只跑远程 E2E（不启动本地服务）
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ -n "${BASE_URL:-}" ]; then
  echo "[e2e] 远程模式 BASE_URL=$BASE_URL"
  cd apps/web
  npx playwright test
  exit 0
fi

# 1. 启动 Mock 客户系统（随机端口）
echo "[e2e] 启动 Mock 客户系统..."
MOCK_PORT=$(( (RANDOM % 1000) + 8100 ))
MOCK_BASE="http://127.0.0.1:$MOCK_PORT"
PYTHONPATH="$ROOT" .venv/bin/python -m uvicorn apps.mock_customer_systems.app:app \
  --host 127.0.0.1 --port "$MOCK_PORT" --log-level warning &
MOCK_PID=$!

# 2. 启动 API（连接 Mock 客户系统）
echo "[e2e] 启动 API (port 8000)..."
MOCK_CUSTOMER_SYSTEMS_BASE_URL="$MOCK_BASE" PYTHONPATH="$ROOT" \
  .venv/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --log-level warning &
API_PID=$!

# 3. 启动 Vite dev server（Playwright 将通过 http://127.0.0.1:5173 访问）
echo "[e2e] 启动 Vite dev server (port 5173)..."
cd apps/web
npm run dev > /tmp/ai-support-vite.log 2>&1 &
WEB_PID=$!

cleanup() {
  echo "[e2e] 清理进程..."
  kill "$MOCK_PID" "$API_PID" "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT

# 等待服务就绪
for _ in $(seq 1 150); do
  curl -fsS "$MOCK_BASE/health" >/dev/null 2>&1 && break
  sleep 0.1
done
for _ in $(seq 1 150); do
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 0.1
done
for _ in $(seq 1 150); do
  curl -fsS http://127.0.0.1:5173/ >/dev/null 2>&1 && break
  sleep 0.1
done

# 4. 运行 Playwright
echo "[e2e] 运行 Playwright..."
npx playwright test
