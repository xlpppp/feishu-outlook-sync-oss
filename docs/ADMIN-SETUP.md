# 管理员：注册 Microsoft 与飞书应用

本文说明如何为「飞书 ↔ Outlook 同步服务」创建应用凭据。**注册应用本身免费**；用户使用免费/个人 Outlook.com 即可，**无需**为应用注册购买 Azure 虚拟机。

---

## 一、Microsoft（个人 Outlook.com）

目标：让用户用个人 Microsoft 账户授权，服务代其读写日历（读取默认日历；写入专用「Feishu Sync」日历）。

### 1. 创建应用注册

1. 打开 [Azure 门户](https://portal.azure.com) 或 [Microsoft Entra 管理中心](https://entra.microsoft.com)
2. **应用注册** → **新注册**
3. 名称：例如 `Feishu Outlook Sync`
4. **受支持的账户类型**（重要）：
   - 选 **「仅个人 Microsoft 帐户」**，或
   - **「任何组织目录中的帐户和个人 Microsoft 帐户」**（若希望同时支持公司 + 个人）
5. **重定向 URI**：平台选 **Web**，填入：
   ```
   https://YOUR_DOMAIN/oauth/microsoft/callback
   ```
   本地调试可再加：`http://127.0.0.1:8000/oauth/microsoft/callback`
6. 注册完成后记录 **应用程序（客户端）ID** → 写入 `.env` 的 `MS_CLIENT_ID`

### 2. 客户端密码

1. **证书和密码** → **新客户端密码** → 创建并**立刻复制**密钥值  
2. 写入 `MS_CLIENT_SECRET`  
3. 注意过期时间，到期前轮换

### 3. API 权限（委托）

1. **API 权限** → **添加权限** → **Microsoft Graph** → **委托的权限**
2. 勾选：
   - `Calendars.ReadWrite`（读默认日历 + 写 Feishu Sync，已足够）
   - `offline_access`
   - `User.Read`
3. 个人账户场景一般**不需要**「管理员同意」；用户首次登录时自行同意即可。

### 4. Authority（租户）

在 `.env` 中：

- 仅个人账户：`MS_AUTHORITY=https://login.microsoftonline.com/consumers`（推荐）
- 组织 + 个人：`MS_AUTHORITY=https://login.microsoftonline.com/common`（应用注册须支持个人账户）

### 5. 费用说明

- 应用注册与 Graph 委托权限对个人 Outlook 使用**无额外租户许可费要求**（按微软现行政策；以官方为准）
- 本服务跑在你自己的服务器/容器上，与「是否购买 Azure VM」无关

---

## 二、飞书开放平台

### 1. 创建应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app) → 创建企业自建应用（或按组织规范）
2. 记录 **App ID**、**App Secret** → `FEISHU_APP_ID` / `FEISHU_APP_SECRET`

### 2. 安全设置 / 重定向 URL

1. **安全设置** → 配置重定向 URL：
   ```
   https://YOUR_DOMAIN/oauth/feishu/callback
   ```
2. 开启 **刷新 user_access_token**（若有开关），以便 `offline_access` 生效
3. 如需本地调试，同样添加 `http://127.0.0.1:8000/oauth/feishu/callback`

### 3. 权限（Scopes）— 含写

在 **权限管理** 中申请（用户身份 / 以用户身份调用）：

| Scope key | 用途 | 控制台常见名称 |
|-----------|------|----------------|
| `calendar:calendar:readonly` | 读取日历列表与日程 | 获取日历、日程及忙闲信息 |
| `calendar:calendar` | **写**：创建日历、创建/更新/删除日程 | 获取与更新日历日程信息 |
| `offline_access` | 返回 refresh_token | （安全设置中开启刷新） |

可选细粒度（一般 `calendar:calendar` 已覆盖）：

- `calendar:calendar:create` — 创建日历
- `calendar:calendar.event:create` / `:update` / `:delete` — 日程写操作

授权链接中的 scope 由环境变量 `FEISHU_SCOPES` 控制，默认：

```
calendar:calendar calendar:calendar.event:create calendar:calendar.event:update calendar:calendar.event:delete offline_access
```

> 说明：飞书文档中「更新日历和日程信息」对应的 scope key 是 **`calendar:calendar`**（不是 `calendar:calendar:write`）。若控制台另有 `calendar:calendar:write` 字样，以控制台实际 key 为准，并写入 `FEISHU_SCOPES`。

### 4. 发布版本与用户重新授权

企业自建应用通常需要：**创建版本 → 申请权限 → 管理员审批/发布** 后，终端用户才能完成授权。

**升级写权限后**：此前仅用 readonly 连接的用户，仪表盘在选择 Outlook→飞书 / 双向时会提示重新连接飞书。请通知用户：**断开飞书 → 再连接飞书**，以同意新的写 scope。

### 5. 用户信息

服务在回调后调用 `GET /open-apis/authen/v1/user_info` 获取 `open_id` / 名称。若调用失败，请确认应用已具备获取用户基本信息相关能力，并已发布。

---

## 三、近实时推送同步（推荐）

在保留 APScheduler 定时同步作为兜底的前提下，可启用：

- **飞书**：开放平台事件 `calendar.calendar.event.changed_v4` → `POST /webhooks/feishu` → 防抖后调用该用户的 `sync_user`
- **Microsoft Graph**：日历事件 change notifications → `POST /webhooks/microsoft` → 同上

生产示例：将 `PUBLIC_BASE_URL` 设为你的 HTTPS 根地址（如 `https://sync.example.com`）。

### 1. 飞书事件订阅

1. 开放平台 → 应用 → **开发配置 → 事件与回调**
2. **加密策略**：配置 Encrypt Key、Verification Token，分别写入 `.env`：
   - `FEISHU_EVENT_ENCRYPT_KEY`
   - `FEISHU_EVENT_VERIFICATION_TOKEN`
3. **订阅方式**：选择「将事件发送至开发者服务器」，请求地址：
   ```
   https://YOUR_DOMAIN/webhooks/feishu
   ```
   保存时飞书会发 `url_verification`；服务端会回显 `challenge`（支持加密 challenge）。
4. **添加事件**：订阅 **日程变更** `calendar.calendar.event.changed_v4`
5. 说明：该事件还需以 **user_access_token** 对具体日历调用「订阅日程变更」API。服务在用户连接飞书且同步开启时自动调用；**只订阅主日历/自有源**，跳过 `role=reader` / `free_busy_reader`，并跳过目标日历 `FEISHU_SYNC_CALENDAR_NAME`（默认 `Outlook Sync`）以防回环。

官方文档：[订阅日程变更](https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event/subscription)、[日程变更事件](https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event/events/changed)。

### 2. Microsoft Graph 变更通知

1. 生成随机 `clientState`（勿提交到 git）：
   ```bash
   openssl rand -hex 24
   ```
   写入 `GRAPH_WEBHOOK_CLIENT_STATE`
2. 服务在用户连接 Outlook、且同步方向包含 Outlook→飞书（或双向）时，创建订阅：
   - `resource`: `/me/events`（Graph Outlook events 支持的路径；通知可能含各日历，合并引擎仍只从默认日历作源，目标「Feishu Sync」不会回写）
   - `notificationUrl` / `lifecycleNotificationUrl`: `https://YOUR_DOMAIN/webhooks/microsoft`
   - 最长约 **7 天**；后台每 6 小时检查，在到期前按 `GRAPH_SUBSCRIPTION_RENEW_HOURS` 续期
3. 创建订阅时 Graph 会对 URL 做 `validationToken` 握手；端点以 **纯文本** 回显，无需登录 Cookie
4. 生命周期事件 `missed` / `reauthorizationRequired` / `subscriptionRemoved` 由同一端点处理并尽量重建订阅

官方文档：[Outlook change notifications](https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview)、[lifecycle](https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events)。

### 3. 推荐 `.env` 片段

```bash
PUSH_SYNC_ENABLED=true
FEISHU_EVENT_ENCRYPT_KEY=...
FEISHU_EVENT_VERIFICATION_TOKEN=...
GRAPH_WEBHOOK_CLIENT_STATE=...
PUSH_DEBOUNCE_SECONDS=20
# 开启 push 后建议 3–5 分钟作兜底；不要设为 1
SYNC_INTERVAL_MINUTES=3
```

未设置 `PUSH_SYNC_ENABLED` 时：只要任一飞书事件密钥或 `GRAPH_WEBHOOK_CLIENT_STATE` 非空，推送自动开启。

---

## 四、把凭据写入服务

```bash
cp .env.example .env
# 填写：
# PUBLIC_BASE_URL=https://YOUR_DOMAIN
# SECRET_KEY=...
# TOKEN_ENCRYPTION_KEY=...   # Fernet
# MS_CLIENT_ID / MS_CLIENT_SECRET / MS_AUTHORITY
# FEISHU_APP_ID / FEISHU_APP_SECRET
# FEISHU_SCOPES=calendar:calendar calendar:calendar.event:create calendar:calendar.event:update calendar:calendar.event:delete offline_access
# OUTLOOK_CALENDAR_NAME=Feishu Sync
# FEISHU_SYNC_CALENDAR_NAME=Outlook Sync
# （推荐）FEISHU_EVENT_* / GRAPH_WEBHOOK_CLIENT_STATE / SYNC_INTERVAL_MINUTES=3
```

密钥与全部变量含义见 [ENV.md](ENV.md)。然后按 [DEPLOY.md](DEPLOY.md) 启动服务，再按 [USER-GUIDE.md](USER-GUIDE.md) 让用户自行连接。
