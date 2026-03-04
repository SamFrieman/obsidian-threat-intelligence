# dashboard/audit.py
"""
Immutable audit log.

Model: AuditLog — write-only from application code.
  - default_permissions = ("view",) prevents Django admin from offering
    add/change/delete buttons even to superusers.
  - No update() or delete() methods are called anywhere in this module.
  - DB-level: consider adding a PostgreSQL trigger (see bottom of file)
    that raises an exception on UPDATE/DELETE for defence-in-depth.

write() function:
  - Never raises. Audit failures must not block operations.
  - Logs its own failure to a dedicated logger so ops can detect it.

Auto-logging via signals:
  - user_logged_in  → AuditLog
  - user_login_failed → AuditLog (SECURITY level)
  - post_save on ThreatEvent/IOC (creates/updates)
  - pre_delete on ThreatEvent/IOC

Manual logging in views:
  from dashboard.audit import write as audit_write
  audit_write(request=request, action="dep_scan", detail={"total": 12})
"""
import logging

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger("obsidian.audit")
logger_security = logging.getLogger("obsidian.security")


# ── Model ─────────────────────────────────────────────────────────────

class AuditLog(models.Model):
    """
    Immutable audit trail. One row per auditable action.
    Never updated or deleted by application code.
    """
    ts          = models.DateTimeField(default=timezone.now, db_index=True)
    actor       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",            # no reverse accessor needed
    )
    actor_username = models.CharField(
        max_length=150, blank=True,
        help_text="Denormalised username — preserved if user is later deleted.",
    )
    action      = models.CharField(max_length=64, db_index=True)
    resource    = models.CharField(max_length=200, blank=True)
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    request_id  = models.CharField(max_length=64, blank=True)
    detail      = models.JSONField(default=dict)
    outcome     = models.CharField(
        max_length=16,
        default="ok",
        choices=[("ok", "OK"), ("error", "Error"), ("denied", "Denied")],
    )

    class Meta:
        ordering = ["-ts"]
        # Restricts Django admin to view only — no add/change/delete in UI
        default_permissions = ("view",)
        indexes = [
            models.Index(fields=["action", "ts"]),
            models.Index(fields=["actor", "ts"]),
        ]

    def save(self, *args, **kwargs):
        # Prevent accidental updates: once a row has a PK it must not be re-saved
        if self.pk is not None:
            raise RuntimeError(
                "AuditLog rows are immutable. Do not call save() on existing instances."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditLog rows cannot be deleted.")

    def __str__(self):
        return f"{self.ts:%Y-%m-%dT%H:%M:%S} [{self.action}] {self.actor_username or '—'}"


# ── Write helper ──────────────────────────────────────────────────────

def _get_ip(request) -> str | None:
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")


def write(
    action: str,
    request=None,
    actor=None,
    resource: str = "",
    detail: dict | None = None,
    outcome: str = "ok",
) -> None:
    """
    Write one audit entry. Never raises.

    Args:
        action:   Short verb string, e.g. "dep_scan", "threat_event_created"
        request:  Django HttpRequest, used to extract user/IP/request_id
        actor:    Explicit user override (use when no request available, e.g. Celery)
        resource: Identifier of the affected object, e.g. "ThreatEvent:42"
        detail:   Arbitrary JSON-serialisable dict
        outcome:  "ok" | "error" | "denied"
    """
    try:
        user = actor
        username = ""
        ip = None
        request_id = ""

        if request is not None:
            if hasattr(request, "user") and request.user.is_authenticated:
                user = request.user
            ip = _get_ip(request)
            request_id = getattr(request, "request_id", "")

        if user is not None:
            username = getattr(user, "username", str(user))

        AuditLog(
            actor=user if (user and hasattr(user, "pk")) else None,
            actor_username=username,
            action=action,
            resource=resource,
            ip_address=ip,
            request_id=request_id,
            detail=detail or {},
            outcome=outcome,
        ).save()

    except Exception:
        # Log failure but never propagate — audit errors must not break operations
        logger.exception(
            "audit_write_failed",
            extra={"action": action, "outcome": outcome},
        )


# ── Signals ───────────────────────────────────────────────────────────

@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    write(
        action="user_login",
        request=request,
        actor=user,
        detail={"username": user.username},
        outcome="ok",
    )
    logger_security.info(
        "user_login",
        extra={
            "username":   user.username,
            "ip":         _get_ip(request),
            "request_id": getattr(request, "request_id", ""),
        },
    )


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request, **kwargs):
    write(
        action="user_login_failed",
        request=request,
        detail={"username": credentials.get("username", "unknown")},
        outcome="denied",
    )
    logger_security.warning(
        "user_login_failed",
        extra={
            "username_attempted": credentials.get("username", "unknown"),
            "ip":                 _get_ip(request),
        },
    )


@receiver(post_save, sender="dashboard.ThreatEvent")
def _on_threatevent_save(sender, instance, created, **kwargs):
    write(
        action="threat_event_created" if created else "threat_event_updated",
        resource=f"ThreatEvent:{instance.pk}",
        detail={
            "severity": instance.severity,
            "source":   instance.source,
            "title":    (instance.title or "")[:100],
        },
    )


@receiver(post_delete, sender="dashboard.ThreatEvent")
def _on_threatevent_delete(sender, instance, **kwargs):
    write(
        action="threat_event_deleted",
        resource=f"ThreatEvent:{instance.pk}",
        detail={"severity": instance.severity, "source": instance.source},
    )


@receiver(post_save, sender="dashboard.IOC")
def _on_ioc_save(sender, instance, created, **kwargs):
    write(
        action="ioc_created" if created else "ioc_updated",
        resource=f"IOC:{instance.pk}",
        detail={
            "indicator_type": instance.indicator_type,
            "source":         instance.source,
        },
    )


# Connect signals — call this from dashboard/apps.py ready()
def connect_signals():
    """
    Explicit signal connection. Called from DashboardConfig.ready().
    Importing this module is sufficient because @receiver decorators
    register automatically, but this function documents the intent.
    """
    pass  # decorators above handle registration on import


# ── Admin registration ────────────────────────────────────────────────

# dashboard/admin.py — add this class:
#
# from django.contrib import admin
# from .audit import AuditLog
#
# @admin.register(AuditLog)
# class AuditLogAdmin(admin.ModelAdmin):
#     list_display  = ("ts", "action", "actor_username", "resource", "outcome", "ip_address")
#     list_filter   = ("action", "outcome")
#     search_fields = ("actor_username", "action", "resource", "request_id")
#     readonly_fields = ("ts", "actor", "actor_username", "action", "resource",
#                        "ip_address", "request_id", "detail", "outcome")
#     ordering = ("-ts",)
#
#     def has_add_permission(self, request):    return False
#     def has_change_permission(self, request, obj=None): return False
#     def has_delete_permission(self, request, obj=None): return False


# ── apps.py integration ───────────────────────────────────────────────

# dashboard/apps.py:
#
# from django.apps import AppConfig
#
# class DashboardConfig(AppConfig):
#     name = "dashboard"
#
#     def ready(self):
#         import dashboard.audit   # noqa — registers @receiver decorators


# ── PostgreSQL defence-in-depth trigger (optional, apply manually) ────
#
# CREATE OR REPLACE FUNCTION prevent_audit_mutation()
# RETURNS trigger AS $$
# BEGIN
#   RAISE EXCEPTION 'AuditLog rows are immutable';
# END;
# $$ LANGUAGE plpgsql;
#
# CREATE TRIGGER audit_immutable_update
#   BEFORE UPDATE ON dashboard_auditlog
#   FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
#
# CREATE TRIGGER audit_immutable_delete
#   BEFORE DELETE ON dashboard_auditlog
#   FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
#
# This makes immutability enforced at the database level, not just application level.
# Apply via a data migration (RunSQL with atomic=False).
