# dashboard/dep_scanner.py
"""
Safe dependency scanning — read-only, no package installation.

Security model:
  - subprocess always uses argument list (never shell=True)
  - sys.executable pins to the Django process Python (no PATH confusion)
  - Output is sanitised with regex before returning to client
  - threading.Lock prevents concurrent scan abuse
  - All operations logged via standard Django logger
  - NEVER calls pip install / upgrade / uninstall
"""
import json
import logging
import re
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger('obsidian.dep_scanner')

_scan_lock = threading.Lock()
_LOCK_TIMEOUT_SECS = 30

SEV_SCORE = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1, 'info': 0}

_REQ_LINE_RE = re.compile(
    r'^(?P<pkg>[A-Za-z0-9_\-\.]+)'
    r'(?P<spec>[=<>!~]+[A-Za-z0-9_\-\.\*,]+)?'
    r'\s*(?:#.*)?$'
)
_SAFE_PKG  = re.compile(r'[^\w.\-]')
_SAFE_VER  = re.compile(r'[^\w.\-]')


class ScanError(Exception):
    pass

class ScanBusyError(ScanError):
    pass


def _parse_requirements(req_path: Path) -> dict:
    if not req_path.exists():
        return {}
    pinned = {}
    for line in req_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('-'):
            continue
        m = _REQ_LINE_RE.match(line)
        if m:
            key  = m.group('pkg').lower().replace('-', '_')
            spec = m.group('spec') or ''
            pinned[key] = spec if spec.startswith('==') else None
    return pinned


def _is_major_bump(current: str, latest: str) -> bool:
    try:
        return int(current.split('.')[0]) < int(latest.split('.')[0])
    except (ValueError, IndexError):
        return False


def scan_outdated(requirements_path: str | None = None) -> dict:
    """
    Run pip list --outdated and return structured, sanitised results.
    Thread-safe. Read-only. Never installs anything.

    Raises ScanBusyError if another scan is running.
    Raises ScanError on subprocess failure.
    """
    acquired = _scan_lock.acquire(timeout=_LOCK_TIMEOUT_SECS)
    if not acquired:
        raise ScanBusyError('Another scan is already running.')

    try:
        logger.info('dep_scanner: starting outdated scan')

        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'list', '--outdated', '--format=json'],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # pip exits 1 when the list is empty — treat as success
        if result.returncode not in (0, 1):
            logger.error('pip list --outdated failed rc=%d stderr=%s',
                         result.returncode, result.stderr[:400])
            raise ScanError(
                f'pip list exited {result.returncode}: {result.stderr[:200]}'
            )

        try:
            raw = json.loads(result.stdout or '[]')
        except json.JSONDecodeError as exc:
            raise ScanError(f'Cannot parse pip output: {exc}') from exc

        req_path   = Path(requirements_path) if requirements_path else (
            Path(__file__).parent.parent / 'requirements.txt'
        )
        pinned_map = _parse_requirements(req_path)

        packages      = []
        major_count   = 0

        for pkg in raw:
            name    = _SAFE_PKG.sub('', pkg.get('name', ''))[:80]
            current = _SAFE_VER.sub('', pkg.get('version', ''))[:30]
            latest  = _SAFE_VER.sub('', pkg.get('latest_version', ''))[:30]
            key     = name.lower().replace('-', '_')

            is_major  = _is_major_bump(current, latest)
            is_pinned = key in pinned_map
            pin_spec  = pinned_map.get(key) or ''

            if is_major:
                major_count += 1

            packages.append({
                'name':          name,
                'current':       current,
                'latest':        latest,
                'latest_type':   pkg.get('latest_filetype', 'wheel'),
                'is_major_bump': is_major,
                'is_pinned':     is_pinned,
                'pinned_spec':   pin_spec,
            })

        # Major bumps first, then alphabetical
        packages.sort(key=lambda p: (not p['is_major_bump'], p['name'].lower()))

        logger.info('dep_scanner: done — %d outdated, %d major bumps',
                    len(packages), major_count)

        return {
            'packages':           packages,
            'total_outdated':     len(packages),
            'major_bumps':        major_count,
            'requirements_found': req_path.exists(),
            'scan_path':          str(req_path),
        }

    finally:
        _scan_lock.release()


def generate_upgrade_plan(packages: list) -> dict:
    """
    Classify packages into safe / risky / blocked upgrade groups.
    DRY-RUN ONLY. Never executes any install.
    """
    safe, risky, blocked, warnings = [], [], [], []

    for pkg in packages:
        entry = {
            'name': pkg['name'],
            'from': pkg['current'],
            'to':   pkg['latest'],
        }

        if pkg.get('is_pinned') and pkg.get('pinned_spec'):
            blocked.append({**entry, 'reason': f"pinned {pkg['pinned_spec']} in requirements.txt"})
            warnings.append(
                f"{pkg['name']}: requires manual update in requirements.txt (currently {pkg['pinned_spec']})"
            )
        elif pkg.get('is_major_bump'):
            risky.append({
                **entry,
                'warning': f"Major version {pkg['current']} → {pkg['latest']} — review changelog."
            })
            warnings.append(
                f"MAJOR: {pkg['name']} {pkg['current']} → {pkg['latest']}"
            )
        else:
            safe.append(entry)

    safe_specs = ' '.join(f"{p['name']}=={p['to']}" for p in safe)
    safe_cmd   = f"pip install {safe_specs}" if safe_specs else '# nothing to upgrade safely'

    return {
        'safe_upgrades':    safe,
        'risky_upgrades':   risky,
        'blocked':          blocked,
        'warnings':         warnings,
        'safe_install_cmd': safe_cmd,
        'total_changes':    len(safe) + len(risky),
        'recommendation': (
            'Apply safe upgrades in staging first. '
            'Review changelogs for every major bump. '
            'Do not run pip install from a production server via this UI.'
        ),
    }
