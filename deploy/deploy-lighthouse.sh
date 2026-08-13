#!/usr/bin/env bash
# Lighthouse / CVM Docker Compose 部署脚本
# 用法：bash deploy/deploy-lighthouse.sh
# 依赖：已安装 docker 与 docker compose 插件、git、能访问 github.com
set -euo pipefail

REPO_URL="https://github.com/jonji886/ai-support-delivery.git"
APP_DIR="${APP_DIR:-$HOME/ai-support-delivery}"
BRANCH="${BRANCH:-main}"

echo "==> 目标目录：$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "==> 克隆仓库"
  git clone "$REPO_URL" "$APP_DIR"
else
  echo "==> 更新仓库"
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
fi

cd "$APP_DIR"

# 生成 .env（如不存在）。请在此填入真实 DEEPSEEK_API_KEY 与公网 IP。
if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> 已生成 .env，请编辑 DEEPSEEK_API_KEY 与 WEB_PUBLIC_ORIGIN 后重新运行。"
  echo "    例如：WEB_PUBLIC_ORIGIN=http://<你的公网IP>:8080"
  exit 0
fi

echo "==> 拉取/构建镜像并启动"
docker compose -f deploy/docker-compose.yml up -d --build

echo "==> 等待健康检查"
for i in $(seq 1 30); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "==> API 健康：OK"
    break
  fi
  sleep 2
done

echo "==> 部署完成"
echo "    API:    http://<公网IP>:8000/health"
echo "    前端:   http://<公网IP>:8080"
