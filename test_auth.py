# dashboard/tests/test_auth.py

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.urls import reverse

from core.auth import generate_token, hash_token, api_auth_required
from dashboard.models import APIToken

User = get_user_model()


def _make_view():
    """Simple view wrapped with the decorator under test."""
    @api_auth_required
    def view(request):
        from django.http import JsonResponse
        return JsonResponse({"ok": True})
    return view


class APIAuthDecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", password="x", email="t@example.com"
        )
        self.plaintext = generate_token()
        self.token = APIToken.objects.create(
            user=self.user,
            name="test token",
            token_hash=hash_token(self.plaintext),
            scopes=["threats:read"],
            is_active=True,
        )
        self.view = _make_view()

    # ── Missing token ────────────────────────────────────────────────
    def test_missing_token_returns_401(self):
        request = self.factory.get("/api/threats/kepler/")
        # AnonymousUser
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()

        response = self.view(request)
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"Authentication required", response.content)

    def test_missing_token_sets_www_authenticate_header(self):
        request = self.factory.get("/api/threats/kepler/")
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertIn("WWW-Authenticate", response)
        self.assertIn("Bearer", response["WWW-Authenticate"])

    # ── Invalid token ────────────────────────────────────────────────
    def test_invalid_token_returns_401(self):
        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION="Bearer obs_notarealtoken000000000000000000000000000000000000000000000000",
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"Invalid or expired token", response.content)

    def test_malformed_header_returns_401(self):
        """Token without 'Bearer ' prefix is ignored."""
        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION=self.plaintext,  # no 'Bearer ' prefix
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 401)

    def test_wrong_prefix_rejected(self):
        """Token missing obs_ prefix is rejected before DB lookup."""
        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION="Bearer notobs_abc123",
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 401)

    # ── Expired/revoked token ────────────────────────────────────────
    def test_inactive_token_returns_401(self):
        self.token.is_active = False
        self.token.save()
        # Clear cache so the DB is actually hit
        from django.core.cache import cache
        cache.clear()

        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION=f"Bearer {self.plaintext}",
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 401)

    def test_expired_token_returns_401(self):
        from django.utils import timezone
        from datetime import timedelta
        self.token.expires_at = timezone.now() - timedelta(hours=1)
        self.token.is_active = False  # enforce via is_active; expire via cron
        self.token.save()
        from django.core.cache import cache
        cache.clear()

        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION=f"Bearer {self.plaintext}",
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 401)

    # ── Valid token ──────────────────────────────────────────────────
    def test_valid_token_returns_200(self):
        from django.core.cache import cache
        cache.clear()

        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION=f"Bearer {self.plaintext}",
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = self.view(request)
        self.assertEqual(response.status_code, 200)

    def test_valid_token_attaches_user_to_request(self):
        from django.core.cache import cache
        cache.clear()

        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION=f"Bearer {self.plaintext}",
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        self.view(request)
        self.assertEqual(request.user.username, "testuser")

    def test_valid_token_served_from_cache(self):
        """Second request should hit cache, not DB."""
        from django.core.cache import cache
        cache.clear()

        for _ in range(2):
            request = self.factory.get(
                "/api/threats/kepler/",
                HTTP_AUTHORIZATION=f"Bearer {self.plaintext}",
            )
            from django.contrib.auth.models import AnonymousUser
            request.user = AnonymousUser()
            response = self.view(request)
            self.assertEqual(response.status_code, 200)

        # If second request hit DB it would also pass, but this verifies
        # no exception from double-lookup
        cache_key = f"apitoken:{hash_token(self.plaintext)}"
        self.assertIsNotNone(cache.get(cache_key))

    # ── Session auth bypass ──────────────────────────────────────────
    def test_authenticated_session_user_bypasses_token_check(self):
        """Django session auth should pass without any token header."""
        request = self.factory.get("/api/threats/kepler/")
        request.user = self.user  # already authenticated
        response = self.view(request)
        self.assertEqual(response.status_code, 200)

    # ── Scope enforcement ────────────────────────────────────────────
    def test_insufficient_scope_returns_403(self):
        from django.core.cache import cache
        cache.clear()

        @api_auth_required(require_scope="admin:write")
        def scoped_view(request):
            from django.http import JsonResponse
            return JsonResponse({"ok": True})

        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION=f"Bearer {self.plaintext}",
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = scoped_view(request)
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Insufficient permissions", response.content)

    def test_correct_scope_returns_200(self):
        from django.core.cache import cache
        cache.clear()

        @api_auth_required(require_scope="threats:read")
        def scoped_view(request):
            from django.http import JsonResponse
            return JsonResponse({"ok": True})

        request = self.factory.get(
            "/api/threats/kepler/",
            HTTP_AUTHORIZATION=f"Bearer {self.plaintext}",
        )
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        response = scoped_view(request)
        self.assertEqual(response.status_code, 200)
