# core/observability.py
"""
Structured JSON logging formatter + RequestTracingMiddleware.

Import this module in settings.py LOGGING config.
Add RequestTracingMiddleware as the FIRST middleware in MIDDLEWARE list.
"""
import json
import logging
import time
import threading
import uuid


# ── Thread-local request context ─────────────────────────────────────
_ctx = threading.local()


def get_request_id() -> str:
    """Retrieve the current request ID from thread-local. Empty string if not set."""
    return getattr(_ctx, "request_id", "")


def get_user_id() -> int | None:
    return getattr(_ctx, "user_id", None)


# ── JSON formatter ────────────────────────────────────────────────────

class StructuredJsonFormatter(logging.Formatter):
    """
    Emit one JSON object per log line.
    Compatible with Loki, Datadog, CloudWatch Logs Insights, and jq.

    Automatic fields on every line:
      ts, level, logger, msg, module, line, request_id, user_id

    Extra fields: pass via logger.info("msg", extra={"key": val, ...})
    """

    # Fields automatically pulled from thread-local context
    _CONTEXT_FIELDS = ("request_id", "user_id")

    # Fields that are safe to pass through from LogRecord.extra
    _ALLOWED_EXTRA = frozenset({
        "request_id", "user_id", "duration_ms", "status_code",
        "method", "path", "ip", "endpoint", "event_count",
        "query_ms", "cache_hit", "task_id", "feed_id",
        "token_id", "username", "error", "note",
        "since_hours", "upserted", "batches", "errors",
        "deleted_cells", "elapsed_s",
    })

    def format(self, record: logging.LogRecord) -> str:
        log: dict = {
            "ts":     self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
            "module": record.module,
            "line":   record.lineno,
        }

        # Thread-local context (set by RequestTracingMiddleware)
        for field in self._CONTEXT_FIELDS:
            val = getattr(_ctx, field, None)
            if val is not None:
                log[field] = val

        # Extra fields from the log call
        for field in self._ALLOWED_EXTRA:
            if hasattr(record, field):
                log[field] = getattr(record, field)

        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)

        if record.stack_info:
            log["stack"] = self.formatStack(record.stack_info)

        return json.dumps(log, default=str)


# ── Middleware ────────────────────────────────────────────────────────

_access_logger = logging.getLogger("obsidian.access")
_slow_logger   = logging.getLogger("obsidian.slow_queries")


def _get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")


class RequestTracingMiddleware:
    """
    Middleware responsibilities:
      1. Accept or generate X-Request-ID
      2. Attach to thread-local (propagates to all log lines in this request)
      3. Echo request ID in response header
      4. Emit structured access log on response

    Must be the FIRST entry in settings.MIDDLEWARE.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = (
            request.headers.get("X-Request-ID") or
            str(uuid.uuid4())
        )
        _ctx.request_id = request_id
        _ctx.user_id = None  # will be set after auth middleware runs

        request.request_id = request_id
        start = time.monotonic()

        response = self.get_response(request)

        # Set user_id now that auth middleware has run
        if hasattr(request, "user") and request.user.is_authenticated:
            _ctx.user_id = request.user.id

        duration_ms = round((time.monotonic() - start) * 1000, 1)
        response["X-Request-ID"] = request_id

        _access_logger.info(
            "request",
            extra={
                "request_id":  request_id,
                "method":      request.method,
                "path":        request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "user_id":     getattr(request.user, "id", None),
                "ip":          _get_client_ip(request),
            },
        )

        # Clear thread-local after response (important for thread-reuse in gthread)
        _ctx.request_id = ""
        _ctx.user_id = None

        return response


class SlowQueryLoggingMiddleware:
    """
    Log requests that trigger slow queries.
    Only active when DEBUG=True OR SLOW_QUERY_LOG=True.

    Threshold configured via settings.SLOW_QUERY_THRESHOLD_MS (default 200).
    """

    def __init__(self, get_response):
        self.get_response = get_response
        from django.conf import settings
        self.threshold_ms = getattr(settings, "SLOW_QUERY_THRESHOLD_MS", 200)
        self.enabled = getattr(settings, "SLOW_QUERY_LOG", False)

    def __call__(self, request):
        if not self.enabled:
            return self.get_response(request)

        from django.db import connection, reset_queries
        from django.conf import settings
        reset_queries()

        response = self.get_response(request)

        slow = [
            q for q in connection.queries
            if float(q["time"]) * 1000 > self.threshold_ms
        ]
        if slow:
            _slow_logger.warning(
                "slow_queries_detected",
                extra={
                    "path":        request.path,
                    "query_count": len(slow),
                    "slowest_ms":  max(float(q["time"]) * 1000 for q in slow),
                    "queries": [
                        {"sql": q["sql"][:300], "ms": round(float(q["time"]) * 1000, 1)}
                        for q in slow[:5]  # cap at 5 in log to avoid huge lines
                    ],
                },
            )

        return response
