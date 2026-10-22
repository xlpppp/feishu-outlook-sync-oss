# 部署指南

## 前置条件

- 已完成 [ADMIN-SETUP.md](ADMIN-SETUP.md) 中的微软与飞书应用注册
- 一台可公网访问的 Linux 服务器（或内网 + 反向代理）
- HTTPS 域名（生产强烈建议；OAuth 与 `COOKIE_SECURE=true` 依赖）
- Docker + Docker Compose，或 Python 3.11+

将回调 URL 配成：

- `https://YOUR_DOMAIN/oauth/microsoft/callback`
- `https://YOUR_DOMAIN/oauth/feishu/callback`

---

## `.env` 怎么填（双向同步）

**详细逐项说明（含 SECRET_KEY / TOKEN_ENCRYPTION_KEY 生成命令）→ [ENV.md](ENV.md)**

最短路径：

```bash
cp .env.example .env

# 1) 自定义会话密钥
openssl rand -hex 32
# 把结果写入 SECRET_KEY=

# 2) Fernet 加密密钥（专用格式，不是普通密码）
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 把结果写入 TOKEN_ENCRYPTION_KEY=

# 3) 填 PUBLIC_BASE_URL=https://你的域名
# 4) 填 MS_CLIENT_ID / MS_CLIENT_SECRET（Azure 应用注册，见 ADMIN-SETUP.md）
# 5) 填 FEISHU_APP_ID / FEISHU_APP_SECRET（飞书开放平台）
# 6) 保持 FEISHU_SCOPES 含 calendar:calendar（双向写飞书必需）
# 7) OUTLOOK_CALENDAR_NAME / FEISHU_SYNC_CALENDAR_NAME 默认即可
```

| 问题 | 答案 |
|------|------|
| `SECRET_KEY` 是我自定义的随机数吗？ | **是**。用 `openssl rand -hex 32` 等生成任意长随机串即可。 |
| `TOKEN_ENCRYPTION_KEY` 填什么？ | **Fernet 密钥**（上面 Python 一行生成）。手写普通字符串无效。丢失则全员重授权。 |
| 双向还要改别的吗？ | 保持默认日历名；飞书权限含写 scope；用户在网页选「双向」。 |

---

## 方式 A：Docker Compose（推荐）

```bash
git clone https://github.com/xlpppp/feishu-outlook-sync-oss.git && cd feishu-outlook-sync-oss
cp .env.example .env
# 编辑 .env，至少设置：
#   PUBLIC_BASE_URL=https://YOUR_DOMAIN
#   SECRET_KEY=<随机长串>
#   TOKEN_ENCRYPTION_KEY=<Fernet>
#   MS_CLIENT_ID / MS_CLIENT_SECRET
#   FEISHU_APP_ID / FEISHU_APP_SECRET
#   COOKIE_SECURE=true

# 若宿主机 8000 已被占用，在 .env 设 HOST_PORT=18000（默认已是 18000）
# 容器内仍固定监听 8000；Nginx 反代到 127.0.0.1:18000

docker compose up -d --build
docker compose logs -f
```

数据卷：`sync-data` 挂载到容器内 `/data`，SQLite 文件为 `/data/sync.db`。

健康检查：

```bash
curl -s https://YOUR_DOMAIN/health
# {"status":"ok"}
```

### 反向代理示例（Nginx）

```nginx
server {
    listen 443 ssl http2;
    server_name YOUR_DOMAIN;
    # ssl_certificate ...;
    # ssl_certificate_key ...;

    location / {
        proxy_pass http://127.0.0.1:18000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`PUBLIC_BASE_URL` 必须与用户浏览器访问的对外 URL 一致（含 `https://`）。

---

## 方式 B：裸机 / systemd

```bash
cd /opt/feishu-outlook-sync-server
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env；DATABASE_URL 可用默认 sqlite:///.../data/sync.db
mkdir -p data
```

systemd 单元示例 `/etc/systemd/system/feishu-outlook-sync.service`：

```ini
[Unit]
Description=Feishu Outlook Sync
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/feishu-outlook-sync-server
EnvironmentFile=/opt/feishu-outlook-sync-server/.env
ExecStart=/opt/feishu-outlook-sync-server/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now feishu-outlook-sync
```

---


## 数据卷说明与每日备份

`docker-compose.yml` 里的 `sync-data:/data` 是 **Docker 命名卷**，不会在项目目录下出现名为 `sync-data` 的文件夹。数据实际在 Docker 管理的卷里，例如：

```bash
docker volume ls | grep sync
docker volume inspect feishu-outlook-sync-server_sync-data
# Mountpoint 类似 /var/lib/docker/volumes/.../_data
```

容器内路径：

| 路径 | 内容 |
|------|------|
| `/data/sync.db` | 主库（用户、加密 token、同步映射） |
| `/data/backups/sync-YYYYMMDD.db` | **每日自动备份**（默认每天 03:15，保留 14 天） |

应用内已用 APScheduler 做每日备份（`BACKUP_*` 环境变量，见 `.env.example`）。改 `.env` 后 `docker compose up -d --build`。

手动备份到宿主机目录：

```bash
./scripts/backup-db.sh /root/backups/feishu-outlook
# 或
docker compose exec -T sync cat /data/sync.db > ~/sync-$(date +%F).db
```

若希望在项目目录直接看到文件，可把 compose 改成绑定挂载（二选一，勿混用旧卷数据前请先拷出）：

```yaml
    volumes:
      - ./data:/data
```

然后 `mkdir -p data && docker compose up -d`，库在 `./data/sync.db`，备份在 `./data/backups/`。


## 备份与密钥

- **定期备份** SQLite（Docker：`docker compose exec sync cat /data/sync.db > backup.db` 或备份 volume）
- **TOKEN_ENCRYPTION_KEY** 丢失则无法解密已存 token，所有用户需重新授权
- **切勿**将 `.env`、数据库提交到公开仓库
- 日志中不会打印原始 access/refresh token

---

## 升级

```bash
docker compose pull   # 若使用镜像仓库
# 或重新 build
docker compose up -d --build
```

升级前备份数据库；schema 由 SQLAlchemy `create_all` 创建，并在启动时用 SQLite `PRAGMA table_info` 做轻量 `ALTER TABLE` （如 `users.sync_direction`、`event_mappings.direction`）。大版本变更请先看 [CHANGELOG.md](../CHANGELOG.md) 与 README。

若升级后要启用近实时推送：对照 `.env.example` 补齐 `FEISHU_EVENT_*` / `GRAPH_WEBHOOK_CLIENT_STATE`（及可选 `PUSH_*`），并将 `SYNC_INTERVAL_MINUTES` 设为 3–5；飞书控制台步骤见 [ADMIN-SETUP.md](ADMIN-SETUP.md)「三、近实时推送同步」。

---

## 故障排查

| 现象 | 可能原因 |
|------|----------|
| OAuth 回调 404 / mismatch | `PUBLIC_BASE_URL` 或开放平台重定向 URI 不一致 |
| Cookie 丢失 | `COOKIE_SECURE=true` 但站点非 HTTPS；或域名不一致 |
| 飞书 99991679 / 无权限 | 权限未申请或未发布；用户未同意 scope |
| Microsoft AADSTS 错误 | 应用账户类型与 `MS_AUTHORITY` 不匹配；密钥错误 |
| 解密失败 | `TOKEN_ENCRYPTION_KEY` 已更换 |
