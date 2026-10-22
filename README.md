# Feishu ↔ Outlook Calendar Sync

Multi-user calendar sync between **Feishu (Lark)** and personal **Outlook.com**, using Microsoft Graph and Feishu Open API. Each user authorizes independently, chooses sync direction, and the service writes into dedicated target calendars to prevent sync loops. Optional near-realtime webhooks, Docker deployment, and an optional admin console are included.

**License:** [MIT](LICENSE) · **Repo:** [xlpppp/feishu-outlook-sync-oss](https://github.com/xlpppp/feishu-outlook-sync-oss)

---

## 中文

多用户 **飞书 ↔ Outlook.com** 日历同步服务（Microsoft Graph + 飞书 Open API）。每人独立 OAuth，可选同步方向，通过专用目标日历防回环；可选近实时 Webhook、Docker 部署与管理后台。

### 功能

- 每人独立授权：飞书 OAuth + Microsoft 个人账户 OAuth
- **同步方向可选**（按用户持久化）：飞书→Outlook / Outlook→飞书 / 双向
- **防回环**：各腿写入专用目标日历，绝不把目标日历当作源再拉取
- **近实时推送**（可选）：飞书日程变更事件 + Graph change notifications → 防抖后复用 `sync_user`；APScheduler 间隔同步作兜底
- 自建部署（Docker / 裸机），SQLite + APScheduler
- **管理后台**（可选）：允许名单内的飞书用户访问 `/admin`
- 不依赖 lark-cli；使用飞书开放平台 Open API

### 同步方向与防回环

| 方向 | 源 | 目标 |
|------|----|------|
| `feishu_to_outlook`（默认） | 飞书主日历（默认跳过「订阅」日历） | Outlook 日历 `OUTLOOK_CALENDAR_NAME`（默认 `Feishu Sync`） |
| `outlook_to_feishu` | Outlook 默认日历 | 飞书专用日历 `FEISHU_SYNC_CALENDAR_NAME`（默认 `Outlook Sync`） |
| `bidirectional` | 依次跑上述两腿 | — |

冲突策略：各方向使用独立目标日历，目标侧编辑不会回写。不做两端主日历同一事件的合并。

### 快速开始（Docker）

```bash
git clone https://github.com/xlpppp/feishu-outlook-sync-oss.git
cd feishu-outlook-sync-oss
cp .env.example .env
# 编辑 .env：PUBLIC_BASE_URL、SECRET_KEY、TOKEN_ENCRYPTION_KEY、MS_*、FEISHU_* 等
# 详见 docs/ENV.md、docs/ADMIN-SETUP.md

docker compose up -d --build
# 浏览器打开 PUBLIC_BASE_URL
```

Compose 服务名是 **`sync`**（不是 `app`）。

### 本地开发

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # COOKIE_SECURE=false；PUBLIC_BASE_URL=http://127.0.0.1:8000
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 测试

```bash
python3 -m unittest discover -s tests -v
python3 scripts/smoke_check.py
```

### 部署注意

```bash
git pull
docker compose down && docker compose up -d --build
# 切勿 docker compose down -v（会删 volume / 丢库）
```

### 文档索引

| 文档 | 内容 |
|------|------|
| [change.md](change.md) | 更新日志 |
| [AGENTS.md](AGENTS.md) | 贡献者 / Agent 说明 |
| [docs/ADMIN-SETUP.md](docs/ADMIN-SETUP.md) | 注册微软/飞书应用与近实时推送 |
| [docs/ENV.md](docs/ENV.md) | 环境变量逐项说明 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Docker / 裸机 / 反向代理 |
| [docs/USER-GUIDE.md](docs/USER-GUIDE.md) | 终端用户指南 |

### 环境变量概览

常用变量（完整列表见 [docs/ENV.md](docs/ENV.md)）：

| 变量 | 说明 |
|------|------|
| `PUBLIC_BASE_URL` | 对外 HTTPS 根 URL（无尾斜杠） |
| `SECRET_KEY` | Cookie 会话签名密钥 |
| `TOKEN_ENCRYPTION_KEY` | Fernet 密钥，加密库内 OAuth token |
| `MS_CLIENT_ID` / `MS_CLIENT_SECRET` | Azure 应用凭据 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书应用凭据 |
| `OUTLOOK_CALENDAR_NAME` / `FEISHU_SYNC_CALENDAR_NAME` | 防回环专用目标日历名 |
| `SYNC_INTERVAL_MINUTES` | 定时同步兜底间隔 |
| `PUSH_SYNC_ENABLED` 及飞书/Graph webhook 密钥 | 可选近实时推送 |
| `ADMIN_FEISHU_OPEN_IDS` | 可选；管理员飞书 `open_id` 名单 |

### 已知限制

- 防回环专用日历：勿把 `Feishu Sync` / `Outlook Sync` 当作源再指望回写
- 双向时两端主日历事件不会互相同步合并
- 飞书重复日程按同步窗展开实例；复杂例外规则可能与 Outlook 不完全一致
- 飞书「订阅日历」默认不同步（可用 `SKIP_SUBSCRIBED_CALENDARS=false` 关闭）
- OAuth state 存进程内存；多副本需共享存储
- 飞书 `refresh_token` 约 365 天后需用户重新授权
- 面向个人 Microsoft 账户（`consumers` / `common` authority）

### License

[MIT](LICENSE) · Copyright (c) 2026 Ye Feng / xlpppp

---

## English (quick reference)

### Features

- Per-user Feishu + Microsoft OAuth
- Sync directions: Feishu→Outlook, Outlook→Feishu, or bidirectional
- Loop prevention via dedicated target calendars
- Optional near-realtime Feishu events + Graph webhooks (debounced); APScheduler as fallback
- Docker / bare-metal; SQLite; optional `/admin` allowlist

### Quick start

```bash
git clone https://github.com/xlpppp/feishu-outlook-sync-oss.git
cd feishu-outlook-sync-oss
cp .env.example .env   # fill secrets; see docs/ENV.md
docker compose up -d --build
```

Local: `pip install -r requirements.txt` then `uvicorn app.main:app --reload`.

### Docs

See the Chinese table above — same paths under `docs/`. High-level env vars are listed there; full reference in [docs/ENV.md](docs/ENV.md).

### Limitations

Dedicated target calendars only (no primary↔primary merge); subscribed Feishu calendars skipped by default; in-memory OAuth state; personal Microsoft accounts; see Chinese section for details.

### License

MIT — see [LICENSE](LICENSE).
