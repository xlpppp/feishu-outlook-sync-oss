# Admin UI Polish + Sync Run Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the global page shell to 1200px, polish `/admin` (no horizontal scroll, nowrap headers, SVG icon actions, inline 7-day sync history), and persist each sync completion into a new `sync_runs` table.

**Architecture:** Extend SQLAlchemy models with `SyncRun`; write rows from `sync_service._record` / `sync_user` with an explicit `trigger`. Admin Jinja reuses existing card/theme tokens; expand state is query-param or details/summary per row. Retention deletes rows older than 7 days on startup (and optionally from scheduler).

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2, existing `style.css` tokens, unittest.

**Spec:** `docs/superpowers/specs/2026-10-21-admin-ui-sync-logs-design.md`

## Global Constraints

- Never commit `.env`, secrets, `*.db`, or `/data`.
- Unbind semantics unchanged (tokens only).
- Empty `ADMIN_FEISHU_OPEN_IDS` → `/admin` still 404; non-allowlist → 403.
- Global `.wrap` width `min(1200px, calc(100% - 2rem))`; no page horizontal scrollbar.
- Sync history window: **7 days** (display + retention).
- Chinese UI; icon buttons need `title` + `aria-label`.
- Open one PR against GitHub `main` after implementation.
- No pagination/search, delete-user, or dashboard history in this plan.

## File map

| File | Role |
|------|------|
| `app/models.py` | Add `SyncRun` model + constants for trigger/status |
| `app/sync_runs.py` | **Create:** `record_sync_run`, `list_recent_runs`, `purge_old_runs` |
| `app/sync_service.py` | Pass `trigger` into `_record`; call `record_sync_run`; fill counts from `SyncResult` |
| `app/scheduler.py` / `app/main.py` / push paths | Pass `trigger="poll"` / `"push"` / `"manual"` at call sites |
| `app/routes/api.py` / `web.py` | Manual sync → `trigger="manual"` |
| `app/routes/admin.py` | Load recent runs for expand; optional `GET` fragment |
| `app/templates/admin.html` | Icon actions + inline expand table |
| `app/static/style.css` | `.wrap` 1200px; admin table / icon-btn / expand styles |
| `app/db.py` | Ensure `create_all` picks up new table (already via models import) |
| `tests/test_sync_runs.py` | **Create:** insert, list 7-day filter, purge |
| `tests/test_admin.py` | Extend: expand empty/non-empty HTML or route |
| `CHANGELOG.md`, `README.md` | Brief feature note |

---

### Task 1: `SyncRun` model + repository helpers (TDD)

**Files:**
- Modify: `app/models.py`
- Create: `app/sync_runs.py`
- Create: `tests/test_sync_runs.py`
- Test: `tests/test_sync_runs.py`

**Interfaces:**
- Produces:
  - `SyncRun` columns: `id`, `user_id`, `started_at`, `finished_at`, `trigger`, `status`, `message`, `created_count`, `updated_count`, `deleted_count`
  - `record_sync_run(db, user_id, *, trigger, status, message, created=0, updated=0, deleted=0, started_at=None, finished_at=None) -> SyncRun`
  - `list_recent_runs(db, user_id, *, days=7, limit=100) -> list[SyncRun]`
  - `purge_old_runs(db, *, days=7) -> int` (rows deleted)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync_runs.py (sketch)
class SyncRunsTests(unittest.TestCase):
    def test_record_and_list_within_window(self): ...
    def test_list_excludes_older_than_7_days(self): ...
    def test_purge_old_runs(self): ...
```

Use the same in-memory / temp SQLite patterns as `tests/test_admin.py` / existing sync tests (`init_db`, `session_scope`).

- [ ] **Step 2: Run tests — expect fail**

```bash
python3 -m unittest tests.test_sync_runs -v
```

- [ ] **Step 3: Implement model + `app/sync_runs.py`**

- `trigger`: `poll` | `push` | `manual` | `admin` (string column, validate at write helpers)
- `status`: `ok` | `error` | `partial` (map from existing `_record` status strings; if today only `ok`/`error`, keep compatible and treat non-ok with errors>0 as `error`, errors==0 but issues as `partial` if needed)
- Index: `(user_id, started_at)`

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git add app/models.py app/sync_runs.py tests/test_sync_runs.py
git commit -m "feat: add SyncRun model and 7-day run helpers"
```

---

### Task 2: Write runs from sync completion

**Files:**
- Modify: `app/sync_service.py` (`sync_user`, `_record`, `sync_all_enabled`)
- Modify: call sites that invoke `sync_user` / `sync_all_enabled` (search repo): `app/scheduler.py`, `app/push_debounce.py` or webhook handlers, `app/routes/api.py`, `app/routes/web.py`
- Test: extend `tests/test_sync_runs.py` or add a thin unit test that mocks `_record` path

**Interfaces:**
- Consumes: `record_sync_run`
- Produces: `sync_user(..., trigger: str = "manual")`; `_record(..., trigger, result: SyncResult | None = None)`

- [ ] **Step 1: Extend `_record` to also insert `SyncRun`**

When recording:
- `started_at` / `finished_at`: use now (or thread start time if you capture `t0` at `sync_user` entry — preferred)
- Counts from `SyncResult` when available
- `message`: prefer `result.summary()` + optional `result.message`, truncated like `last_sync_message`
- Skip inserting a run on `dry_run=True`

- [ ] **Step 2: Thread `trigger` through call sites**

| Caller | `trigger` |
|--------|-----------|
| Scheduler `sync_all_enabled` | `poll` |
| Push debounce / webhook-driven sync | `push` |
| User dashboard / API manual sync | `manual` |
| Admin-triggered sync (if any) | `admin` |

Default `trigger="manual"` if unsure; document in code.

- [ ] **Step 3: Call `purge_old_runs` on app startup** (e.g. in `main` lifespan / `init_db` after create_all) and optionally once daily in scheduler.

- [ ] **Step 4: Tests pass; commit**

```bash
git commit -m "feat: persist sync_runs on each sync completion"
```

---

### Task 3: Admin UI — width, table, icons, inline logs

**Files:**
- Modify: `app/static/style.css`
- Modify: `app/templates/admin.html`
- Modify: `app/routes/admin.py`
- Modify: `tests/test_admin.py`

**Interfaces:**
- Consumes: `list_recent_runs`
- Produces: admin page with expandable rows; CSS classes `.admin-table`, `.admin-actions`, `.admin-expand`, `.icon-btn` variants

- [ ] **Step 1: CSS**

- `.wrap { width: min(1200px, calc(100% - 2rem)); }`
- `body` / main: ensure no `overflow-x: auto` on admin; use `overflow-x: hidden` on table wrapper
- `th { white-space: nowrap; }`
- `table-layout: fixed` + ellipsis cells
- Icon button styles for admin actions (reuse `.icon-btn` patterns)

- [ ] **Step 2: Template**

- Replace text buttons with SVG icon buttons (toggle sync, unbind, expand logs)
- Expand: either `<details>` in a full-width child row, or toggle class via tiny inline JS / query `?expand=<user_id>`
- Nested mini-table: started_at (Asia/Shanghai display if project already formats times), trigger, status badge, message/counts
- Empty: 「近 7 天暂无同步记录」

- [ ] **Step 3: Route**

- For each listed user (or only expanded id), attach `recent_runs`
- Prefer expand-on-demand: `GET /admin/users/{id}/sync-runs` returning HTML fragment **or** JSON; keep `require_admin`
- Ensure open_id column ellipsis + `title`

- [ ] **Step 4: Tests**

- Admin page contains icon button markup / `aria-label`
- With seeded `SyncRun`, expand endpoint or page includes message text
- Without runs, empty state present

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: polish admin UI with icons and inline sync logs"
```

---

### Task 4: Docs + full suite

**Files:**
- Modify: `CHANGELOG.md`, `README.md` (short bullets)
- Optional: `docs/ADMIN-SETUP.md` one-liner about sync history

- [ ] **Step 1: Document** 1200px shell, icon actions, `sync_runs` 7-day retention; no new env vars

- [ ] **Step 2: Run full suite**

```bash
python3 -m unittest discover -s tests -v
```

- [ ] **Step 3: Commit + open PR to `main`**

```bash
git commit -m "docs: admin UI polish and sync_runs notes"
```

PR description: summarize UI + `sync_runs`, deploy note (rebuild container; no new env). Do not merge yourself.

---

## Manual verify (after deploy)

1. Hard-refresh `/` and `/admin` — content ~1200px, no horizontal scrollbar.
2. Headers stay single-line; long open_id truncates with hover title.
3. Icon toggle / unbind still confirm and work.
4. Trigger a manual sync; expand that user — new row appears within 7 days.
5. Confirm home dashboard still works at new width.
