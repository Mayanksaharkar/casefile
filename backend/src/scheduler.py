"""
scheduler.py — Cron-based audit scheduler for Casefile.

Reads .audit/schedules.yaml at startup and runs audits on schedule.
Sends Slack/email notifications when new issues are found vs the last run.
"""

import os
import uuid
import asyncio
import aiohttp
import smtplib
import yaml
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from .utils import make_logger

log = make_logger('scheduler')

# In-memory schedule registry {id -> schedule_dict}
_schedules: Dict[str, Dict] = {}
_tasks: Dict[str, asyncio.Task] = {}


def _parse_cron(cron_expr: str) -> Dict[str, Any]:
    """Parse a 5-field cron expression into a dict."""
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expr!r} (expected 5 fields)")
    keys = ['minute', 'hour', 'day', 'month', 'weekday']
    return dict(zip(keys, fields))


def _cron_matches(cron: Dict[str, Any], now: datetime) -> bool:
    """Check if a parsed cron expression matches the given datetime."""
    def _field_matches(field: str, value: int) -> bool:
        if field == '*':
            return True
        if '/' in field:
            parts = field.split('/')
            step = int(parts[1])
            start = 0 if parts[0] == '*' else int(parts[0])
            return (value - start) % step == 0
        if ',' in field:
            return value in [int(x) for x in field.split(',')]
        if '-' in field:
            lo, hi = field.split('-')
            return int(lo) <= value <= int(hi)
        return value == int(field)

    return (
        _field_matches(cron['minute'], now.minute)
        and _field_matches(cron['hour'], now.hour)
        and _field_matches(cron['day'], now.day)
        and _field_matches(cron['month'], now.month)
        and _field_matches(cron['weekday'], now.weekday())
    )


async def _send_slack_notification(webhook_url: str, message: str):
    """POST a message to a Slack incoming webhook."""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(webhook_url, json={'text': message})
    except Exception as e:
        log.error(f"Slack notification failed: {e}")


def _send_email_notification(to_address: str, subject: str, body: str):
    """Send a plain-text email via SMTP (configured via env vars)."""
    smtp_host = os.environ.get('SMTP_HOST', '')
    smtp_port = int(os.environ.get('SMTP_PORT', '587'))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASS', '')
    from_addr = os.environ.get('SMTP_FROM', smtp_user)

    if not smtp_host or not to_address:
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = from_addr
        msg['To'] = to_address
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        log.info(f"Email notification sent to {to_address}")
    except Exception as e:
        log.error(f"Email notification failed: {e}")


async def _notify(schedule: Dict, audit_state: Dict, new_issue_count: int, report_url: str):
    """Fire all configured notifications for a schedule."""
    notify = schedule.get('notify', {})
    name = schedule.get('name', 'scheduled-audit')
    target_url = schedule.get('targetUrl', '')

    if new_issue_count == 0:
        return  # Silent pass

    subject = f"[Casefile] {new_issue_count} new issue(s) found — {name}"
    body = (
        f"Casefile found {new_issue_count} new issue(s) during the scheduled audit "
        f"of {target_url}.\n\nReport: {report_url}\n\n"
        "Issues by severity:\n"
        f"  Critical: {audit_state.get('summary', {}).get('critical', 0)}\n"
        f"  High:     {audit_state.get('summary', {}).get('high', 0)}\n"
        f"  Medium:   {audit_state.get('summary', {}).get('medium', 0)}\n"
        f"  Low:      {audit_state.get('summary', {}).get('low', 0)}\n"
    )

    if notify.get('slack'):
        await _send_slack_notification(notify['slack'], f"🔔 {subject}\n{report_url}")

    if notify.get('email'):
        _send_email_notification(notify['email'], subject, body)


async def _run_scheduled_audit(schedule: Dict):
    """Execute a single scheduled audit and send notifications."""
    import src.orchestrator as audit_controller
    from .storage import disk_storage as storage
    from .regression import compare_runs

    target_url = schedule.get('targetUrl', '')
    repo_path = schedule.get('repoPath')
    budget = schedule.get('budget', 30)
    name = schedule.get('name', 'scheduled')
    frontend_origin = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:3000')

    log.info(f"Running scheduled audit '{name}' against {target_url}")

    # Find the most recent completed audit for this URL (for regression comparison)
    all_audits = storage.list_audits()
    previous = next(
        (a for a in all_audits
         if a.get('targetUrl') == target_url and a.get('status') == 'completed'),
        None
    )
    compare_id = previous.get('id') if previous else None

    audit_id = str(uuid.uuid4())
    try:
        await audit_controller.run_audit({
            'id': audit_id,
            'targetUrl': target_url,
            'repoPath': repo_path,
            'budget': budget,
            'safeMode': True,
            'compareAgainstId': compare_id,
        })

        state = storage.read_audit_state(audit_id) or {}
        regression = state.get('regression', {})

        # Count genuinely new issues (not recurring)
        new_count = regression.get('newCount', len(state.get('issues', [])))
        report_url = f"{frontend_origin}/data/audits/{audit_id}/report.html"

        await _notify(schedule, state, new_count, report_url)
        log.info(f"Scheduled audit '{name}' complete: {len(state.get('issues', []))} issue(s), {new_count} new")

    except Exception as e:
        log.error(f"Scheduled audit '{name}' failed: {e}")


async def _run_schedule_loop(schedule_id: str):
    """Main loop for a single schedule — ticks every minute."""
    schedule = _schedules.get(schedule_id)
    if not schedule:
        return

    try:
        cron = _parse_cron(schedule.get('cron', '0 2 * * *'))
    except ValueError as e:
        log.error(f"Invalid cron for schedule '{schedule.get('name')}': {e}")
        return

    log.info(f"Schedule '{schedule.get('name')}' started (cron: {schedule.get('cron')})")

    while schedule_id in _schedules:
        now = datetime.now(timezone.utc)
        if _cron_matches(cron, now):
            asyncio.create_task(_run_scheduled_audit(schedule))
            # Sleep 61s to avoid double-firing in the same minute
            await asyncio.sleep(61)
        else:
            # Sleep until the next minute boundary
            await asyncio.sleep(60 - now.second)


def load_schedules_from_yaml(repo_path: Optional[str] = None):
    """Load .audit/schedules.yaml from the repo path and register all schedules."""
    if not repo_path:
        return
    yaml_path = Path(repo_path) / '.audit' / 'schedules.yaml'
    if not yaml_path.exists():
        return

    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f) or {}
        for sched in data.get('schedules', []):
            if 'name' in sched and 'cron' in sched and 'targetUrl' in sched:
                add_schedule(sched)
        log.info(f"Loaded {len(data.get('schedules', []))} schedule(s) from {yaml_path}")
    except Exception as e:
        log.error(f"Failed to load schedules.yaml: {e}")


def add_schedule(schedule: Dict) -> str:
    """Register a new schedule and start its loop. Returns the schedule ID."""
    schedule_id = schedule.get('id') or str(uuid.uuid4())
    schedule['id'] = schedule_id
    _schedules[schedule_id] = schedule
    task = asyncio.create_task(_run_schedule_loop(schedule_id))
    _tasks[schedule_id] = task
    log.info(f"Schedule '{schedule.get('name')}' registered (id: {schedule_id})")
    return schedule_id


def remove_schedule(schedule_id: str) -> bool:
    """Stop and remove a schedule by ID."""
    if schedule_id not in _schedules:
        return False
    del _schedules[schedule_id]
    task = _tasks.pop(schedule_id, None)
    if task:
        task.cancel()
    return True


def list_schedules() -> List[Dict]:
    """Return all registered schedules."""
    return list(_schedules.values())


def get_schedule(schedule_id: str) -> Optional[Dict]:
    return _schedules.get(schedule_id)
