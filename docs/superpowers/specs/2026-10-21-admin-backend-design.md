# 管理后台设计：用户绑定一览与关同步 / 解绑

**日期：** 2026-10-21  
**仓库：** xlpppp/feishu-outlook-sync-oss  

**状态：** 已实现（历史设计稿）

## 背景

自建飞书↔Outlook 同步服务已支持多用户 OAuth 绑定与 `users.sync_enabled`。当前仅有面向本人的仪表盘（`/`），管理员无法一览谁绑过、也无法代为关闭自动同步或解除登录绑定。

## 目标

1. 管理员可查看所有已注册用户的绑定与同步状态。
2. 管理员可在线关闭 / 开启某账户的自动同步。
3. 管理员可解除某账户的登录绑定（仅清除 OAuth Token）。
4. 仅允许名单内的飞书用户访问管理页。

## 非目标（首版不做）

- 删除用户整行、清空 `event_mappings`、删除 Outlook「Feishu」日历中的已同步事件。
- 代用户触发「立即同步」。
- 用户搜索 / 分页（用户量预期较小，先全表列表）。
- 独立 SPA 或单独 Admin API 产品面。

## 已确认决策

| 项 | 选择 |
|----|------|
| 入口形态 | 独立 `/admin` 页，复用现有 Jinja + `base.html` 风格（方案 A） |
| 鉴权 | 飞书 `open_id` 允许名单（环境变量） |
| 解绑语义 | **只清 Token**，保留 User 行与事件映射 |
| 关同步 | 写 `sync_enabled`，并按现有逻辑清理 / 重建推送订阅 |

## 访问与鉴权

- **环境变量：** `ADMIN_FEISHU_OPEN_IDS`（逗号分隔的飞书 `open_id`，如 `ou_xxx,ou_yyy`）。
- **名单为空：** `/admin` 及所有管理 POST 返回 **404**（不暴露存在管理后台）。
- **未登录：** 引导飞书 OAuth，登录成功后回跳 `/admin`。
- **已登录但不在名单：** **403**。
- **已登录且命中：** 可访问管理页；首页对名单用户显示「管理后台」链接。
- **依赖：** 会话中的用户须已绑定飞书（有 `feishu_open_id`）；仅微软登录、无飞书 open_id 的账号无法成为管理员。

## 页面与字段

路径：`GET /admin` → `templates/admin.html`。

表格按用户 `id` 倒序，列：

- `id`
- 显示名 / 飞书名
- `feishu_open_id`
- `ms_email`
- 飞书 Token 有无、微软 Token 有无
- `sync_enabled`
- `sync_direction`
- `last_sync_at`、`last_sync_status`（及简短 `last_sync_message` 摘要）
- 映射条数（`event_mappings` count）

## 操作

均需管理员鉴权；POST；浏览器二次确认（`confirm`）。

### 1. 开 / 关自动同步

- 路由示例：`POST /admin/users/{user_id}/sync`（`enabled=0|1`）
- 行为：更新 `User.sync_enabled`
  - 关：`push_subscriptions.cleanup_user_subscriptions`
  - 开：`push_subscriptions.ensure_user_subscriptions`
- 成功后重定向回 `/admin` 并 flash

### 2. 解除登录绑定

- 路由示例：`POST /admin/users/{user_id}/unbind`
- 行为：删除该用户全部 `tokens` 行（microsoft + feishu）；调用 `cleanup_user_subscriptions`
- **不**删除 `users`、`event_mappings`、远端日历事件
- 用户再次 OAuth 可重新绑定；映射仍在，后续同步按现有 skip/update/recreate 逻辑处理

### 审计日志

每次 toggle / unbind 记录：`admin_user_id`、目标 `user_id`、动作名。不记录 Token 明文。

## 实现要点

| 文件 | 变更 |
|------|------|
| `app/config.py` | 解析 `ADMIN_FEISHU_OPEN_IDS` → `list[str]` |
| `app/routes/admin.py` | 新建：列表页 + toggle + unbind + `require_admin` |
| `app/main.py` | `include_router` |
| `app/templates/admin.html` | 管理页 |
| `app/templates/index.html` / `base.html` | 名单内显示管理入口 |
| `.env.example`、`README.md`、`CHANGELOG.md`、必要时 `docs/ENV.md` | 文档 |
| `tests/test_admin.py`（或等价） | 鉴权与操作单测 |

## 验收标准

1. 名单用户登录后可打开 `/admin` 并看到全部用户行。
2. 非名单用户访问 `/admin` → 403；名单空 → 404。
3. 关同步后该用户不再被调度 / 推送触发同步（与现有 `sync_enabled` 行为一致）。
4. 解绑后该用户 Token 消失，User 与映射仍在；重新登录可再绑。
5. 单测覆盖：名单命中 / 未命中、空名单 404、toggle、unbind 只清 token。

## 部署注意

服务器 `.env` 增加 `ADMIN_FEISHU_OPEN_IDS=<管理员的飞书 open_id>` 后重建容器。open_id 可从现有用户表或飞书开放平台获取。
