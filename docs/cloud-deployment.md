# Cloud Deployment Guide

> 目标：证明开发者知道如何将这个项目真正部署上线并维护。
> 以 Alibaba Cloud ECS 为主要示例（AWS EC2 同理）。

## Architecture

```
Internet
   ↓
DNS (A Record) → ECS Public IP
   ↓
Security Group (80/443)
   ↓
Docker Engine
   ├── nginx (web container, :80)
   │     └── React build (static files)
   ├── api container (:8000, internal only)
   │     └── FastAPI + LangGraph
   │           ├── Memory (SQLite volume)
   │           ├── RAG (Local/Chroma volume)
   │           └── Trace (SQLite volume)
   └── (optional) chroma container (:8000, internal)
   ↓
Persistent Volume (runtime/)
```

## 1. ECS / EC2 初始化

### 1.1 选择实例

| 配置项 | 推荐 | 说明 |
|---|---|---|
| 实例规格 | ecs.t6-c1m2.large (2C4G) | 最低要求 2C2G，推荐 4G |
| 操作系统 | Ubuntu 22.04 LTS | 长期支持 |
| 系统盘 | 40GB SSD | 系统 + Docker |
| 数据盘 | 20GB SSD | 挂载 `/data`，存放持久化数据 |
| 公网带宽 | 5Mbps 按量付费 | 个人项目够用 |

### 1.2 首次登录后初始化

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 创建部署用户
sudo useradd -m -s /bin/bash deploy
sudo usermod -aG sudo deploy

# 设置 SSH 密钥登录（禁用密码登录）
sudo sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

### 1.3 挂载数据盘

```bash
sudo mkfs.ext4 /dev/vdb
sudo mkdir -p /data
sudo mount /dev/vdb /data
echo '/dev/vdb /data ext4 defaults 0 2' | sudo tee -a /etc/fstab
sudo chown -R deploy:deploy /data
```

## 2. Docker 安装

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy

# 验证
docker --version
docker compose version

# 设置开机自启
sudo systemctl enable docker
```

## 3. 防火墙 / Security Group

### Security Group 规则

| 方向 | 端口 | 来源 | 说明 |
|---|---|---|---|
| Inbound | 22 | 你的 IP | SSH |
| Inbound | 80 | 0.0.0.0/0 | HTTP |
| Inbound | 443 | 0.0.0.0/0 | HTTPS |
| Inbound | 8000 | 0.0.0.0/0 | API（可选，调试用） |

> 生产环境应关闭 8000 公网访问，仅通过 Nginx 反向代理。

### UFW（可选，双重防护）

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 4. Domain & HTTPS

### 4.1 DNS 配置

在域名服务商（如阿里云 DNS）添加 A 记录：

```
Type: A
Host: support (或 @)
Value: <ECS Public IP>
TTL: 600
```

### 4.2 HTTPS (Let's Encrypt)

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书（Nginx 必须先运行）
sudo certbot --nginx -d support.yourdomain.com

# 自动续期（Certbot 默认已配置）
sudo systemctl status certbot.timer
```

> Docker 内的 Nginx 监听 80，宿主机的 Nginx 监听 443 反向代理到 Docker 80。
> 或者直接在 Docker Nginx 容器中挂载证书。

## 5. 部署应用

### 5.1 准备目录

```bash
mkdir -p /data/ai-support-delivery
cd /data/ai-support-delivery
git clone <repo-url> .
```

### 5.2 配置环境变量

```bash
cp deploy/.env.example deploy/.env
nano deploy/.env
# 修改关键配置：
# - DEEPSEEK_API_KEY=<your-key>
# - APP_ENV=production
# - VECTOR_STORE_PROVIDER=local（或 chroma）
# - WEB_PUBLIC_ORIGIN=https://support.yourdomain.com
```

### 5.3 启动

```bash
cd deploy
docker compose --env-file .env up -d --build
```

### 5.4 验证

```bash
# 检查容器状态
docker compose ps

# 检查 health
curl http://localhost:8000/health
curl http://localhost:8080/

# 查看日志
docker compose logs -f api
docker compose logs -f web
```

## 6. 持久化数据

### 6.1 Volume 映射

Docker Compose 中 `runtime-data` volume 映射到 api 容器的 `/app/runtime`。

生产环境应映射到宿主机目录：

```yaml
volumes:
  - /data/ai-support-delivery/runtime:/app/runtime
```

### 6.2 数据库文件

| 文件 | 用途 | 备份频率 |
|---|---|---|
| `runtime/conversations.db` | Working Memory | 每日 |
| `runtime/memory.db` | Long-term Memory | 每日 |
| `runtime/events.db` | 指标数据 | 每日 |
| `runtime/observability.db` | Trace 数据 | 每日 |
| `runtime/chroma/` | 向量索引 | rebuildable |

## 7. 日志

### 7.1 容器日志

```bash
# 实时查看
docker compose logs -f

# 最近 100 行
docker compose logs --tail 100 api
```

### 7.2 日志轮转

Docker 默认 json-file 驱动不轮转。在 `/etc/docker/daemon.json` 配置：

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

重启 Docker：`sudo systemctl restart docker`

## 8. Health Check & Restart

Docker Compose 已配置：

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
  interval: 10s
  timeout: 3s
  retries: 3
restart: unless-stopped
```

容器异常退出会自动重启。

## 9. Backup

### 9.1 自动备份脚本

```bash
#!/bin/bash
# /data/scripts/backup.sh
BACKUP_DIR=/data/backups
SOURCE_DIR=/data/ai-support-delivery/runtime
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR
tar -czf $BACKUP_DIR/runtime_$DATE.tar.gz -C $SOURCE_DIR .

# 保留最近 7 天
find $BACKUP_DIR -name "runtime_*.tar.gz" -mtime +7 -delete
```

### 9.2 Cron 定时

```bash
# 每天凌晨 3 点备份
0 3 * * * /data/scripts/backup.sh >> /data/logs/backup.log 2>&1
```

## 10. Upgrade

### 10.1 滚动更新

```bash
cd /data/ai-support-delivery
git pull origin main
cd deploy
docker compose --env-file .env up -d --build
```

### 10.2 回滚

```bash
# 回退到上一个版本
git log --oneline -5
git checkout <previous-commit>
docker compose --env-file .env up -d --build
```

### 10.3 数据回滚

```bash
# 停止服务
docker compose down

# 恢复数据
tar -xzf /data/backups/runtime_20260815_030000.tar.gz -C /data/ai-support-delivery/runtime/

# 重启
docker compose up -d
```

## 11. Monitoring (Basic)

### 11.1 简单监控脚本

```bash
#!/bin/bash
# /data/scripts/health_check.sh
HEALTH_URL=http://localhost:8000/health
WEB_URL=http://localhost:8080/
ALERT_EMAIL=your-email@example.com

if ! curl -sf $HEALTH_URL > /dev/null; then
    echo "API is DOWN" | mail -s "ALERT: API Down" $ALERT_EMAIL
fi

if ! curl -sf $WEB_URL > /dev/null; then
    echo "Web is DOWN" | mail -s "ALERT: Web Down" $ALERT_EMAIL
fi
```

### 11.2 Cron 监控

```bash
# 每 5 分钟检查一次
*/5 * * * * /data/scripts/health_check.sh
```

## 12. Notes

- 本文档不声称"已部署到云"。它是一个可执行的部署方案。
- SQLite 适合个人项目/小规模演示。生产高并发应替换为 PostgreSQL。
- Chroma 适合中小规模知识库（< 100K 文档）。更大规模应考虑专用向量数据库服务。
- DeepSeek API 需要网络可达。国内 ECS 可能需要配置代理。
