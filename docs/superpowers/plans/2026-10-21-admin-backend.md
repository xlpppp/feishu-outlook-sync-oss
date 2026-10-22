# Admin Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/admin` Jinja page so allowlisted Feishu users can list all bound accounts, toggle `sync_enabled`, and clear OAuth tokens (unbind) without deleting users or mappings.

**Architecture:** Reuse the existing FastAPI + Jinja dashboard stack. Parse `ADMIN_FEISHU_OPEN_IDS` in config; gate `/admin` with a `require_admin` dependency (empty allowlist → 404; not logged in → redirect to Feishu OAuth with return path; wrong user → 403). Toggle/unbind POST handlers mirror `web.toggle_sync` and call `tokens.delete_token` + `push_subscriptions.cleanup_user_subscriptions`.

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2, unittest (existing style in `tests/`), signed cookie session (`session_auth`).

**Spec:** `docs/superpowers/specs/2026-10-21-admin-backend-design.md`

## Global Constraints

- Never commit `.env`, secrets, `*.db`, or `/data`.
- Unbind deletes **tokens only** (both `microsoft` and `feishu`); keep `users` and `event_mappings`.
- Empty `ADMIN_FEISHU_OPEN_IDS` → admin routes return **404** (do not reveal admin exists).
- Open one PR against GitHub `main` after implementation.
- Chinese UI copy consistent with existing dashboard.
- Do not add pagination/search, delete-user, or remote calendar cleanup in this plan.

## File map

| File | Role |
|------|------|
| `app/config.py` | Parse `ADMIN_FEISHU_OPEN_IDS` → `admin_feishu_open_ids: list[str]` + helper `is_admin_open_id(oid)` |
| `app/routes/admin.py` | **Create:** `require_admin`, `GET /admin`, toggle, unbind |
| `app/main.py` | `include_router(admin.router)` |
| `app/routes/oauth.py` | Optional `next` in OAuth state; after Feishu callback redirect to safe relative path |
| `app/templates/admin.html` | Admin table UI |
| `app/templates/index.html` | Link to `/admin` when `is_admin` |
| `app/routes/web.py` | Pass `is_admin` in dashboard context |
| `.env.example`, `docs/ENV.md`, `README.md`, `CHANGELOG.md` | Document env + feature |
| `tests/test_admin.py` | **Create:** auth + toggle + unbind tests |

---

### Task 1: Config allowlist + failing auth tests

**Files:**
- Modify: `app/config.py`
- Create: `tests/test_admin.py`
- Test: `tests/test_admin.py`

**Interfaces:**
- Produces: `Settings.admin_feishu_open_ids: list[str]`; `Settings.is_admin_open_id(open_id: str | None) -> bool` (False if open_id empty or list empty)

- [ ] **Step 1: Write failing tests for allowlist parsing**

```python
# tests/test_admin.py (partial)
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class AdminAllowlistConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        from app.config import get_settings
        get_settings.cache_clear()

    def test_empty_allowlist(self) -> None:
        with patch.dict(os.environ, {"ADMIN_FEISHU_OPEN_IDS": ""}, clear=False):
            from app.config import get_settings
            get_settings.cache_clear()
            s = get_settings()
            self.assertEqual(s.admin_feishu_open_ids, [])
            self.assertFalse(s.is_admin_open_id("ou_abc"))

    def test_parse_and_match(self) -> None:
        with patch.dict(
            os.environ, {"ADMIN_FEISHU_OPEN_IDS": "ou_a, ou_b"}, clear=False
        ):
            from app.config import get_settings
            get_settings.cache_clear()
            s = get_settings()
            self.assertEqual(s.admin_feishu_open_ids, ["ou_a", "ou_b"])
            self.assertTrue(s.is_admin_open_id("ou_a"))
            self.assertFalse(s.is_admin_open_id("ou_other"))
            self.assertFalse(s.is_admin_open_id(None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect fail**

```bash
cd /repo && python -m unittest tests.test_admin.AdminAllowlistConfigTests -v
```

Expected: FAIL (attribute missing) or ImportError.

- [ ] **Step 3: Implement config**

In `Settings.__init__`, after cookie settings:

```python
raw_admins = os.getenv("ADMIN_FEISHU_OPEN_IDS", "")
self.admin_feishu_open_ids: list[str] = [
    p.strip() for p in raw_admins.replace(";", ",").split(",") if p.strip()
]
```

Add method:

```python
def is_admin_open_id(self, open_id: str | None) -> bool:
    if not open_id or not self.admin_feishu_open_ids:
        return False
    return open_id.strip() in self.admin_feishu_open_ids
```

- [ ] **Step 4: Re-run tests — expect PASS**

```bash
python -m unittest tests.test_admin.AdminAllowlistConfigTests -v
```

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_admin.py
git commit -m "feat(admin): parse ADMIN_FEISHU_OPEN_IDS allowlist"
```

---

### Task 2: `require_admin` + GET `/admin` list (TDD)

**Files:**
- Create: `app/routes/admin.py`
- Modify: `app/main.py`
- Create: `app/templates/admin.html` (minimal table OK; polish in Task 4)
- Modify: `tests/test_admin.py`

**Interfaces:**
- Consumes: `get_settings().is_admin_open_id`, `get_session_user_id`, `User`, `tokens.has_token`
- Produces: `require_admin(request, db) -> User` (admin user); raises/returns 404/403/RedirectResponse; `GET /admin` HTML

- [ ] **Step 1: Add TestClient auth tests (failing)**

Use FastAPI `TestClient`, override `get_db`, patch settings allowlist, create in-memory SQLite users. Pattern:

```python
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_db
from app.main import create_app
from app.models import User
from app.session_auth import set_session_user

# Helper: make_client(db_url) that yields TestClient with session cookie for a user
# Tests:
# - allowlist empty → GET /admin == 404
# - logged in non-admin → 403
# - admin → 200 and body contains other user's ms_email or feishu_name
```

Implement concrete helpers in the test file (in-memory sqlite `sqlite:///:memory:`, `Base.metadata.create_all`, dependency override). If `httpx`/`TestClient` is unavailable in the environment, use Starlette's TestClient from `starlette.testclient` (comes with FastAPI).

- [ ] **Step 2: Run — expect FAIL** (route missing / 404 always)

```bash
python -m unittest tests.test_admin -v
```

- [ ] **Step 3: Implement `app/routes/admin.py`**

```python
"""Admin: list users, toggle sync, unbind tokens."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import push_subscriptions, tokens
from ..config import get_settings
from ..db import get_db
from ..models import EventMapping, User
from ..session_auth import get_session_user_id

log = logging.getLogger("admin")
router = APIRouter(tags=["admin"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def require_admin(request: Request, db: Session) -> User | Response:
    settings = get_settings()
    if not settings.admin_feishu_open_ids:
        return Response(status_code=404)
    uid = get_session_user_id(request)
    if not uid:
        return RedirectResponse(
            "/oauth/feishu/start?next=/admin", status_code=302
        )
    user = db.get(User, uid)
    if not user or not settings.is_admin_open_id(user.feishu_open_id):
        return Response("Forbidden", status_code=403)
    return user


@router.get("/admin", response_class=HTMLResponse)
def admin_index(
    request: Request,
    flash: str | None = None,
    flash_err: str | None = None,
    db: Session = Depends(get_db),
):
    gate = require_admin(request, db)
    if isinstance(gate, Response):
        return gate
    admin = gate
    users = db.query(User).order_by(User.id.desc()).all()
    mapping_counts = dict(
        db.query(EventMapping.user_id, func.count(EventMapping.id))
        .group_by(EventMapping.user_id)
        .all()
    )
    rows = []
    for u in users:
        rows.append(
            {
                "user": u,
                "ms_connected": tokens.has_token(db, u.id, tokens.PROVIDER_MS),
                "feishu_connected": tokens.has_token(
                    db, u.id, tokens.PROVIDER_FEISHU
                ),
                "mapping_count": int(mapping_counts.get(u.id, 0)),
            }
        )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "request": request,
            "admin": admin,
            "rows": rows,
            "flash": flash,
            "flash_error": flash_err == "1",
            "outlook_target_calendar_name": get_settings().outlook_calendar_name,
            "feishu_target_calendar_name": get_settings().feishu_sync_calendar_name,
            "sync_interval": get_settings().sync_interval_minutes,
        },
    )
```

Register in `main.py`:

```python
from .routes import api, oauth, web, webhooks, admin
...
app.include_router(admin.router)
```

Minimal `admin.html` extending `base.html` with a table over `rows` (id, names, tokens, sync_enabled, actions stubs OK until Task 3–4).

- [ ] **Step 4: OAuth `next` support**

In `oauth.py` Feishu start: read `next: Optional[str] = None`; if `next` is a safe relative path (`startswith("/")` and not `//`), store in `_oauth_states[state]["next"]`.

In Feishu callback: after success, `dest = meta.get("next") or "/"`; use `_flash_redirect(dest, ...)`.

Same optional `next` on Microsoft start/callback is nice-to-have; Feishu is required for admin.

- [ ] **Step 5: Re-run tests — PASS**

```bash
python -m unittest tests.test_admin -v
```

- [ ] **Step 6: Commit**

```bash
git add app/routes/admin.py app/main.py app/routes/oauth.py app/templates/admin.html tests/test_admin.py
git commit -m "feat(admin): /admin list page with Feishu open_id allowlist gate"
```

---

### Task 3: Toggle sync + unbind tokens (TDD)

**Files:**
- Modify: `app/routes/admin.py`
- Modify: `tests/test_admin.py`

**Interfaces:**
- Produces: `POST /admin/users/{user_id}/sync` Form `enabled`; `POST /admin/users/{user_id}/unbind`
- Consumes: `tokens.delete_token`, `push_subscriptions.cleanup_user_subscriptions` / `ensure_user_subscriptions`

- [ ] **Step 1: Failing tests**

```python
# As admin session:
# POST /admin/users/{id}/sync enabled=0 → target.sync_enabled False; 302 to /admin
# POST unbind → has_token MS and Feishu False; User row still exists; EventMapping count unchanged
# Non-admin POST → 403
# Empty allowlist POST → 404
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement handlers**

```python
@router.post("/admin/users/{user_id}/sync")
def admin_toggle_sync(
    user_id: int,
    request: Request,
    enabled: str = Form("0"),
    db: Session = Depends(get_db),
):
    gate = require_admin(request, db)
    if isinstance(gate, Response):
        return gate
    admin = gate
    target = db.get(User, user_id)
    if not target:
        return RedirectResponse(
            "/admin?flash=" + quote("用户不存在") + "&flash_err=1", status_code=302
        )
    target.sync_enabled = enabled in ("1", "true", "on")
    try:
        if target.sync_enabled:
            push_subscriptions.ensure_user_subscriptions(db, target)
        else:
            push_subscriptions.cleanup_user_subscriptions(db, target)
    except Exception:
        log.exception(
            "admin toggle sync failed admin=%s user=%s", admin.id, target.id
        )
    db.commit()
    log.info(
        "admin_toggle_sync admin_user_id=%s target_user_id=%s enabled=%s",
        admin.id,
        target.id,
        target.sync_enabled,
    )
    return RedirectResponse(
        "/admin?flash=" + quote("已更新自动同步"), status_code=302
    )


@router.post("/admin/users/{user_id}/unbind")
def admin_unbind(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    gate = require_admin(request, db)
    if isinstance(gate, Response):
        return gate
    admin = gate
    target = db.get(User, user_id)
    if not target:
        return RedirectResponse(
            "/admin?flash=" + quote("用户不存在") + "&flash_err=1", status_code=302
        )
    try:
        push_subscriptions.cleanup_user_subscriptions(db, target)
    except Exception:
        log.exception(
            "admin unbind cleanup push failed admin=%s user=%s",
            admin.id,
            target.id,
        )
    tokens.delete_token(db, target.id, tokens.PROVIDER_MS)
    tokens.delete_token(db, target.id, tokens.PROVIDER_FEISHU)
    db.commit()
    log.info(
        "admin_unbind admin_user_id=%s target_user_id=%s", admin.id, target.id
    )
    return RedirectResponse(
        "/admin?flash=" + quote("已解除登录绑定（仅清除 Token）"),
        status_code=302,
    )
```

- [ ] **Step 4: Run all admin tests — PASS**

```bash
python -m unittest tests.test_admin -v
```

- [ ] **Step 5: Commit**

```bash
git add app/routes/admin.py tests/test_admin.py
git commit -m "feat(admin): toggle sync and unbind tokens for any user"
```

---

### Task 4: UI polish + dashboard link + docs

**Files:**
- Modify: `app/templates/admin.html`
- Modify: `app/templates/index.html`
- Modify: `app/routes/web.py` (`is_admin` in `_dashboard_ctx`)
- Modify: `.env.example`, `docs/ENV.md`, `README.md`, `CHANGELOG.md`

- [ ] **Step 1: `is_admin` on home**

In `_dashboard_ctx`:

```python
settings = get_settings()
is_admin = bool(
    user
    and settings.is_admin_open_id(user.feishu_open_id)
)
# add "is_admin": is_admin to return dict
```

In `index.html` (near top of content when `user`):

```html
{% if is_admin %}
<p><a class="btn" href="/admin">管理后台</a></p>
{% endif %}
```

- [ ] **Step 2: Finish `admin.html`**

Table columns per spec; for each row:
- Form POST sync with `enabled` opposite of current; button「关闭自动同步」/「开启自动同步」; `onsubmit="return confirm('…')"`
- Form POST unbind; button「解除登录绑定」; confirm warning that only tokens are cleared

Reuse existing CSS classes (`btn`, `btn danger`, `status-box`, table styles if any; otherwise simple HTML table with existing card wrappers).

- [ ] **Step 3: Docs**

`.env.example`:

```bash
# 管理后台：逗号分隔的飞书 open_id；为空则 /admin 返回 404
# ADMIN_FEISHU_OPEN_IDS=ou_xxx,ou_yyy
```

README / ENV.md: short「管理后台」section pointing at `/admin` and the env var. CHANGELOG Unreleased: bullet for admin backend.

- [ ] **Step 4: Run full unit suite**

```bash
python -m unittest discover -s tests -v
```

Expected: all OK (including prior instance_view tests).

- [ ] **Step 5: Commit + open PR**

```bash
git add app/templates/admin.html app/templates/index.html app/routes/web.py .env.example docs/ENV.md README.md CHANGELOG.md
git commit -m "feat(admin): UI, home link, and docs for admin backend"
```

Open PR to `main` titled like `feat: admin backend for user list / sync toggle / unbind`.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `/admin` Jinja page | 2, 4 |
| `ADMIN_FEISHU_OPEN_IDS` | 1 |
| Empty → 404 | 1–2 |
| Unauthenticated → Feishu OAuth + return | 2 (oauth next) |
| Non-allowlist → 403 | 2 |
| List fields | 2, 4 |
| Toggle sync + push cleanup/ensure | 3 |
| Unbind tokens only | 3 |
| Audit log | 3 |
| Home link for admins | 4 |
| Docs / CHANGELOG | 4 |
| Unit tests | 1–3 |

## Self-review notes

- No TBD placeholders.
- Unbind does not delete User/mappings (matches spec).
- OAuth `next` must reject open redirects (`//evil`, `https://`).
