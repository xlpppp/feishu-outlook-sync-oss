# `.env` 填写说明（含双向同步）

复制示例后编辑：

```bash
cp .env.example .env
```

下面按「必填 → 应用凭据 → 双向日历名 → 可选」说明：**填什么、怎么生成/获取**。

---

## 一句话先答两个密钥

| 变量 | 是不是你自己定的？ | 填什么 |
|------|-------------------|--------|
| `SECRET_KEY` | **是**，你自定义的随机串 | 任意足够长的随机字符串（建议 ≥32 字符），用于签 Cookie 会话。丢了只会导致用户重新登录本站，**不会**毁掉已加密的 token。 |
| `TOKEN_ENCRYPTION_KEY` | **不是**随便编的普通字符串 | 必须是 **Fernet** 格式密钥（`cryptography` 库生成）。用来加密数据库里的飞书/微软 access、refresh token。**丢了或改了，所有用户都要重新授权。** |

生成命令（在装过 Python 的机器上执行一次，把打印结果整行贴进 `.env`）：

```bash
# SECRET_KEY（自定义随机串，两种任选）
openssl rand -hex 32
# 或
python -c "import secrets; print(secrets.token_urlsafe(48))"

# TOKEN_ENCRYPTION_KEY（必须用 Fernet）
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

若本机没有 `cryptography`：

```bash
pip install cryptography
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Fernet 密钥长得像：`xYz...=`（url-safe base64），**不要**自己手搓一串普通密码代替。

---

## 必填项

### 1. `PUBLIC_BASE_URL`

- **含义**：用户浏览器访问本服务的根地址，**无尾斜杠**。
- **示例**：`https://sync.yourcompany.com`
- **本地调试**：`http://127.0.0.1:8000`
- **注意**：必须与微软/飞书后台配置的 OAuth 回调域名一致；前面有 Nginx HTTPS 时这里写 `https://...`，并给 Nginx 加 `X-Forwarded-Proto`。

### 2. `SECRET_KEY`

- 见上文。生产环境务必换掉示例里的 `change-me-...`。

### 3. `TOKEN_ENCRYPTION_KEY`

- 见上文。生成一次后**长期保管**（密码管理器 / 密钥库）；换钥 = 全员重授权。

### 4. `MS_CLIENT_ID` / `MS_CLIENT_SECRET`

- **从哪来**：Azure / Entra「应用注册」→ 应用（客户端）ID、客户端密码。  
- **步骤见**：[ADMIN-SETUP.md](ADMIN-SETUP.md) 第一节。  
- 个人 Outlook.com：账户类型选「仅个人 Microsoft 帐户」或「组织+个人」。  
- 重定向 URI（Web）：`{PUBLIC_BASE_URL}/oauth/microsoft/callback`

### 5. `MS_AUTHORITY`

- 仅个人账户（推荐）：`https://login.microsoftonline.com/consumers`  
- 组织+个人：`https://login.microsoftonline.com/common`（应用注册须支持个人账户）

### 6. `MS_SCOPES`

- 默认即可：`Calendars.ReadWrite User.Read`  
- 双向同步同样够用（读 Outlook 默认日历 + 写「Feishu Sync」）。

### 7. `FEISHU_APP_ID` / `FEISHU_APP_SECRET`

- **从哪来**：[飞书开放平台](https://open.feishu.cn/app) → 自建应用 → 凭证与基础信息。  
- **步骤见**：[ADMIN-SETUP.md](ADMIN-SETUP.md) 第二节。  
- 重定向 URL：`{PUBLIC_BASE_URL}/oauth/feishu/callback`  
- 开启「刷新 user_access_token」（若有开关）。

### 8. `FEISHU_SCOPES`（双向必含写权限）

默认（推荐，**不要删掉** `calendar:calendar`）：

```
calendar:calendar calendar:calendar.event:create calendar:calendar.event:update calendar:calendar.event:delete offline_access
```

| Scope | 作用 |
|-------|------|
| `calendar:calendar` | 读/写日历（建「Outlook Sync」等） |
| `calendar:calendar.event:create` / `:update` / `:delete` | 日程增删改（双向写飞书） |
| `offline_access` | 刷新令牌（安全设置里开启「刷新 user_access_token」） |

> 若控制台显示的是 `calendar:calendar:read` 而不是 `:readonly`，OAuth 里也要用 `:read`，写 `:readonly` 会 20043。

控制台权限名以「权限管理」页显示的 **scope key** 为准（可能是 `calendar:calendar` / `calendar:calendar:read` / `calendar:calendar.event:*`）。申请后需**发布版本**。授权链接里的 `FEISHU_SCOPES` 必须与已开通 key **完全一致**，否则飞书报 **20043**；未开通却请求会报 **20027**。以前只授过只读的用户，选双向前要**断开再连飞书**。

---

## 双向同步相关（建议保持默认名）

| 变量 | 默认 | 说明 |
|------|------|------|
| `OUTLOOK_CALENDAR_NAME` | `Feishu Sync` | **飞书→Outlook** 写入的 Outlook 日历名；服务会自动创建。不要把这个日历当 Outlook→飞书 的源。 |
| `FEISHU_SYNC_CALENDAR_NAME` | `Outlook Sync` | **Outlook→飞书** 写入的飞书日历名；缺失会自动创建。不要把这个日历当飞书→Outlook 的源。 |

用户在网页上自选方向：`飞书→Outlook` / `Outlook→飞书` / **双向**。服务端防回环：目标日历永不作源。

---

## 可选（一般用默认）

| 变量 | 默认 | 说明 |
|------|------|------|
| `SKIP_SUBSCRIBED_CALENDARS` | `true` | 飞书→Outlook 时跳过订阅日历（`role=reader` / `free_busy_reader`，即飞书里「订阅」的他人日历）。`false` 可关闭此过滤。 |
| `SYNC_INTERVAL_MINUTES` | `15` | 定时同步兜底间隔（分钟）。开启 push 后建议 **3–5**，不要强制设为 1。 |
| `SYNC_WINDOW_PAST_DAYS` | `7` | 同步过去几天 |
| `SYNC_WINDOW_FUTURE_DAYS` | `60` | 同步未来几天 |
| `TIMEZONE` | `Asia/Shanghai` | 无时区信息时的回退时区 |
| `DATABASE_URL` | Docker 内 `sqlite:////data/sync.db` | 数据库；Compose 已挂 volume，通常不用改 |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | 容器内监听；Docker 部署保持 `PORT=8000` |
| `HOST_PORT` | `18000` | **宿主机**映射端口（`docker-compose` 用）；8000 被占用就改这个，Nginx 反代到 `127.0.0.1:$HOST_PORT` |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `COOKIE_SECURE` | 生产 `true` | 仅 HTTPS 带 Cookie；本地可 `false` |

---

## 近实时推送（可选，推荐生产开启）

定时轮询仍会跑；push 只是在日历变更时提前触发同一套 `sync_user`。

| 变量 | 默认 | 说明 |
|------|------|------|
| `PUSH_SYNC_ENABLED` | 未设置时自动 | 显式 `true`/`false`。未设置时：任一飞书事件密钥或 `GRAPH_WEBHOOK_CLIENT_STATE` 非空即开启。 |
| `FEISHU_EVENT_ENCRYPT_KEY` | 空 | 飞书「事件与回调 → 加密策略」Encrypt Key；用于解密与签名校验。 |
| `FEISHU_EVENT_VERIFICATION_TOKEN` | 空 | 同上页面 Verification Token；challenge / 事件校验。 |
| `GRAPH_WEBHOOK_CLIENT_STATE` | 空 | 自建随机串（≤128），写入 Graph 订阅 `clientState` 并在回调比对。`openssl rand -hex 24` |
| `PUSH_DEBOUNCE_SECONDS` | `20` | 同一用户多次推送合并窗口（秒），建议 15–30。 |
| `GRAPH_SUBSCRIPTION_RENEW_HOURS` | `24` | Graph 订阅到期前多少小时续期（Outlook events 最长约 7 天）。 |

Webhook URL（须公网 HTTPS，与 `PUBLIC_BASE_URL` 一致）：

- 飞书：`{PUBLIC_BASE_URL}/webhooks/feishu`
- Graph：`{PUBLIC_BASE_URL}/webhooks/microsoft`

控制台步骤见 [ADMIN-SETUP.md](ADMIN-SETUP.md)「推送同步」一节。

---

## 管理后台（可选）

| 变量 | 默认 | 说明 |
|------|------|------|
| `ADMIN_FEISHU_OPEN_IDS` | 空 | 逗号（或分号）分隔的飞书 `open_id`。命中名单的已登录用户可访问 `GET /admin`，代为开关自动同步或解除登录绑定（仅清 Token）。**为空时** `/admin` 及管理 POST 返回 **404**（不暴露后台存在）。非名单用户 → **403**。 |

部署后在 `.env` 写入管理员的飞书 `open_id` 并重建容器。`open_id` 可从已绑定用户的 `users.feishu_open_id` 或飞书开放平台获取。管理页可展开查看近 7 天 `sync_runs` 同步历史（无额外环境变量；超期记录自动清理）。

---

## 填完后的最小检查清单

1. `.env` 里 `PUBLIC_BASE_URL`、两个密钥、微软/飞书四件套都已非空
2. 微软回调 = `{PUBLIC_BASE_URL}/oauth/microsoft/callback`
3. 飞书回调 = `{PUBLIC_BASE_URL}/oauth/feishu/callback`
4. 飞书已申请并发布含 `calendar:calendar` 的版本
5. （推荐）配置推送密钥 + 飞书事件地址 `/webhooks/feishu` + 订阅 `calendar.calendar.event.changed_v4`；`SYNC_INTERVAL_MINUTES=3`～`5`
6. `docker compose up -d --build`，`curl https://你的域名/health` 返回 `{"status":"ok"}`
7. 浏览器打开站点 → 分别连接 Outlook、飞书 → 选「双向」→「立即同步」

完整启动步骤见 [DEPLOY.md](DEPLOY.md)。
