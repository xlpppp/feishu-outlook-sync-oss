# feishu-outlook-sync-oss

Contributor and agent notes for this open-source repository.

## Project Commands

| Command | Description |
|---------|-------------|
| `docker compose build` (or `docker compose up -d --build`) | Build / rebuild the app |
| `python3 -m unittest discover -s tests -v` | Run unit tests |
| `python3 scripts/smoke_check.py` | Import + route smoke check |
| No ruff/mypy gate yet | Linting |

## Project Info

- **Stack**: Python 3 / FastAPI / SQLAlchemy / Jinja2 / Docker Compose
- **Repository**: https://github.com/xlpppp/feishu-outlook-sync-oss
- **Default branch**: `main`
- **Compose service name**: `sync` (container may be named `feishu-outlook-sync`)

## Guidelines

- Prefer reading `README.md`, `change.md`, and `docs/` before changing behavior.
- Compose service name is `sync`, not `app`.
- Do not run `docker compose down -v` (destroys the data volume / SQLite DB).
- Never commit `.env`, `*.db`, or real tokens / secrets.
- By default do not sync Feishu “subscribed” calendars to Outlook (`SKIP_SUBSCRIBED_CALENDARS=true`).
- `dry_run` syncs must not write `sync_runs`.
- Admin UI sync history is last 7 days; expand via `/admin?expand=<id>`.
- `ADMIN_FEISHU_OPEN_IDS` must match real `users.feishu_open_id` values from the DB.
- Agents may change code/docs/PRs; do not rewrite a deployer's production `.env`.

## Submodules

<!-- No nested AGENTS.md yet -->
