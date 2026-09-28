"""
webhooks.py — CI/CD webhook receiver for Casefile.

Handles GitHub PR webhooks to trigger automatic audits on pull requests.
"""

import os
import hmac
import hashlib
import asyncio
import aiohttp
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from ..utils import make_logger
import src.orchestrator as audit_controller

log = make_logger('webhooks')
router = APIRouter()

GITHUB_API = 'https://api.github.com'


def _verify_github_signature(body: bytes, signature_header: str) -> bool:
    """Verify the X-Hub-Signature-256 HMAC signature from GitHub."""
    secret = os.environ.get('GITHUB_WEBHOOK_SECRET', '')
    if not secret:
        log.warning('GITHUB_WEBHOOK_SECRET not set — skipping signature verification')
        return True
    if not signature_header or not signature_header.startswith('sha256='):
        return False
    expected = 'sha256=' + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


async def _wait_for_preview(url: str, timeout_seconds: int = 300, interval: int = 10) -> bool:
    """Poll a preview URL until it returns 200 or timeout is reached."""
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() < deadline:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status < 400:
                        return True
            except Exception:
                pass
            await asyncio.sleep(interval)
    return False


async def _set_commit_status(
    repo_full_name: str, sha: str, state: str, description: str, target_url: str = ''
):
    """Set a GitHub commit status via the Checks API."""
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        log.warning('GITHUB_TOKEN not set — skipping commit status update')
        return
    url = f"{GITHUB_API}/repos/{repo_full_name}/statuses/{sha}"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    payload = {
        'state': state,               # pending | success | failure | error
        'description': description[:140],
        'context': 'casefile/audit',
    }
    if target_url:
        payload['target_url'] = target_url
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(url, json=payload, headers=headers)
    except Exception as e:
        log.error(f"Failed to set commit status: {e}")


async def _post_pr_comment(repo_full_name: str, pr_number: int, body: str):
    """Post a comment on a GitHub pull request."""
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        return
    url = f"{GITHUB_API}/repos/{repo_full_name}/issues/{pr_number}/comments"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={'body': body}, headers=headers)
    except Exception as e:
        log.error(f"Failed to post PR comment: {e}")


def _build_pr_comment(audit_state: dict, report_url: str) -> str:
    """Build a markdown PR comment summarising the audit results."""
    summary = audit_state.get('summary', {})
    total = summary.get('total', 0)
    critical = summary.get('critical', 0)
    high = summary.get('high', 0)
    medium = summary.get('medium', 0)
    low = summary.get('low', 0)
    pages = audit_state.get('progress', {}).get('pagesDiscovered', 0)

    if total == 0:
        verdict = '✅ **Casefile: No issues found**'
        verdict_detail = f'Audited {pages} page(s) — all clean.'
    else:
        verdict = f'❌ **Casefile: {total} issue(s) found**'
        verdict_detail = (
            f"| Severity | Count |\n|---|---|\n"
            f"| 🔴 Critical | {critical} |\n"
            f"| 🟠 High | {high} |\n"
            f"| 🟡 Medium | {medium} |\n"
            f"| 🟢 Low | {low} |\n"
        )

    issues = audit_state.get('issues', [])
    rows = []
    for issue in issues[:10]:
        sev = issue.get('severity', 'low').upper()
        cat = issue.get('category', '')
        title = issue.get('title', 'Untitled')
        route = issue.get('route', '')
        rows.append(f"| {sev} | {cat} | {title} | `{route}` |")

    issue_table = ''
    if rows:
        issue_table = (
            "\n\n**Top issues:**\n\n"
            "| Severity | Category | Title | Route |\n"
            "|---|---|---|---|\n"
            + '\n'.join(rows)
        )
        if len(issues) > 10:
            issue_table += f"\n\n_...and {len(issues) - 10} more. See full report._"

    return (
        f"{verdict}\n\n"
        f"{verdict_detail}"
        f"{issue_table}\n\n"
        f"[📄 View full Casefile report]({report_url})\n\n"
        f"<sub>Generated by [Casefile](https://github.com/casefile/casefile) — adaptive web auditor</sub>"
    )


async def _run_pr_audit(
    target_url: str,
    repo_full_name: str,
    pr_number: int,
    sha: str,
    repo_path: Optional[str],
    frontend_origin: str,
):
    """Background task: wait for preview, run audit, post results to GitHub."""
    audit_id = None
    try:
        # Set pending status immediately
        await _set_commit_status(repo_full_name, sha, 'pending', 'Casefile audit running...')

        # Wait for the preview URL to be live
        log.info(f"Waiting for preview URL to be ready: {target_url}")
        ready = await _wait_for_preview(target_url)
        if not ready:
            await _set_commit_status(
                repo_full_name, sha, 'error',
                'Preview URL did not become available within 5 minutes.'
            )
            return

        # Run the audit
        import uuid
        audit_id = str(uuid.uuid4())
        audit_kwargs = {
            'id': audit_id,
            'targetUrl': target_url,
            'repoPath': repo_path,
            'budget': int(os.environ.get('CI_AUDIT_BUDGET', '30')),
            'safeMode': True,
        }
        log.info(f"Starting CI audit {audit_id} for PR #{pr_number}")
        await audit_controller.run_audit(audit_kwargs)

        # Read the completed state
        from src.storage import disk_storage as storage
        state = storage.read_audit_state(audit_id) or {}

        report_url = f"{frontend_origin}/data/audits/{audit_id}/report.html"
        total_issues = len(state.get('issues', []))


        critical_or_high = [i for i in state.get('issues', []) if i.get('severity') in ('critical', 'high')]
        total_issues = len(state.get('issues', []))
        
        gate_threshold_hit = len(critical_or_high) > 0
        
        if not gate_threshold_hit:
            await _set_commit_status(repo_full_name, sha, 'success', 'Casefile: Checks passed (No high/critical issues)', report_url)
        else:
            await _set_commit_status(
                repo_full_name, sha, 'failure',
                f"Casefile: {len(critical_or_high)} Critical/High issue(s) found", report_url
            )
            comment = _build_pr_comment(state, report_url)
            await _post_pr_comment(repo_full_name, pr_number, comment)


        log.info(f"CI audit {audit_id} complete: {total_issues} issue(s)")

    except Exception as e:
        log.error(f"CI audit failed: {e}")
        if repo_full_name and sha:
            await _set_commit_status(repo_full_name, sha, 'error', f'Casefile audit error: {str(e)[:100]}')


@router.post('/github')
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive GitHub webhook events (pull_request: opened/synchronize).
    Verifies the HMAC signature, extracts PR metadata, and triggers an
    async audit against the PR's preview URL.
    """
    body = await request.body()
    signature = request.headers.get('X-Hub-Signature-256', '')

    if not _verify_github_signature(body, signature):
        raise HTTPException(status_code=401, detail='Invalid webhook signature')

    event = request.headers.get('X-GitHub-Event', '')
    if event not in ('pull_request',):
        return JSONResponse({'ignored': True, 'event': event})

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON payload')

    action = payload.get('action', '')
    if action not in ('opened', 'synchronize', 'reopened'):
        return JSONResponse({'ignored': True, 'action': action})

    pr = payload.get('pull_request', {})
    sha = pr.get('head', {}).get('sha', '')
    pr_number = pr.get('number')
    repo = payload.get('repository', {})
    repo_full_name = repo.get('full_name', '')

    # Determine preview URL
    # Priority: PR label "preview-url=...", then env pattern, then PR body
    preview_url = None
    pattern = os.environ.get('PREVIEW_URL_PATTERN', '')
    branch = pr.get('head', {}).get('ref', '').replace('/', '-')

    if pattern:
        preview_url = pattern.replace('{branch}', branch).replace('{sha}', sha[:8])

    if not preview_url:
        # Try to find it in PR body e.g. "Preview: https://..."
        body_text = pr.get('body', '') or ''
        match = re.search(r'preview[:\s]+\**(https?://[^\s*]+)', body_text, re.IGNORECASE)
        if match:
            preview_url = match.group(1).strip()

    if not preview_url:
        return JSONResponse({
            'status': 'skipped',
            'reason': 'No preview URL found. Set PREVIEW_URL_PATTERN env var or include "Preview: <url>" in PR body.',
        })

    repo_path = os.environ.get('CI_REPO_PATH', '')
    frontend_origin = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:3000')

    background_tasks.add_task(
        _run_pr_audit,
        target_url=preview_url,
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        sha=sha,
        repo_path=repo_path or None,
        frontend_origin=frontend_origin,
    )

    log.info(f"GitHub PR #{pr_number} webhook received — audit scheduled for {preview_url}")
    return JSONResponse({'status': 'audit_scheduled', 'previewUrl': preview_url})


# Need re for URL extraction in PR body
import re
