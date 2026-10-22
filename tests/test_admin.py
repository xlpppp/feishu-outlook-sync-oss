# tests/test_admin.py
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Stable secrets for session cookies in tests
_TEST_ENV = {
    "SECRET_KEY": "test-secret-key-for-admin-suite",
    "COOKIE_SECURE": "false",
    "TOKEN_ENCRYPTION_KEY": "",
    "DATABASE_URL": "sqlite:///:memory:",
    "PUSH_SYNC_ENABLED": "false",
}


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


class AdminRouteTests(unittest.TestCase):
    """GET /admin auth + list coverage."""

    def setUp(self) -> None:
        self._env = patch.dict(os.environ, {**_TEST_ENV, "ADMIN_FEISHU_OPEN_IDS": "ou_admin"}, clear=False)
        self._env.start()
        from app.config import get_settings

        get_settings.cache_clear()

        from app.db import Base, get_db
        from app.main import create_app
        from app.models import EventMapping, User
        from app.session_auth import set_session_user
        from app import tokens

        self.User = User
        self.EventMapping = EventMapping
        self.tokens = tokens
        self.set_session_user = set_session_user

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.Session()

        self.admin = User(
            feishu_open_id="ou_admin",
            feishu_name="管理员",
            display_name="管理员",
            ms_email="admin@example.com",
        )
        self.other = User(
            feishu_open_id="ou_other",
            feishu_name="其他用户",
            display_name="其他用户",
            ms_email="other@example.com",
            sync_enabled=True,
        )
        self.db.add_all([self.admin, self.other])
        self.db.flush()
        tokens.upsert_token(
            self.db,
            self.other.id,
            tokens.PROVIDER_MS,
            access_token="ms-access",
            refresh_token="ms-refresh",
            expires_in=3600,
        )
        tokens.upsert_token(
            self.db,
            self.other.id,
            tokens.PROVIDER_FEISHU,
            access_token="fs-access",
            refresh_token="fs-refresh",
            expires_in=3600,
        )
        self.db.add(
            EventMapping(
                user_id=self.other.id,
                feishu_event_id="fev1",
                outlook_event_id="oev1",
                content_hash="abc",
            )
        )
        self.db.commit()

        def _override_db():
            try:
                yield self.db
            finally:
                pass

        self._sched = patch("app.main.start_scheduler")
        self._sched_stop = patch("app.main.stop_scheduler")
        self._sched.start()
        self._sched_stop.start()

        self.app = create_app()
        self.app.dependency_overrides[get_db] = _override_db
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()
        self._sched.stop()
        self._sched_stop.stop()
        self.db.close()
        self.engine.dispose()
        self._env.stop()
        from app.config import get_settings

        get_settings.cache_clear()

    def _login_as(self, user_id: int) -> None:
        resp = Response()
        self.set_session_user(resp, user_id)
        cookie = resp.headers.get("set-cookie", "")
        # fos_session=...; Path=/; ...
        part = cookie.split(";", 1)[0]
        name, _, value = part.partition("=")
        self.client.cookies.set(name, value)

    def test_empty_allowlist_returns_404(self) -> None:
        with patch.dict(os.environ, {"ADMIN_FEISHU_OPEN_IDS": ""}, clear=False):
            from app.config import get_settings

            get_settings.cache_clear()
            self._login_as(self.admin.id)
            r = self.client.get("/admin", follow_redirects=False)
            self.assertEqual(r.status_code, 404)

    def test_non_admin_returns_403(self) -> None:
        self._login_as(self.other.id)
        r = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(r.status_code, 403)

    def test_unauthenticated_redirects_to_feishu_oauth(self) -> None:
        r = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        loc = r.headers.get("location", "")
        self.assertTrue(loc.startswith("/oauth/feishu/start"))
        self.assertIn("next=/admin", loc)

    def test_admin_sees_user_list(self) -> None:
        self._login_as(self.admin.id)
        r = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertIn("other@example.com", body)
        self.assertIn("其他用户", body)

    def test_admin_icon_actions_and_aria(self) -> None:
        self._login_as(self.admin.id)
        r = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertIn('aria-label="关闭自动同步"', body)
        self.assertIn('aria-label="解除登录绑定"', body)
        self.assertIn("查看近 7 天同步记录", body)
        self.assertIn("icon-btn admin-icon", body)
        self.assertIn("admin-table", body)

    def test_expand_empty_sync_runs(self) -> None:
        self._login_as(self.admin.id)
        r = self.client.get(
            f"/admin?expand={self.other.id}", follow_redirects=False
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("近 7 天暂无同步记录", r.text)
        frag = self.client.get(
            f"/admin/users/{self.other.id}/sync-runs", follow_redirects=False
        )
        self.assertEqual(frag.status_code, 200)
        self.assertIn("近 7 天暂无同步记录", frag.text)

    def test_expand_with_sync_runs(self) -> None:
        from datetime import datetime, timezone

        from app.sync_runs import record_sync_run

        record_sync_run(
            self.db,
            self.other.id,
            trigger="manual",
            status="ok",
            message="create=2 update=1 skip=0",
            created=2,
            updated=1,
            deleted=0,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        self.db.commit()
        self._login_as(self.admin.id)
        r = self.client.get(
            f"/admin?expand={self.other.id}", follow_redirects=False
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("create=2 update=1", r.text)
        self.assertIn("手动", r.text)
        frag = self.client.get(
            f"/admin/users/{self.other.id}/sync-runs", follow_redirects=False
        )
        self.assertEqual(frag.status_code, 200)
        self.assertIn("create=2 update=1", frag.text)


class AdminActionTests(unittest.TestCase):
    """POST toggle sync + unbind tokens."""

    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ, {**_TEST_ENV, "ADMIN_FEISHU_OPEN_IDS": "ou_admin"}, clear=False
        )
        self._env.start()
        from app.config import get_settings

        get_settings.cache_clear()

        from app.db import Base, get_db
        from app.main import create_app
        from app.models import EventMapping, User
        from app.session_auth import set_session_user
        from app import tokens

        self.User = User
        self.EventMapping = EventMapping
        self.tokens = tokens
        self.set_session_user = set_session_user

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.Session()

        self.admin = User(
            feishu_open_id="ou_admin",
            feishu_name="管理员",
            display_name="管理员",
        )
        self.target = User(
            feishu_open_id="ou_target",
            feishu_name="目标用户",
            ms_email="target@example.com",
            sync_enabled=True,
        )
        self.db.add_all([self.admin, self.target])
        self.db.flush()
        tokens.upsert_token(
            self.db,
            self.target.id,
            tokens.PROVIDER_MS,
            access_token="ms-access",
            refresh_token="ms-refresh",
            expires_in=3600,
        )
        tokens.upsert_token(
            self.db,
            self.target.id,
            tokens.PROVIDER_FEISHU,
            access_token="fs-access",
            refresh_token="fs-refresh",
            expires_in=3600,
        )
        self.db.add(
            EventMapping(
                user_id=self.target.id,
                feishu_event_id="fev1",
                outlook_event_id="oev1",
                content_hash="abc",
            )
        )
        self.db.commit()
        self.mapping_count_before = (
            self.db.query(EventMapping)
            .filter(EventMapping.user_id == self.target.id)
            .count()
        )

        def _override_db():
            try:
                yield self.db
            finally:
                pass

        self._sched = patch("app.main.start_scheduler")
        self._sched_stop = patch("app.main.stop_scheduler")
        self._ensure = patch(
            "app.routes.admin.push_subscriptions.ensure_user_subscriptions"
        )
        self._cleanup = patch(
            "app.routes.admin.push_subscriptions.cleanup_user_subscriptions"
        )
        self._sched.start()
        self._sched_stop.start()
        self.mock_ensure = self._ensure.start()
        self.mock_cleanup = self._cleanup.start()

        self.app = create_app()
        self.app.dependency_overrides[get_db] = _override_db
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()
        self._ensure.stop()
        self._cleanup.stop()
        self._sched.stop()
        self._sched_stop.stop()
        self.db.close()
        self.engine.dispose()
        self._env.stop()
        from app.config import get_settings

        get_settings.cache_clear()

    def _login_as(self, user_id: int) -> None:
        resp = Response()
        self.set_session_user(resp, user_id)
        cookie = resp.headers.get("set-cookie", "")
        part = cookie.split(";", 1)[0]
        name, _, value = part.partition("=")
        self.client.cookies.set(name, value)

    def test_admin_toggle_sync_off(self) -> None:
        self._login_as(self.admin.id)
        r = self.client.post(
            f"/admin/users/{self.target.id}/sync",
            data={"enabled": "0"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers.get("location", "").startswith("/admin"))
        self.db.refresh(self.target)
        self.assertFalse(self.target.sync_enabled)
        self.mock_cleanup.assert_called()

    def test_admin_unbind_clears_tokens_keeps_user_and_mappings(self) -> None:
        self._login_as(self.admin.id)
        r = self.client.post(
            f"/admin/users/{self.target.id}/unbind",
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers.get("location", "").startswith("/admin"))
        self.assertFalse(
            self.tokens.has_token(self.db, self.target.id, self.tokens.PROVIDER_MS)
        )
        self.assertFalse(
            self.tokens.has_token(
                self.db, self.target.id, self.tokens.PROVIDER_FEISHU
            )
        )
        still = self.db.get(self.User, self.target.id)
        self.assertIsNotNone(still)
        self.assertEqual(
            self.db.query(self.EventMapping)
            .filter(self.EventMapping.user_id == self.target.id)
            .count(),
            self.mapping_count_before,
        )
        self.mock_cleanup.assert_called()

    def test_non_admin_post_forbidden(self) -> None:
        self._login_as(self.target.id)
        r = self.client.post(
            f"/admin/users/{self.target.id}/sync",
            data={"enabled": "0"},
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 403)

    def test_empty_allowlist_post_404(self) -> None:
        with patch.dict(os.environ, {"ADMIN_FEISHU_OPEN_IDS": ""}, clear=False):
            from app.config import get_settings

            get_settings.cache_clear()
            self._login_as(self.admin.id)
            r = self.client.post(
                f"/admin/users/{self.target.id}/unbind",
                follow_redirects=False,
            )
            self.assertEqual(r.status_code, 404)


class OAuthNextRedirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {**_TEST_ENV, "ADMIN_FEISHU_OPEN_IDS": "", "FEISHU_APP_ID": "cli_test"},
            clear=False,
        )
        self._env.start()
        from app.config import get_settings

        get_settings.cache_clear()
        self._sched = patch("app.main.start_scheduler")
        self._sched_stop = patch("app.main.stop_scheduler")
        self._sched.start()
        self._sched_stop.start()
        from app.main import create_app

        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self._sched.stop()
        self._sched_stop.stop()
        self._env.stop()
        from app.config import get_settings

        get_settings.cache_clear()

    def test_feishu_start_stores_safe_next(self) -> None:
        with patch("app.auth_feishu.build_auth_url", return_value="https://example.com/oauth"):
            r = self.client.get(
                "/oauth/feishu/start?next=/admin", follow_redirects=False
            )
        self.assertEqual(r.status_code, 302)
        from app.routes import oauth as oauth_mod

        self.assertTrue(any(m.get("next") == "/admin" for m in oauth_mod._oauth_states.values()))

    def test_feishu_start_rejects_open_redirect(self) -> None:
        with patch("app.auth_feishu.build_auth_url", return_value="https://example.com/oauth"):
            r = self.client.get(
                "/oauth/feishu/start?next=//evil.example", follow_redirects=False
            )
        self.assertEqual(r.status_code, 302)
        from app.routes import oauth as oauth_mod

        self.assertTrue(
            all(
                m.get("next") in (None, "")
                for m in oauth_mod._oauth_states.values()
                if m.get("provider") == "feishu"
            )
            or not any(
                m.get("next") == "//evil.example"
                for m in oauth_mod._oauth_states.values()
            )
        )


if __name__ == "__main__":
    unittest.main()
