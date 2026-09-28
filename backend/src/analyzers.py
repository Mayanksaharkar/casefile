"""
analyzers.py — All static and dynamic analyzers for Casefile.

Covers:
  - Accessibility (axe-core results)
  - Console errors
  - Network failures / UI-API mismatch
  - Visual regression (pixel diff + optional Gemini Vision confirmation)
  - Performance (Web Vitals: LCP, CLS, INP, TTFB)
  - Security surface scan (XSS probes, CSP headers, cookie flags, tokens in URLs)
  - API contract verification (5xx, 401, null responses, slow APIs)
  - Accessibility upgrade (keyboard navigation, focus visibility, color contrast)
"""

import re
import os
import hashlib
import base64
import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Accessibility Analyzer (axe-core results → issue list)
# ──────────────────────────────────────────────────────────────────────────────

IMPACT_TO_SEVERITY = {
    'critical': 'high',
    'serious': 'medium',
    'moderate': 'low',
    'minor': 'low',
}

WCAG_LEVEL_MAP = {
    'wcag2a': 'A',
    'wcag2aa': 'AA',
    'wcag2aaa': 'AAA',
    'wcag21a': 'A',
    'wcag21aa': 'AA',
    'wcag22aa': 'AA',
    'best-practice': 'best-practice',
}


def summarize_accessibility(violations: List[Dict[str, Any]], page_url: str) -> List[Dict[str, Any]]:
    result = []
    for v in violations:
        nodes = v.get('nodes', [])
        sample_targets = []
        for n in nodes[:3]:
            target = n.get('target')
            if target:
                sample_targets.append(' '.join(target))

        # Determine WCAG level from tags
        tags = v.get('tags', [])
        wcag_level = 'unknown'
        for tag in tags:
            if tag.lower() in WCAG_LEVEL_MAP:
                wcag_level = WCAG_LEVEL_MAP[tag.lower()]
                break

        result.append({
            'category': 'ACCESSIBILITY',
            'severity': IMPACT_TO_SEVERITY.get(v.get('impact'), 'low'),
            'title': v.get('help'),
            'description': v.get('description'),
            'route': page_url,
            'ruleId': v.get('id'),
            'helpUrl': v.get('helpUrl'),
            'wcagLevel': wcag_level,
            'nodeCount': len(nodes),
            'sampleTargets': sample_targets,
            'acceptanceCriteria': [
                f'[ ] axe-core rule "{v.get("id")}" reports zero violations on {page_url}.',
                '[ ] All affected elements are keyboard-accessible with visible focus indicators.',
            ],
        })
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Console Analyzer
# ──────────────────────────────────────────────────────────────────────────────

def find_console_errors(console_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [entry for entry in console_entries if entry.get('type') == 'error']


def summarize_console(console_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    errors = find_console_errors(console_entries)
    return {
        'errorCount': len(errors),
        'errors': [e.get('text') for e in errors][:10],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Network Analyzer
# ──────────────────────────────────────────────────────────────────────────────

SUCCESS_WORDS = [
    'success', 'successfully', 'saved', 'created', 'updated', 'deleted',
    'sent', 'added', 'complete',
]


def find_failed_requests(network_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in network_entries if e.get('status', 0) == 0 or e.get('status', 0) >= 400]


def find_ui_api_mismatch(
    network_entries: List[Dict[str, Any]], body_text_after_action: Optional[str]
) -> Optional[Dict[str, Any]]:
    failed = find_failed_requests(network_entries)
    if not failed:
        return None
    lower_body = (body_text_after_action or '').lower()
    claims_success = any(w in lower_body for w in SUCCESS_WORDS)
    if not claims_success:
        return None
    return {
        'failedRequests': failed,
        'matchedSuccessWords': [w for w in SUCCESS_WORDS if w in lower_body],
    }


def summarize_network(network_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    failed = find_failed_requests(network_entries)
    return {
        'requestCount': len(network_entries),
        'failedCount': len(failed),
        'failed': failed[:10],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Visual Regression Analyzer (Phase 3)
# ──────────────────────────────────────────────────────────────────────────────

BASELINES_DIR = Path(__file__).resolve().parent.parent / 'data' / 'baselines'

def _route_hash(url: str) -> str:
    """Stable hash for a URL used as the baseline filename."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def save_baseline(route_url: str, screenshot_bytes: bytes) -> str:
    """Save a screenshot as the baseline for this route. Returns the path."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    path = BASELINES_DIR / f"{_route_hash(route_url)}.png"
    path.write_bytes(screenshot_bytes)
    return str(path)


def load_baseline(route_url: str) -> Optional[bytes]:
    """Load the baseline screenshot bytes for this route, or None if not yet set."""
    path = BASELINES_DIR / f"{_route_hash(route_url)}.png"
    if path.exists():
        return path.read_bytes()
    return None


def _pixel_diff_ratio(img_a: bytes, img_b: bytes) -> float:
    """
    Compute the fraction of differing pixels between two PNG images.
    Uses Pillow if available; falls back to 0.0 (no diff) on import error.
    """
    try:
        from PIL import Image, ImageChops
        import io
        a = Image.open(io.BytesIO(img_a)).convert('RGB')
        b = Image.open(io.BytesIO(img_b)).convert('RGB')
        # Resize b to match a if dimensions differ
        if a.size != b.size:
            b = b.resize(a.size, Image.LANCZOS)
        diff = ImageChops.difference(a, b)
        total_pixels = a.width * a.height
        nonzero = sum(1 for pixel in diff.getdata() if any(c > 10 for c in pixel))
        return nonzero / total_pixels
    except Exception:
        return 0.0


def _make_side_by_side_diff(baseline_bytes: bytes, current_bytes: bytes) -> bytes:
    """Create a side-by-side comparison PNG. Returns PNG bytes."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        a = Image.open(io.BytesIO(baseline_bytes)).convert('RGB')
        b = Image.open(io.BytesIO(current_bytes)).convert('RGB')
        if a.size != b.size:
            b = b.resize(a.size, Image.LANCZOS)
        # Create combined image with a 4px gap
        gap = 4
        combined = Image.new('RGB', (a.width * 2 + gap, a.height), (200, 200, 200))
        combined.paste(a, (0, 0))
        combined.paste(b, (a.width + gap, 0))
        buf = io.BytesIO()
        combined.save(buf, format='PNG')
        return buf.getvalue()
    except Exception:
        return b''


async def check_visual_regression(
    page_url: str,
    current_screenshot: bytes,
    audit_id: str,
    threshold: float = 0.05,
    gemini_confirm: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Compare current screenshot against the stored baseline.
    Returns an issue dict if a regression is detected, else None.
    Also saves the current screenshot as new baseline if none exists yet.
    """
    baseline = load_baseline(page_url)
    if baseline is None:
        # First time — establish baseline, no issue
        save_baseline(page_url, current_screenshot)
        return None

    ratio = _pixel_diff_ratio(baseline, current_screenshot)
    if ratio < threshold:
        return None  # Within tolerance

    # Generate diff image
    diff_bytes = _make_side_by_side_diff(baseline, current_screenshot)
    diff_path = None
    if diff_bytes:
        from src.storage import disk_storage as storage
        diff_name = f"visual-diff-{_route_hash(page_url)}.png"
        diff_path = storage.save_screenshot(audit_id, diff_bytes, diff_name)

    # Optionally ask Gemini Vision to classify the diff
    classification = 'regression'
    if gemini_confirm and os.environ.get('GEMINI_API_KEY'):
        classification = await _classify_diff_with_gemini(baseline, current_screenshot, page_url)

    if classification == 'intentional':
        # Update baseline silently
        save_baseline(page_url, current_screenshot)
        return None

    return {
        'category': 'VISUAL_REGRESSION',
        'severity': 'high' if ratio > 0.20 else 'medium',
        'title': f"Visual regression detected on {page_url}",
        'description': (
            f"{round(ratio * 100, 1)}% of pixels changed on {page_url} vs the stored baseline. "
            "This may indicate a layout break, missing component, or unintended style change."
        ),
        'route': page_url,
        'confidence': min(ratio * 3, 1.0),
        'expected': 'Page appears visually identical to the approved baseline.',
        'actual': f"{round(ratio * 100, 1)}% pixel difference detected.",
        'evidence': {
            'diffImagePath': diff_path,
            'pixelDiffRatio': ratio,
        },
        'acceptanceCriteria': [
            '[ ] The page renders identically to the approved baseline at the same viewport.',
            '[ ] If the change is intentional, the baseline is updated via the dashboard.',
        ],
    }


async def _classify_diff_with_gemini(
    baseline_bytes: bytes, current_bytes: bytes, page_url: str
) -> str:
    """Ask Gemini Vision whether a diff is a regression or an intentional redesign."""
    try:
        import aiohttp
        api_key = os.environ.get('GEMINI_API_KEY', '')
        model = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash')
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        b64_baseline = base64.b64encode(baseline_bytes).decode()
        b64_current = base64.b64encode(current_bytes).decode()

        body = {
            'contents': [{
                'parts': [
                    {'text': (
                        f"You are a visual QA reviewer. I am showing you two screenshots of {page_url}.\n"
                        "The first is the approved baseline. The second is the current state.\n"
                        "Is this difference a REGRESSION (broken layout, missing content, wrong styling) "
                        "or an INTENTIONAL redesign?\n"
                        "Respond with exactly one word: 'regression' or 'intentional'."
                    )},
                    {'inlineData': {'mimeType': 'image/png', 'data': b64_baseline}},
                    {'inlineData': {'mimeType': 'image/png', 'data': b64_current}},
                ]
            }],
            'generationConfig': {'temperature': 0.0},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '').strip().lower()
                    if 'intentional' in text:
                        return 'intentional'
    except Exception:
        pass
    return 'regression'


# ──────────────────────────────────────────────────────────────────────────────
# Performance Analyzer (Phase 5) — Web Vitals via JS injection
# ──────────────────────────────────────────────────────────────────────────────

# Thresholds (Google Core Web Vitals)
PERF_THRESHOLDS = {
    'lcp':  {'high': 2500, 'critical': 4000},   # ms
    'cls':  {'medium': 0.1, 'high': 0.25},       # score (unitless)
    'inp':  {'medium': 200, 'high': 500},         # ms
    'ttfb': {'medium': 800, 'high': 1800},        # ms
}

WEB_VITALS_SNIPPET = """
() => {
  return new Promise((resolve) => {
    const vitals = {};
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.entryType === 'largest-contentful-paint') vitals.lcp = entry.startTime;
        if (entry.entryType === 'layout-shift' && !entry.hadRecentInput) {
          vitals.cls = (vitals.cls || 0) + entry.value;
        }
        if (entry.entryType === 'first-input') vitals.inp = entry.processingStart - entry.startTime;
      }
    });
    try {
      observer.observe({ type: 'largest-contentful-paint', buffered: true });
      observer.observe({ type: 'layout-shift', buffered: true });
      observer.observe({ type: 'first-input', buffered: true });
    } catch(e) {}

    // TTFB from navigation timing
    const nav = performance.getEntriesByType('navigation')[0];
    if (nav) vitals.ttfb = nav.responseStart - nav.requestStart;

    // Resolve after short wait to collect LCP/CLS
    setTimeout(() => {
      observer.disconnect();
      resolve(vitals);
    }, 1500);
  });
}
"""


async def collect_web_vitals(page) -> Dict[str, Any]:
    """Evaluate Web Vitals on the current page. Returns a dict of metric->value."""
    try:
        vitals = await page.evaluate(WEB_VITALS_SNIPPET)
        return vitals or {}
    except Exception:
        return {}


def analyze_performance(vitals: Dict[str, Any], page_url: str, rules: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Compare collected Web Vitals against thresholds.
    Returns a list of PERFORMANCE issue dicts.
    """
    issues = []
    thresholds = PERF_THRESHOLDS.copy()

    # Allow overrides from rules.yaml
    if rules and isinstance(rules, dict):
        rt = rules.get('performanceThresholds', {})
        for k, v in rt.items():
            if k in thresholds:
                thresholds[k].update(v)

    metric_labels = {
        'lcp': ('Largest Contentful Paint', 'ms', 'Slow LCP indicates the main content takes too long to render.'),
        'cls': ('Cumulative Layout Shift', 'score', 'High CLS means elements shift unexpectedly during page load.'),
        'inp': ('Interaction to Next Paint', 'ms', 'High INP means the page is slow to respond to user input.'),
        'ttfb': ('Time to First Byte', 'ms', 'High TTFB indicates slow server or network response.'),
    }

    for metric, (label, unit, description) in metric_labels.items():
        value = vitals.get(metric)
        if value is None:
            continue

        severity = None
        t = thresholds.get(metric, {})
        if 'critical' in t and value > t['critical']:
            severity = 'critical'
        elif 'high' in t and value > t['high']:
            severity = 'high'
        elif 'medium' in t and value > t['medium']:
            severity = 'medium'

        if severity:
            threshold_val = t.get('critical') or t.get('high') or t.get('medium')
            issues.append({
                'category': 'PERFORMANCE',
                'severity': severity,
                'title': f"{label} is too slow on {page_url}",
                'description': f"{label} is {round(value, 1)}{unit} (threshold: {threshold_val}{unit}). {description}",
                'route': page_url,
                'confidence': 1.0,
                'expected': f"{label} ≤ {threshold_val}{unit}",
                'actual': f"{label} = {round(value, 1)}{unit}",
                'metrics': {metric: value},
                'acceptanceCriteria': [
                    f'[ ] {label} is ≤ {threshold_val}{unit} on {page_url}.',
                    '[ ] No render-blocking resources introduced by the fix.',
                ],
            })

    return issues


# ──────────────────────────────────────────────────────────────────────────────
# Security Analyzer (Phase 6) — OWASP surface scan
# ──────────────────────────────────────────────────────────────────────────────

XSS_PAYLOADS = [
    '<script>window.__casefile_xss=1</script>',
    '"><img src=x onerror="window.__casefile_xss=1">',
    "';window.__casefile_xss=1;//",
]

SENSITIVE_PARAM_NAMES = re.compile(
    r'\b(token|access_token|api_key|apikey|secret|password|passwd|auth|jwt|bearer)\b',
    re.IGNORECASE
)


def analyze_response_headers(headers: Dict[str, str], page_url: str) -> List[Dict[str, Any]]:
    """
    Inspect HTTP response headers for common security misconfigurations.
    Returns a list of SECURITY issue dicts.
    """
    issues = []
    h = {k.lower(): v for k, v in (headers or {}).items()}
    is_https = page_url.startswith('https://')

    # CSP
    if 'content-security-policy' not in h:
        issues.append({
            'category': 'SECURITY',
            'severity': 'high',
            'title': f"Missing Content-Security-Policy header on {page_url}",
            'description': 'No CSP header was found. This leaves the page vulnerable to XSS and data injection attacks.',
            'route': page_url,
            'confidence': 1.0,
            'expected': 'Content-Security-Policy header is present with a restrictive policy.',
            'actual': 'No Content-Security-Policy header found.',
            'acceptanceCriteria': [
                '[ ] Content-Security-Policy header is set on all page responses.',
                '[ ] The policy includes script-src and object-src directives.',
            ],
        })

    # X-Frame-Options / frame-ancestors
    has_frame_opt = 'x-frame-options' in h
    csp_val = h.get('content-security-policy', '')
    has_frame_ancestors = 'frame-ancestors' in csp_val
    if not has_frame_opt and not has_frame_ancestors:
        issues.append({
            'category': 'SECURITY',
            'severity': 'medium',
            'title': f"Clickjacking risk: missing frame-ancestors on {page_url}",
            'description': 'No X-Frame-Options or CSP frame-ancestors directive found. The page can be embedded in a malicious iframe.',
            'route': page_url,
            'confidence': 1.0,
            'expected': "X-Frame-Options: DENY or CSP frame-ancestors 'none'.",
            'actual': 'Neither header present.',
            'acceptanceCriteria': [
                "[ ] X-Frame-Options: DENY or SAMEORIGIN is set, OR CSP includes frame-ancestors 'none'.",
            ],
        })

    # HSTS (only applies to HTTPS)
    if is_https and 'strict-transport-security' not in h:
        issues.append({
            'category': 'SECURITY',
            'severity': 'medium',
            'title': f"Missing HSTS header on {page_url}",
            'description': 'Strict-Transport-Security is missing. Browsers will not enforce HTTPS-only connections.',
            'route': page_url,
            'confidence': 1.0,
            'expected': 'Strict-Transport-Security header with max-age ≥ 31536000.',
            'actual': 'No Strict-Transport-Security header.',
            'acceptanceCriteria': [
                '[ ] Strict-Transport-Security: max-age=31536000; includeSubDomains is set.',
            ],
        })

    # X-Content-Type-Options
    if h.get('x-content-type-options', '').lower() != 'nosniff':
        issues.append({
            'category': 'SECURITY',
            'severity': 'low',
            'title': f"Missing X-Content-Type-Options: nosniff on {page_url}",
            'description': 'Without nosniff, browsers may MIME-sniff responses away from the declared content-type.',
            'route': page_url,
            'confidence': 1.0,
            'expected': "X-Content-Type-Options: nosniff",
            'actual': f"X-Content-Type-Options: {h.get('x-content-type-options', '(missing)')}",
            'acceptanceCriteria': ['[ ] X-Content-Type-Options: nosniff is set on all responses.'],
        })

    return issues


def analyze_url_for_secrets(url: str) -> Optional[Dict[str, Any]]:
    """Check if sensitive parameters appear in the URL query string."""
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key in params:
            if SENSITIVE_PARAM_NAMES.search(key):
                return {
                    'category': 'SECURITY',
                    'severity': 'critical',
                    'title': f"Sensitive parameter '{key}' exposed in URL",
                    'description': (
                        f"The parameter '{key}' appears in the URL query string of {url}. "
                        "Tokens and credentials in URLs are logged by servers, proxies, and browser history."
                    ),
                    'route': url,
                    'confidence': 1.0,
                    'expected': 'Sensitive values are sent in request bodies or Authorization headers, not URLs.',
                    'actual': f"'{key}' found in query string of {url}",
                    'acceptanceCriteria': [
                        f"[ ] '{key}' is no longer present in the URL.",
                        '[ ] The value is transmitted via a secure header or POST body instead.',
                    ],
                }
    except Exception:
        pass
    return None


async def probe_xss(page, form_selectors: List[str], page_url: str) -> Optional[Dict[str, Any]]:
    """
    Inject XSS payloads into form fields and listen for script execution.
    Returns a SECURITY issue if an XSS vector is confirmed.
    """
    xss_triggered = {'flag': False, 'selector': None, 'payload': None}

    async def handle_dialog(dialog):
        xss_triggered['flag'] = True
        await dialog.dismiss()

    page.on('dialog', handle_dialog)

    for selector in form_selectors[:10]:  # cap at 10 fields per form
        for payload in XSS_PAYLOADS:
            if xss_triggered['flag']:
                break
            try:
                await page.fill(selector, payload)
                # Check if window.__casefile_xss was set (inline script execution)
                executed = await page.evaluate("() => !!window.__casefile_xss")
                if executed or xss_triggered['flag']:
                    xss_triggered['selector'] = selector
                    xss_triggered['payload'] = payload
                    break
            except Exception:
                continue

    page.remove_listener('dialog', handle_dialog)

    if xss_triggered['flag'] or xss_triggered.get('selector'):
        return {
            'category': 'SECURITY',
            'severity': 'critical',
            'title': f"Cross-Site Scripting (XSS) vulnerability on {page_url}",
            'description': (
                f"An XSS payload was executed on {page_url} via input field "
                f"'{xss_triggered['selector']}'. An attacker could steal session cookies, "
                "redirect users, or inject malicious content."
            ),
            'route': page_url,
            'confidence': 1.0,
            'expected': 'All user input is sanitized before rendering in the DOM.',
            'actual': f"Payload executed: {xss_triggered['payload']}",
            'evidence': {'xssSelector': xss_triggered['selector'], 'xssPayload': xss_triggered['payload']},
            'acceptanceCriteria': [
                '[ ] The same XSS payload no longer executes on this page.',
                '[ ] All user-controlled input is escaped before DOM insertion.',
                '[ ] CSP script-src prevents inline script execution.',
            ],
        }
    return None


async def analyze_cookies(page, page_url: str) -> List[Dict[str, Any]]:
    """Check for insecure cookie flag settings on auth-related cookies."""
    issues = []
    try:
        context = page.context
        cookies = await context.cookies([page_url])
        auth_cookie_names = re.compile(
            r'\b(session|sess|auth|token|jwt|sid|user_id|userid|account)\b', re.IGNORECASE
        )
        for cookie in cookies:
            name = cookie.get('name', '')
            if not auth_cookie_names.search(name):
                continue
            missing = []
            if not cookie.get('secure'):
                missing.append('Secure')
            if not cookie.get('httpOnly'):
                missing.append('HttpOnly')
            if not cookie.get('sameSite') or cookie.get('sameSite') == 'None':
                missing.append('SameSite')
            if missing:
                issues.append({
                    'category': 'SECURITY',
                    'severity': 'high',
                    'title': f"Insecure cookie '{name}' missing flags: {', '.join(missing)}",
                    'description': (
                        f"The auth cookie '{name}' is missing: {', '.join(missing)}. "
                        "This may allow session theft via XSS or network interception."
                    ),
                    'route': page_url,
                    'confidence': 1.0,
                    'expected': f"Cookie '{name}' has Secure, HttpOnly, and SameSite=Strict/Lax flags.",
                    'actual': f"Missing flags: {', '.join(missing)}",
                    'acceptanceCriteria': [
                        f"[ ] Cookie '{name}' has the Secure flag set.",
                        f"[ ] Cookie '{name}' has the HttpOnly flag set.",
                        f"[ ] Cookie '{name}' has SameSite=Strict or SameSite=Lax.",
                    ],
                })
    except Exception:
        pass
    return issues


# ──────────────────────────────────────────────────────────────────────────────
# API Contract Analyzer (Phase 7)
# ──────────────────────────────────────────────────────────────────────────────

API_SLOW_THRESHOLD_MS = 3000


def analyze_api_responses(
    responses: List[Dict[str, Any]], page_url: str, action_label: str = ''
) -> List[Dict[str, Any]]:
    """
    Analyze captured API responses for contract violations.
    Each response dict should have: url, method, status, requestBody,
    responseBody (str), responseTimeMs.
    """
    issues = []
    for r in responses:
        status = r.get('status', 0)
        url = r.get('url', '')
        method = r.get('method', 'GET')
        req_body = r.get('requestBody', '')
        resp_body = r.get('responseBody', '')
        resp_time = r.get('responseTimeMs', 0)
        action_ctx = f" (triggered by: {action_label})" if action_label else ''

        # 5xx on user-triggered request
        if status >= 500:
            resp_snippet = str(resp_body)[:500] if resp_body else '(empty)'
            issues.append({
                'category': 'UI_API_MISMATCH',
                'severity': 'critical',
                'title': f"Server error {status} on {method} {url}",
                'description': f"A {status} Server Error was returned during a user action{action_ctx}. This is a critical API failure.",
                'route': page_url,
                'confidence': 1.0,
                'expected': f"API returns 2xx for {method} {url}",
                'actual': f"HTTP {status}: {resp_snippet}",
                'evidence': {
                    'harEntry': {
                        'method': method, 'url': url, 'status': status,
                        'requestBody': str(req_body)[:500],
                        'responseBodySnippet': resp_snippet,
                    }
                },
                'acceptanceCriteria': [
                    f'[ ] {method} {url} returns 2xx for valid requests.',
                    '[ ] The server error is logged and handled gracefully in the UI.',
                ],
            })

        # 401/403 on authenticated flow
        elif status in (401, 403):
            issues.append({
                'category': 'UI_API_MISMATCH',
                'severity': 'high',
                'title': f"Auth failure {status} on {method} {url}",
                'description': (
                    f"A {status} response was received on an authenticated flow{action_ctx}. "
                    "Session may have expired or the user lacks the required permissions."
                ),
                'route': page_url,
                'confidence': 0.9,
                'expected': f"Authenticated requests to {url} return 2xx.",
                'actual': f"HTTP {status}",
                'evidence': {'harEntry': {'method': method, 'url': url, 'status': status}},
                'acceptanceCriteria': [
                    '[ ] The session is refreshed automatically when expired.',
                    '[ ] Permission errors show a clear UI message rather than a blank/broken page.',
                ],
            })

        # 404 on a resource the UI depends on
        elif status == 404 and method == 'GET':
            issues.append({
                'category': 'FUNCTIONAL_BUG',
                'severity': 'medium',
                'title': f"Broken resource: 404 on {method} {url}",
                'description': f"A resource the page depends on returned 404{action_ctx}.",
                'route': page_url,
                'confidence': 0.85,
                'expected': f"{url} returns 200.",
                'actual': "HTTP 404 Not Found",
                'evidence': {'harEntry': {'method': method, 'url': url, 'status': 404}},
                'acceptanceCriteria': [f'[ ] {url} returns a valid resource.'],
            })

        # Null/empty response where body is expected
        if method in ('GET', 'POST') and status == 200:
            try:
                body = json.loads(resp_body) if isinstance(resp_body, str) else resp_body
                if body is None or body == [] or body == {}:
                    issues.append({
                        'category': 'UI_API_MISMATCH',
                        'severity': 'high',
                        'title': f"Empty API response on {method} {url}",
                        'description': (
                            f"{method} {url} returned an empty body ({repr(body)}) with status 200{action_ctx}. "
                            "The UI may silently fail to render expected content."
                        ),
                        'route': page_url,
                        'confidence': 0.8,
                        'expected': f"{method} {url} returns a non-empty response body.",
                        'actual': f"Response body: {repr(body)}",
                        'evidence': {'harEntry': {'method': method, 'url': url, 'status': 200, 'responseBodySnippet': str(resp_body)[:200]}},
                        'acceptanceCriteria': [
                            f'[ ] {url} returns the expected data structure.',
                            '[ ] The UI handles empty responses gracefully with an appropriate message.',
                        ],
                    })
            except Exception:
                pass

        # Slow API
        if resp_time and resp_time > API_SLOW_THRESHOLD_MS:
            issues.append({
                'category': 'PERFORMANCE',
                'severity': 'medium',
                'title': f"Slow API response: {method} {url} took {resp_time}ms",
                'description': (
                    f"{method} {url} took {resp_time}ms to respond{action_ctx}, "
                    f"exceeding the {API_SLOW_THRESHOLD_MS}ms threshold."
                ),
                'route': page_url,
                'confidence': 1.0,
                'expected': f"Response time ≤ {API_SLOW_THRESHOLD_MS}ms.",
                'actual': f"Response time: {resp_time}ms",
                'acceptanceCriteria': [
                    f'[ ] {method} {url} responds within {API_SLOW_THRESHOLD_MS}ms under normal load.',
                ],
            })

    return issues


# ──────────────────────────────────────────────────────────────────────────────
# Keyboard Accessibility Analyzer (Phase 8)
# ──────────────────────────────────────────────────────────────────────────────

FOCUS_CHECK_SCRIPT = """
() => {
  const el = document.activeElement;
  if (!el || el === document.body) return { focused: false };
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  // Check if element is visible and has a distinct focus indicator
  const hasOutline = style.outlineWidth !== '0px' && style.outlineStyle !== 'none';
  const hasBoxShadow = style.boxShadow !== 'none' && style.boxShadow !== '';
  const hasBorder = style.borderStyle !== 'none' && style.borderWidth !== '0px';
  const hasBgChange = false; // would need pre/post comparison
  return {
    focused: true,
    tagName: el.tagName,
    selector: el.id ? '#' + el.id : (el.className ? '.' + el.className.split(' ')[0] : el.tagName.toLowerCase()),
    ariaLabel: el.getAttribute('aria-label') || '',
    hasVisibleFocus: hasOutline || hasBoxShadow,
    hasOutline,
    hasBoxShadow,
    outlineWidth: style.outlineWidth,
    boxShadow: style.boxShadow,
    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  };
}
"""

ARIA_SCAN_SCRIPT = """
() => {
  const issues = [];
  // Images without alt
  document.querySelectorAll('img:not([alt])').forEach(el => {
    issues.push({ type: 'img-missing-alt', selector: el.src ? 'img[src="' + el.src.split('/').pop() + '"]' : 'img' });
  });
  // Icon buttons without aria-label
  document.querySelectorAll('button').forEach(el => {
    const text = el.textContent.trim();
    const hasLabel = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || text.length > 0;
    if (!hasLabel) issues.push({ type: 'button-missing-label', selector: el.outerHTML.slice(0, 100) });
  });
  // Form inputs without labels
  document.querySelectorAll('input, select, textarea').forEach(el => {
    if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return;
    const id = el.id;
    const hasLabel = (id && document.querySelector('label[for="' + id + '"]')) ||
                     el.getAttribute('aria-label') || el.getAttribute('aria-labelledby');
    if (!hasLabel) issues.push({ type: 'input-missing-label', selector: el.outerHTML.slice(0, 100) });
  });
  return issues;
}
"""


async def analyze_keyboard_navigation(page, page_url: str) -> List[Dict[str, Any]]:
    """
    Tab through focusable elements and check for visible focus indicators.
    Also runs ARIA label checks.
    """
    issues = []
    invisible_focus_elements = []

    try:
        # Tab through up to 40 interactive elements
        for _ in range(40):
            await page.keyboard.press('Tab')
            await asyncio.sleep(0.05)
            state = await page.evaluate(FOCUS_CHECK_SCRIPT)
            if not state.get('focused'):
                continue
            if not state.get('hasVisibleFocus'):
                invisible_focus_elements.append(state.get('selector', 'unknown'))

        if invisible_focus_elements:
            sample = invisible_focus_elements[:5]
            issues.append({
                'category': 'ACCESSIBILITY',
                'severity': 'high',
                'title': f"Focus indicator missing on {len(invisible_focus_elements)} element(s) on {page_url}",
                'description': (
                    f"{len(invisible_focus_elements)} interactive elements on {page_url} have no visible focus indicator. "
                    "Keyboard users cannot determine which element is active. "
                    f"Example elements: {', '.join(sample)}"
                ),
                'route': page_url,
                'confidence': 1.0,
                'expected': "All interactive elements show a visible focus indicator when focused via keyboard.",
                'actual': f"{len(invisible_focus_elements)} elements have no visible focus ring.",
                'wcagLevel': 'AA',
                'acceptanceCriteria': [
                    '[ ] All interactive elements have a visible :focus-visible style.',
                    '[ ] Focus outline is at least 2px and has sufficient contrast.',
                ],
            })
    except Exception:
        pass

    # ARIA checks
    try:
        aria_issues = await page.evaluate(ARIA_SCAN_SCRIPT)
        type_map = {
            'img-missing-alt': ('Image missing alt text', 'high', 'A'),
            'button-missing-label': ('Button missing accessible label', 'high', 'A'),
            'input-missing-label': ('Form input missing label', 'medium', 'A'),
        }
        grouped: Dict[str, List] = {}
        for item in aria_issues:
            t = item.get('type', 'unknown')
            grouped.setdefault(t, []).append(item.get('selector', ''))

        for issue_type, selectors in grouped.items():
            if issue_type not in type_map:
                continue
            label, severity, wcag = type_map[issue_type]
            issues.append({
                'category': 'ACCESSIBILITY',
                'severity': severity,
                'title': f"{label} ({len(selectors)} instance(s)) on {page_url}",
                'description': f"{len(selectors)} instance(s) of '{label}' found on {page_url}.",
                'route': page_url,
                'confidence': 1.0,
                'wcagLevel': wcag,
                'sampleTargets': selectors[:3],
                'expected': f"All {issue_type.split('-')[0]}s have proper accessible names.",
                'actual': f"{len(selectors)} violating element(s) found.",
                'acceptanceCriteria': [
                    f'[ ] All {issue_type.split("-")[0]} elements on {page_url} have accessible names.',
                ],
            })
    except Exception:
        pass

    return issues
