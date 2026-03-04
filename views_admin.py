# dashboard/views_admin.py
"""
Admin-only views for the dependency scan UI.

All views require:
  - is_staff=True (checked via @staff_member_required)
  - GET only for scan trigger (avoids CSRF bypass via direct URL)
  - POST with CSRF token for plan generation

These views are intentionally separated from views.py to make
auditing easier and to avoid accidental exposure.

Add to dashboard/urls.py:
    from . import views_admin
    path('admin/deps/scan/',  views_admin.dep_scan,       name='admin-dep-scan'),
    path('admin/deps/plan/',  views_admin.dep_plan,       name='admin-dep-plan'),
    path('admin/deps/',       views_admin.dep_index,      name='admin-dep-index'),
"""
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .dep_scanner import (
    ScanBusyError,
    ScanError,
    generate_upgrade_plan,
    scan_outdated,
)

logger = logging.getLogger('obsidian.dep_scanner')


@staff_member_required
@require_GET
def dep_scan(request):
    """
    Trigger a pip list --outdated scan and return JSON results.

    Staff-only. GET only. No write operations.

    Response shape:
        200  → { packages, total_outdated, major_bumps, requirements_found, scan_path }
        423  → { error: "busy" }
        500  → { error: "..." }
    """
    user_identifier = getattr(request.user, 'username', 'unknown')
    logger.info('Dependency scan requested by %s from %s',
                user_identifier,
                request.META.get('REMOTE_ADDR', 'unknown'))

    try:
        result = scan_outdated()
        return JsonResponse(result)

    except ScanBusyError as e:
        return JsonResponse({'error': str(e)}, status=423)

    except ScanError as e:
        logger.error('Dependency scan failed: %s', e)
        return JsonResponse({'error': str(e)}, status=500)

    except Exception as e:
        logger.exception('Unexpected error in dep_scan view')
        return JsonResponse({'error': 'Internal scan error — see server logs.'}, status=500)


@staff_member_required
@require_POST
def dep_plan(request):
    """
    Generate an upgrade plan (dry-run) from a previously-obtained scan result.
    Client must POST the packages list from a prior /admin/deps/scan/ call.

    This view never runs pip — it only classifies the provided package list.

    Request body (JSON):
        { "packages": [ {...}, ... ] }

    Response shape:
        200  → { safe_upgrades, risky_upgrades, blocked, warnings, recommendation, ... }
        400  → { error: "..." }
        500  → { error: "..." }
    """
    import json

    user_identifier = getattr(request.user, 'username', 'unknown')
    logger.info('Upgrade plan requested by %s', user_identifier)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    packages = body.get('packages')
    if not isinstance(packages, list):
        return JsonResponse(
            {'error': 'Request body must contain a "packages" list.'}, status=400
        )

    if len(packages) > 500:
        return JsonResponse({'error': 'Package list too large (max 500).'}, status=400)

    try:
        plan = generate_upgrade_plan(packages)
        return JsonResponse(plan)

    except Exception as e:
        logger.exception('Unexpected error in dep_plan view')
        return JsonResponse({'error': 'Plan generation failed — see server logs.'}, status=500)


@staff_member_required
@require_GET
def dep_index(request):
    """
    Render the dependency management admin panel.
    Returns the dashboard shell — the panel is loaded client-side
    after navigation to the 'admin/deps' section.
    """
    # The actual panel renders within the SPA shell.
    # This endpoint just confirms the user is staff before the
    # JS panel makes its /admin/deps/scan/ call.
    return JsonResponse({'ready': True, 'note': 'Use scan/ endpoint to trigger a scan.'})
