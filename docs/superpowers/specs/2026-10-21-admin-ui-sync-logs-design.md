# Admin UI polish + sync run logs

**Date:** 2026-10-21  
**Status:** Approved (layout / actions / logs sections)  
**Repo:** feishu-outlook-sync-oss

## Goal

Beautify `/admin`, widen the global page shell to 1200px with no horizontal scrollbar, replace long text action buttons with SVG icon buttons, and let admins expand a user row to inspect the last 7 days of sync runs for troubleshooting.

## Non-goals

- Pagination/search on the user list
- Delete-user or remote calendar cleanup
- Showing sync history on the end-user dashboard (admin only this iteration)
- Changing unbind semantics (tokens only)

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Path | A: polish existing admin + new `sync_runs` table |
| Log data | New sync run log (not mappings-only / last_sync-only) |
| Window | Display and retain **7 days** |
| Viewer | **Inline** expand under the user row |
| Page width | Global `.wrap` → `min(1200px, calc(100% - 2rem))` |

## Layout and table

- Update shared CSS `.wrap` to `width: min(1200px, calc(100% - 2rem))` so home and admin match.
- Admin table: `table-layout: fixed`, allocated column widths, long cells with `text-overflow: ellipsis` + `overflow: hidden` + `white-space: nowrap` where appropriate; full value in `title`.
- Table container: no horizontal scroll (`overflow-x: hidden`); never introduce page-level horizontal scrollbar.
- Header cells: `white-space: nowrap`.
- Visual: reuse existing card / theme tokens; row hover; status badges; move inline styles into CSS classes.

## Action buttons

- Replace long Chinese label buttons with compact icon buttons (same family as existing `.icon-btn`).
- Actions per row:
  1. Toggle auto-sync (play/pause or power icon; reflects current `sync_enabled`)
  2. Unbind login (unlink/key icon; danger styling)
  3. Expand/collapse sync logs (history/clock icon; active when expanded)
- Each control: `title` + `aria-label` in Chinese; keep full-text `confirm()` copy.
- Actions column: narrow, icons in one horizontal non-wrapping group.

## Sync run logs (`sync_runs`)

### Schema (additive)

| Column | Notes |
|--------|--------|
| `id` | PK |
| `user_id` | FK → `users.id` |
| `started_at` | timezone-aware |
| `finished_at` | nullable until complete |
| `trigger` | `poll` \| `push` \| `manual` \| `admin` (extend if needed) |
| `status` | `ok` \| `error` \| `partial` |
| `message` | short human summary / error |
| `created_count` / `updated_count` / `deleted_count` | optional ints, default 0 |
| Indexes | `(user_id, started_at DESC)` |

### Write path

- On each user sync completion (poll, push-driven, manual, admin-triggered), insert one `sync_runs` row and keep updating `users.last_sync_*` as today.
- Retention: delete rows with `started_at` older than 7 days (startup and/or periodic job; cheap SQLite delete is fine).

### Admin UI

- Icon toggles an expanded `<tr>` (or equivalent) under the user with a nested table of that user's runs in the last 7 days: time, trigger, status, summary/counts.
- Empty state when none.
- Endpoint options (implementer pick matching existing style): either embed runs in `GET /admin` payload for visible expands, or `GET /admin/users/{id}/sync-runs` fetched on expand; prefer server-rendered inline fragment or small JSON for expand-on-demand to avoid huge HTML.

## Auth / safety

- Unchanged: empty `ADMIN_FEISHU_OPEN_IDS` → 404; non-allowlist → 403; unbind tokens only.

## Docs / deploy

- Document `sync_runs` and 7-day retention in CHANGELOG / README briefly.
- No new env vars required for this feature.

## Testing

- Config/layout smoke: wrap width class present; admin table CSS has nowrap headers / no overflow-x auto.
- Sync run insert + 7-day filter query tests.
- Admin expand empty vs non-empty (unit or route-level as existing `tests/test_admin.py` style).
