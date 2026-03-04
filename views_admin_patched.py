# dashboard/views_admin_patched.py
"""
Patched views_admin.py — adds audit logging to dep_scan and dep_plan.
Replace the function bodies in your existing views_admin.py with these.
The @staff_member_required and @require_GET/POST decorators stay unchanged.
"""
import json
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .audit import write as audit_write
from .dep_scanner import (
    ScanBusyError,
    ScanError,
    generate_upgrade_plan,
    scan_outdated,
)

logger = logging.getLogger("obsidian.dep_scanner")


@staff_member_required
@require_GET
def dep_scan(request):
    user_identifier = getattr(request.user, "username", "unknown")
    logger.info(
        "dep_scan_requested",
        extra={
            "username":   user_identifier,
            "ip":         request.META.get("REMOTE_ADDR"),
            "request_id": getattr(request, "request_id", ""),
        },
    )

    try:
        result = scan_outdated()

        audit_write(
            action="dep_scan",
            request=request,
            detail={
                "total_outdated": result["total_outdated"],
                "major_bumps":    result["major_bumps"],
            },
            outcome="ok",
        )

        return JsonResponse(result)

    except ScanBusyError as e:
        audit_write(action="dep_scan", request=request,
                    detail={"error": "busy"}, outcome="error")
        return JsonResponse({"error": str(e)}, status=423)

    except ScanError as e:
        logger.error("dep_scan_failed: %s", e)
        audit_write(action="dep_scan", request=request,
                    detail={"error": str(e)[:200]}, outcome="error")
        return JsonResponse({"error": str(e)}, status=500)

    except Exception:
        logger.exception("dep_scan_unexpected_error")
        audit_write(action="dep_scan", request=request,
                    detail={"error": "unexpected"}, outcome="error")
        return JsonResponse({"error": "Internal scan error — see server logs."}, status=500)


@staff_member_required
@require_POST
def dep_plan(request):
    user_identifier = getattr(request.user, "username", "unknown")
    logger.info("dep_plan_requested", extra={"username": user_identifier})

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    packages = body.get("packages")
    if not isinstance(packages, list):
        return JsonResponse(
            {"error": 'Request body must contain a "packages" list.'}, status=400
        )
    if len(packages) > 500:
        return JsonResponse({"error": "Package list too large (max 500)."}, status=400)

    try:
        plan = generate_upgrade_plan(packages)

        audit_write(
            action="dep_plan_generated",
            request=request,
            detail={
                "safe_count":    len(plan["safe_upgrades"]),
                "risky_count":   len(plan["risky_upgrades"]),
                "blocked_count": len(plan["blocked"]),
            },
            outcome="ok",
        )

        return JsonResponse(plan)

    except Exception:
        logger.exception("dep_plan_unexpected_error")
        audit_write(action="dep_plan_generated", request=request,
                    detail={"error": "unexpected"}, outcome="error")
        return JsonResponse({"error": "Plan generation failed — see server logs."}, status=500)
