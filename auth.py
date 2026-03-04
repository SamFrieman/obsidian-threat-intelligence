# core/auth.py
"""
Token-based API authentication.

Storage model:
  - APIToken model stores SHA-256(token) — never the plaintext token
  - Plaintext is shown once at creation time only
  - Tokens are prefixed (obs_<random>) so they're identifiable in logs/secrets scanners

Auth flow:
  1. Check for active Django session → pass through (browser users)
  2. Check Authorization: Bearer <token> header
  3. Hash the provided token, look up in cache → DB
  4. Attach token owner to request.user

Tradeoff: caching token lookups (5 min TTL) means revoked tokens remain valid
up to 5 minutes. Acceptable for internal tooling; reduce TTL if needed.
"""
import hashlib
import logging
import secrets
from functools import wraps

from django.http import JsonResponse

logger = logging.getLogger("obsidian.auth")
logger_security = logging.getLogger("obsidian.security")

_TOKEN_PREFIX = "obs_"
_CACHE_TTL = 300  # 5 minutes
_CACHE_MISS_TTL = 60  # Cache negative results shorter


def generate_token() -> str:
    """
    Generate a new plaintext token. Call once; store only the hash.
    Returns: 'obs_<40 hex chars>'
    """
    return _TOKEN_PREFIX + secrets.token_hex(40)


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _resolve_token(plaintext: str, request) -> "APIToken | None":
    """
    Resolve a plaintext token to its APIToken record.
    Cache-first. Returns None on any failure.
    """
    from django.core.cache import cache
    from dashboard.models import APIToken

    if not plaintext or not plaintext.startswith(_TOKEN_PREFIX):
        return None

    token_hash = hash_token(plaintext)
    cache_key = f"apitoken:{token_hash}"

    cached = cache.get(cache_key)
    if cached is False:
        # Previously confirmed invalid
        return None
    if cached is not None:
        # Cached token record dict → reconstruct lightweight object
        return _CachedToken(**cached)

    try:
        token = (
            APIToken.objects
            .select_related("user")
            .get(token_hash=token_hash, is_active=True)
        )
        cache.set(cache_key, {
            "token_id": token.pk,
            "user_id": token.user_id,
            "username": token.user.username,
            "scopes": token.scopes,
        }, timeout=_CACHE_TTL)

        logger_security.info(
            "api_token_resolved",
            extra={
                "token_id": token.pk,
                "username": token.user.username,
                "path": request.path,
                "ip": _get_ip(request),
            },
        )
        return token

    except APIToken.DoesNotExist:
        cache.set(cache_key, False, timeout=_CACHE_MISS_TTL)
        logger_security.warning(
            "api_token_invalid",
            extra={"path": request.path, "ip": _get_ip(request)},
        )
        return None


class _CachedToken:
    """Lightweight stand-in for an APIToken when serving from cache."""
    def __init__(self, token_id, user_id, username, scopes):
        self.pk = token_id
        self.user_id = user_id
        self.scopes = scopes
        # Minimal user-like object so request.user.username works
        self.user = type("_User", (), {"username": username, "is_authenticated": True,
                                       "id": user_id, "is_staff": False})()


def _get_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")


def _extract_bearer_token(request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def api_auth_required(view_func=None, *, require_scope: str | None = None):
    """
    Decorator: require authenticated Django session OR valid Bearer token.

    Usage:
        @api_auth_required
        def my_view(request): ...

        @api_auth_required(require_scope="threats:read")
        def my_view(request): ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            # Path 1: Active Django session (browser users, admin)
            if request.user.is_authenticated:
                return fn(request, *args, **kwargs)

            # Path 2: Bearer token
            plaintext = _extract_bearer_token(request)
            if not plaintext:
                return JsonResponse(
                    {"error": "Authentication required.",
                     "detail": "Provide Authorization: Bearer <token> header."},
                    status=401,
                    headers={"WWW-Authenticate": 'Bearer realm="OBSIDIAN"'},
                )

            token = _resolve_token(plaintext, request)
            if token is None:
                logger_security.warning(
                    "api_auth_failed",
                    extra={"path": request.path, "ip": _get_ip(request)},
                )
                return JsonResponse(
                    {"error": "Invalid or expired token."},
                    status=401,
                    headers={"WWW-Authenticate": 'Bearer realm="OBSIDIAN"'},
                )

            # Scope check (optional)
            if require_scope and require_scope not in (token.scopes or []):
                logger_security.warning(
                    "api_scope_denied",
                    extra={
                        "required_scope": require_scope,
                        "token_scopes": token.scopes,
                        "path": request.path,
                    },
                )
                return JsonResponse(
                    {"error": "Insufficient permissions.",
                     "detail": f"Scope '{require_scope}' required."},
                    status=403,
                )

            # Attach to request so views can inspect it
            request.api_token = token
            # Don't overwrite request.user if already set; set minimally otherwise
            if not request.user.is_authenticated:
                request.user = token.user

            return fn(request, *args, **kwargs)

        return wrapper

    # Support both @api_auth_required and @api_auth_required(require_scope=...)
    if view_func is not None:
        return decorator(view_func)
    return decorator
