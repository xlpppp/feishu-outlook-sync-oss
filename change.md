# 更新日志 (Changelog)

本文件为项目权威更新日志（面向运维 / 用户的可见变更），格式大致遵循 [Keep a Changelog](https://keepachangelog.com/)。
`CHANGELOG.md` 仅为指向本文件的短说明，避免旧链接断链。

---

## [2026-10-21]

### Added

- **管理后台** `/admin`：环境变量 `ADMIN_FEISHU_OPEN_IDS`（飞书 `open_id` 允许名单，须与库表 `users.feishu_open_id` 一致）。名单用户可一览全部绑定账户、代为开关自动同步、解除登录绑定（仅清除 OAuth Token，保留用户与事件映射）。名单为空 → 404；非名单 → 403；未登录 → 飞书 OAuth 并安全回跳 `/admin`。
- **同步运行日志** `sync_runs`：每次同步**完成**写入一行（`trigger`=poll/push/manual；状态、摘要与增删改计数）；**dry_run 不落库**。管理后台用户行可展开查看近 **7 天**记录（`/admin?expand=<id>`）；启动与每日定时清理更旧数据。无需新环境变量。

### Changed

- 全局页面壳 `.wrap` 宽度改为 `min(1200px, calc(100% - 2rem))`；`/admin` 表格固定布局、表头不换行、长单元格省略号，操作改为带中文 `title`/`aria-label` 的 SVG 图标按钮。

### Fixed

- **飞书重复日程只同步一次**：`list_events` 改为 `GET .../events/instance_view`，在同步窗内展开每一次 occurrence（含非重复日程）；窗跨度按小于 40 天分片合并去重，遇 193103/193104 自动对半分片。映射键使用实例 `event_id`，每周三等系列在 Outlook 目标日历各生成独立事件。

### Notes

- 勿提交 `.env`、数据库或真实 Token。

---

## [2026-10-20]

### Added

- **近实时推送同步**（推荐生产开启）：
  - 飞书事件 `calendar.calendar.event.changed_v4` → `POST /webhooks/feishu`
  - Microsoft Graph 日历变更通知 → `POST /webhooks/microsoft`
  - 同一用户推送经防抖后复用现有 `sync_user`；APScheduler 定时轮询作兜底
- 相关环境变量：`PUSH_SYNC_ENABLED`、`FEISHU_EVENT_ENCRYPT_KEY`、`FEISHU_EVENT_VERIFICATION_TOKEN`、`GRAPH_WEBHOOK_CLIENT_STATE`、`PUSH_DEBOUNCE_SECONDS`、`GRAPH_SUBSCRIPTION_RENEW_HOURS`（见 [docs/ENV.md](docs/ENV.md)）
- 运维说明：[docs/ADMIN-SETUP.md](docs/ADMIN-SETUP.md)「三、近实时推送同步」；用户 OAuth 后服务自动订阅相关日历 / Graph 订阅并续期

### Changed

- 开启 push 后，建议将 `SYNC_INTERVAL_MINUTES` 设为 **3–5** 作兜底（代码默认仍为 `15`；勿强制改为 `1`）
- `SKIP_SUBSCRIBED_CALENDARS` 默认 `true`：飞书→Outlook 跳过订阅日历（`role=reader` / `free_busy_reader`）；设为 `false` 可关闭过滤

### Fixed

- **飞书拉日程静默截断**：`list_events` 不再用不可分页的 `start_time`+`end_time`（超过 `page_size` 会丢后续日程）。改为 `anchor_time` + `page_token` 翻页（`page_size=500`），再按同步窗客户端过滤相交事件。修复宽同步窗内日程数 >~100 时周五/数日后事件缺失的问题。
- **hash 命中但目标已删仍永久 skip**：f2o / o2f 每轮用目标日历窗内事件 ID 集合校验映射；若 `content_hash` 相同但目标 ID 不在集合中则 **重建** 并刷新映射（计为 create）。修复 Outlook 侧事件被删 / 映射陈旧时飞书主日历日程一直 `skip`、不同步到 Outlook 的问题。

---

## [Unreleased]

（暂无；新变更追加到带日期的章节。）
