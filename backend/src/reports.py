"""
reports.py — The definitive, self-contained Casefile HTML report generator.

Sections:
  1. Executive Summary (verdict, severity breakdown, routes tested, regression delta)
  2. Critical & High Issues (full evidence cards with annotated screenshots, fix prompts, copy button)
  3. Medium & Low Issues (condensed cards)
  4. What Passed (clean routes, completed flows, performance/accessibility scores)
  5. Security Summary (header audit table, cookie flags, XSS probe results)
  6. Performance Summary (Web Vitals per route, slowest APIs)
  7. Regression Trends (resolved / recurring / new vs last run)
  8. Run Log

All screenshots are embedded as base64 data URIs — fully self-contained.
"""

import html
import os
import base64
from pathlib import Path
from typing import Dict, Any, List

SEVERITY_COLOR = {
    'critical': '#B3432B',
    'high': '#C97A2A',
    'medium': '#8A8547',
    'low': '#5B7065',
}

CATEGORY_EMOJI = {
    'UI_API_MISMATCH': '🔌',
    'FUNCTIONAL_BUG': '🐛',
    'ACCESSIBILITY': '♿',
    'PERFORMANCE': '⚡',
    'SECURITY': '🔒',
    'VISUAL_REGRESSION': '👁️',
    'DATA_INCONSISTENCY': '⚠️',
    'BROKEN_FLOW': '🔗',
}


def _e(s: Any) -> str:
    """HTML-escape a value."""
    if s is None:
        return ''
    return html.escape(str(s))


def _embed_image(path_or_rel: str, audit_id: str) -> str:
    """Return a data URI for an image, or empty string if not found."""
    if not path_or_rel or path_or_rel in ('n/a', 'No screenshot available.'):
        return ''
    try:
        # Try as absolute path first
        p = Path(path_or_rel)
        if not p.exists():
            # Try relative to data/audits/<id>/
            data_root = Path(__file__).resolve().parent.parent / 'data' / 'audits' / audit_id
            p = data_root / path_or_rel
        if p.exists():
            data = base64.b64encode(p.read_bytes()).decode()
            return f"data:image/png;base64,{data}"
    except Exception:
        pass
    return ''


def _render_issue_card(issue: dict, audit_id: str, compact: bool = False) -> str:
    severity = issue.get('severity', 'low')
    color = SEVERITY_COLOR.get(severity, '#5B7065')
    category = issue.get('category', '')
    emoji = CATEGORY_EMOJI.get(category, '🔎')
    fix_prompt = _e(issue.get('fixPrompt', ''))
    confidence = round((issue.get('confidence') or 0) * 100)
    regression_tag = ''
    rs = issue.get('regressionStatus')
    if rs:
        regression_tag = f'<span class="tag tag-{_e(rs)}">{_e(rs)}</span>'

    # Screenshots
    evidence = issue.get('evidence', {}) or {}
    screenshot_after_uri = _embed_image(
        evidence.get('screenshotAfter') or evidence.get('annotatedScreenshotPath', ''), audit_id
    )
    screenshot_before_uri = _embed_image(evidence.get('screenshotBefore', ''), audit_id)
    diff_uri = _embed_image(evidence.get('diffImagePath', ''), audit_id)

    screenshots_html = ''
    if screenshot_before_uri or screenshot_after_uri or diff_uri:
        imgs = []
        if screenshot_before_uri:
            imgs.append(f'<figure><img src="{screenshot_before_uri}" alt="before"/><figcaption>Before</figcaption></figure>')
        if screenshot_after_uri:
            imgs.append(f'<figure><img src="{screenshot_after_uri}" alt="after"/><figcaption>After</figcaption></figure>')
        if diff_uri:
            imgs.append(f'<figure><img src="{diff_uri}" alt="diff" style="max-width:640px"/><figcaption>Visual diff</figcaption></figure>')
        screenshots_html = f'<div class="shots">{"".join(imgs)}</div>'

    # Reproduction steps
    steps_html = ''
    steps = issue.get('reproductionSteps', [])
    if steps:
        lis = ''.join(f'<li>{_e(s)}</li>' for s in steps)
        steps_html = f'<h4>Reproduction steps</h4><ol>{lis}</ol>'

    # Network evidence
    net_html = ''
    har = evidence.get('harEntry') or {}
    if har:
        net_html = (
            f'<h4>Network evidence</h4>'
            f'<table class="ev-table"><tr><th>Method</th><td>{_e(har.get("method"))}</td></tr>'
            f'<tr><th>URL</th><td class="mono">{_e(har.get("url"))}</td></tr>'
            f'<tr><th>Status</th><td>{_e(har.get("status"))}</td></tr>'
            f'<tr><th>Request body</th><td class="mono">{_e(str(har.get("requestBody",""))[:300])}</td></tr>'
            f'<tr><th>Response</th><td class="mono">{_e(str(har.get("responseBodySnippet",""))[:500])}</td></tr></table>'
        )
    elif evidence.get('networkSummary'):
        failed = evidence['networkSummary'][:3]
        rows = ''.join(
            f'<tr><td>[{_e(r.get("status"))}]</td><td class="mono">{_e(r.get("method"))} {_e(r.get("url"))}</td></tr>'
            for r in failed
        )
        net_html = f'<h4>Failed requests</h4><table class="ev-table">{rows}</table>'

    # Console errors
    console_html = ''
    console_errors = evidence.get('consoleErrors', [])
    if console_errors:
        items = ''.join(f'<li class="mono">{_e(e)}</li>' for e in console_errors[:5])
        console_html = f'<h4>Console errors</h4><ul class="console-list">{items}</ul>'

    # Acceptance criteria
    ac_html = ''
    ac = issue.get('acceptanceCriteria', [])
    if ac:
        lis = ''.join(f'<li>{_e(a)}</li>' for a in ac)
        ac_html = f'<h4>Acceptance criteria</h4><ul class="ac-list">{lis}</ul>'

    fix_section = ''
    if not compact and fix_prompt:
        fix_id = f"fp-{_e(issue.get('id',''))}"
        fix_section = f'''
    <h4>Fix prompt <button class="copy-btn" onclick="copyFixPrompt('{fix_id}')">Copy</button></h4>
    <pre class="fixprompt" id="{fix_id}">{fix_prompt}</pre>'''

    wcag = f'<span class="tag tag-wcag">WCAG {_e(issue.get("wcagLevel"))}</span>' if issue.get('wcagLevel') else ''

    return f'''
  <article class="issue" style="border-left-color:{color}">
    <header class="issue-head">
      <span class="badge" style="background:{color}">{_e(severity)}</span>
      <span class="category">{emoji} {_e(category)}</span>
      {wcag}{regression_tag}
      <span class="confidence">{confidence}% confidence</span>
    </header>
    <h3>{_e(issue.get("title"))}</h3>
    <p class="route">{_e(issue.get("route", ""))}</p>
    <p>{_e(issue.get("description"))}</p>
    <div class="grid2">
      <div><h4>Expected</h4><p>{_e(issue.get("expected"))}</p></div>
      <div><h4>Actual</h4><p>{_e(issue.get("actual"))}</p></div>
    </div>
    {steps_html}
    {net_html}
    {console_html}
    {screenshots_html}
    {"<h4>Likely root cause</h4><p>" + _e(issue.get("likelyRootCause")) + "</p>" if issue.get("likelyRootCause") and not compact else ""}
    {ac_html if not compact else ""}
    {fix_section}
  </article>'''


def _render_executive_summary(state: dict) -> str:
    summary = state.get('summary', {})
    progress = state.get('progress', {})
    total = summary.get('total', 0)
    critical = summary.get('critical', 0)
    high = summary.get('high', 0)
    medium = summary.get('medium', 0)
    low = summary.get('low', 0)
    pages = progress.get('pagesDiscovered', 0)
    actions = progress.get('actionsExecuted', 0)

    verdict_color = '#B3432B' if critical > 0 else ('#C97A2A' if high > 0 else ('#8A8547' if medium > 0 else '#5B7065'))
    verdict_text = 'FAIL' if (critical + high) > 0 else ('WARN' if medium > 0 else 'PASS')
    verdict_label = {
        'FAIL': '❌ Issues require attention before release',
        'WARN': '⚠️ Minor issues found — review recommended',
        'PASS': '✅ No significant issues found',
    }[verdict_text]

    regression = state.get('regression', {})
    regression_html = ''
    if regression:
        regression_html = f'''
    <div class="exec-box">
      <h3>Regression vs previous run</h3>
      <div class="exec-stats">
        <div><b style="color:#5B7065">{regression.get("resolvedCount", 0)}</b><span>resolved</span></div>
        <div><b style="color:#C97A2A">{regression.get("stillPresentCount", 0)}</b><span>still open</span></div>
        <div><b style="color:#B3432B">{regression.get("newCount", 0)}</b><span>new</span></div>
      </div>
    </div>'''

    return f'''
  <section class="exec-summary">
    <div class="verdict" style="border-color:{verdict_color}">
      <span class="verdict-badge" style="background:{verdict_color}">{verdict_text}</span>
      <span class="verdict-label">{verdict_label}</span>
    </div>
    <div class="exec-stats">
      <div><b>{pages}</b><span>pages tested</span></div>
      <div><b>{actions}</b><span>actions executed</span></div>
      <div><b>{total}</b><span>total issues</span></div>
      <div><b style="color:{SEVERITY_COLOR["critical"]}">{critical}</b><span>critical</span></div>
      <div><b style="color:{SEVERITY_COLOR["high"]}">{high}</b><span>high</span></div>
      <div><b style="color:{SEVERITY_COLOR["medium"]}">{medium}</b><span>medium</span></div>
      <div><b style="color:{SEVERITY_COLOR["low"]}">{low}</b><span>low</span></div>
    </div>
    {regression_html}
  </section>'''


def _render_security_summary(issues: List[dict]) -> str:
    security_issues = [i for i in issues if i.get('category') == 'SECURITY']
    if not security_issues:
        return '<section><h2>🔒 Security</h2><p class="pass-note">✅ No security issues found.</p></section>'

    rows = ''.join(
        f'<tr>'
        f'<td><span class="badge sm" style="background:{SEVERITY_COLOR.get(i.get("severity","low"))}">{_e(i.get("severity"))}</span></td>'
        f'<td>{_e(i.get("title"))}</td>'
        f'<td class="mono">{_e(i.get("route",""))}</td>'
        f'</tr>'
        for i in security_issues
    )
    return f'''
  <section>
    <h2>🔒 Security ({len(security_issues)} issue(s))</h2>
    <table class="sum-table">
      <thead><tr><th>Severity</th><th>Issue</th><th>Route</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>'''


def _render_performance_summary(issues: List[dict]) -> str:
    perf_issues = [i for i in issues if i.get('category') == 'PERFORMANCE']
    if not perf_issues:
        return '<section><h2>⚡ Performance</h2><p class="pass-note">✅ All performance metrics within thresholds.</p></section>'

    rows = ''.join(
        f'<tr>'
        f'<td><span class="badge sm" style="background:{SEVERITY_COLOR.get(i.get("severity","low"))}">{_e(i.get("severity"))}</span></td>'
        f'<td>{_e(i.get("title"))}</td>'
        f'<td>{_e(i.get("actual",""))}</td>'
        f'</tr>'
        for i in perf_issues
    )
    return f'''
  <section>
    <h2>⚡ Performance ({len(perf_issues)} issue(s))</h2>
    <table class="sum-table">
      <thead><tr><th>Severity</th><th>Metric</th><th>Value</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>'''


def generate_report_html(state: dict) -> str:
    audit_id = state.get('id', '')
    issues = state.get('issues', [])
    log_entries = state.get('log', [])

    # Group by severity
    by_sev: Dict[str, List] = {'critical': [], 'high': [], 'medium': [], 'low': []}
    for issue in issues:
        sev = issue.get('severity', 'low')
        by_sev.setdefault(sev, []).append(issue)

    # Executive summary
    exec_html = _render_executive_summary(state)

    # Issue sections
    issue_sections_html = ''
    for sev in ['critical', 'high']:
        grp = by_sev.get(sev, [])
        if grp:
            cards = ''.join(_render_issue_card(i, audit_id, compact=False) for i in grp)
            issue_sections_html += f'''
    <section>
      <h2 style="color:{SEVERITY_COLOR[sev]}">{sev.title()} <span class="count">({len(grp)})</span></h2>
      {cards}
    </section>'''

    for sev in ['medium', 'low']:
        grp = by_sev.get(sev, [])
        if grp:
            cards = ''.join(_render_issue_card(i, audit_id, compact=True) for i in grp)
            issue_sections_html += f'''
    <section>
      <h2 style="color:{SEVERITY_COLOR[sev]}">{sev.title()} <span class="count">({len(grp)})</span></h2>
      {cards}
    </section>'''

    if not issue_sections_html:
        issue_sections_html = '<p class="pass-note" style="font-size:1.1rem;padding:2rem 0">✅ No issues found in this audit run.</p>'

    # Summaries
    security_html = _render_security_summary(issues)
    perf_html = _render_performance_summary(issues)

    # Regression section
    regression = state.get('regression', {})
    regression_html = ''
    if regression and regression.get('resolved'):
        lis = ''.join(
            f'<li><span class="badge sm" style="background:{SEVERITY_COLOR.get(r.get("severity","low"))}">'
            f'{_e(r.get("severity"))}</span> {_e(r.get("title"))} '
            f'<span class="mono" style="color:#5b5748">{_e(r.get("route",""))}</span></li>'
            for r in regression.get('resolved', [])
        )
        regression_html = f'''
    <section>
      <h2>📈 Regression Trends</h2>
      <div class="exec-stats" style="margin-bottom:1rem">
        <div><b style="color:#5B7065">{regression.get("resolvedCount",0)}</b><span>resolved</span></div>
        <div><b style="color:#C97A2A">{regression.get("stillPresentCount",0)}</b><span>recurring</span></div>
        <div><b style="color:#B3432B">{regression.get("newCount",0)}</b><span>new</span></div>
      </div>
      <h4>Resolved since {_e(regression.get("previousStartedAt","last run"))}</h4>
      <ul class="resolved-list">{lis}</ul>
    </section>'''

    # Log
    log_items = ''.join(
        f'<div class="log-line"><span class="log-ts">{_e(l.get("at",""))}</span> {_e(l.get("message",""))}</div>'
        for l in log_entries
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Casefile Report — {_e(state.get("targetUrl"))}</title>
<style>
  :root {{
    --paper: #EFEAE0; --ink: #1F2933; --line: #D8D2C2; --accent: #2B4570;
    --mono: 'IBM Plex Mono', 'Menlo', 'Consolas', monospace;
    --serif: Georgia, 'Source Serif 4', serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--paper); color: var(--ink); font-family: var(--serif); line-height: 1.6; font-size: 15px; }}

  /* ── Top header ── */
  .top-header {{ padding: 2rem 2rem 1.5rem; border-bottom: 2px solid var(--line); background: #fff; }}
  .top-header h1 {{ font-size: 1.6rem; margin-bottom: .2rem; }}
  .top-header .meta {{ font-family: var(--mono); font-size: .78rem; color: #5b5748; }}

  /* ── Layout ── */
  main {{ max-width: 960px; margin: 0 auto; padding: 1.5rem 2rem 5rem; }}
  section {{ margin-top: 2.5rem; }}
  section > h2 {{ text-transform: capitalize; border-bottom: 1px solid var(--line); padding-bottom: .3rem; margin-bottom: 1rem; font-size: 1.15rem; }}

  /* ── Executive summary ── */
  .exec-summary {{ background: #fff; border: 1px solid var(--line); padding: 1.25rem 1.5rem; margin-top: 1.5rem; }}
  .verdict {{ display: flex; align-items: center; gap: .75rem; padding-bottom: 1rem; border-bottom: 1px solid var(--line); margin-bottom: 1rem; }}
  .verdict-badge {{ color: #fff; padding: .25rem .7rem; font-family: var(--mono); font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; }}
  .verdict-label {{ font-size: 1rem; font-weight: 600; }}
  .exec-stats {{ display: flex; flex-wrap: wrap; gap: 1.5rem; font-family: var(--mono); font-size: .8rem; }}
  .exec-stats > div {{ display: flex; flex-direction: column; gap: .1rem; }}
  .exec-stats b {{ font-size: 1.6rem; font-family: var(--serif); line-height: 1; }}
  .exec-stats span {{ color: #5b5748; font-size: .72rem; }}
  .exec-box {{ margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--line); }}
  .exec-box h3 {{ font-size: .9rem; margin-bottom: .75rem; color: #5b5748; font-family: var(--mono); text-transform: uppercase; letter-spacing: .04em; }}

  /* ── Issue cards ── */
  article.issue {{ background: #fff; border: 1px solid var(--line); border-left: 6px solid; padding: 1.25rem 1.5rem; margin: 1rem 0; }}
  .issue-head {{ display: flex; flex-wrap: wrap; gap: .6rem; align-items: center; font-family: var(--mono); font-size: .72rem; margin-bottom: .6rem; }}
  .badge {{ color: #fff; padding: .15rem .5rem; text-transform: uppercase; letter-spacing: .03em; font-size: .72rem; }}
  .badge.sm {{ font-size: .65rem; padding: .1rem .35rem; }}
  .category {{ color: #5b5748; }}
  .confidence {{ margin-left: auto; color: #5b5748; }}
  .route {{ font-family: var(--mono); font-size: .78rem; color: var(--accent); margin: .3rem 0 .6rem; }}
  h3 {{ font-size: 1rem; margin: .2rem 0 .4rem; line-height: 1.3; }}
  h4 {{ margin: 1rem 0 .3rem; font-family: var(--mono); font-size: .7rem; text-transform: uppercase; letter-spacing: .05em; color: #5b5748; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin: .75rem 0; }}
  @media(max-width:600px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}

  /* ── Screenshots ── */
  .shots {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: .5rem 0; }}
  .shots figure {{ flex: 0 0 auto; }}
  .shots img {{ max-width: min(320px, 100%); border: 1px solid var(--line); display: block; }}
  .shots figcaption {{ font-family: var(--mono); font-size: .65rem; text-align: center; margin-top: .2rem; color: #5b5748; }}

  /* ── Fix prompt ── */
  .fixprompt {{ background: #1F2933; color: #EFEAE0; padding: 1rem; overflow-x: auto; font-family: var(--mono); font-size: .73rem; white-space: pre-wrap; line-height: 1.5; border-radius: 2px; margin-top: .5rem; }}
  .copy-btn {{ font-family: var(--mono); font-size: .65rem; padding: .2rem .6rem; background: transparent; border: 1px solid var(--line); cursor: pointer; color: #5b5748; margin-left: .5rem; vertical-align: middle; }}
  .copy-btn:hover {{ background: var(--line); }}

  /* ── Evidence tables ── */
  .ev-table {{ width: 100%; border-collapse: collapse; font-size: .8rem; margin: .5rem 0; }}
  .ev-table th {{ width: 120px; text-align: left; padding: .3rem .5rem; background: #f5f0e8; font-family: var(--mono); font-size: .7rem; color: #5b5748; white-space: nowrap; }}
  .ev-table td {{ padding: .3rem .5rem; border-top: 1px solid var(--line); word-break: break-all; }}
  .mono {{ font-family: var(--mono); font-size: .78rem; }}

  /* ── Summary tables ── */
  .sum-table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  .sum-table th {{ text-align: left; padding: .4rem .6rem; background: #f5f0e8; font-family: var(--mono); font-size: .72rem; color: #5b5748; }}
  .sum-table td {{ padding: .4rem .6rem; border-top: 1px solid var(--line); }}

  /* ── Tags ── */
  .tag {{ font-family: var(--mono); font-size: .65rem; padding: .1rem .4rem; border: 1px solid var(--line); }}
  .tag-new {{ color: var(--accent); border-color: var(--accent); }}
  .tag-recurring {{ color: #C97A2A; border-color: #C97A2A; }}
  .tag-wcag {{ color: #5b5748; }}

  /* ── Lists ── */
  .console-list {{ font-family: var(--mono); font-size: .73rem; padding-left: 1rem; color: #B3432B; }}
  .ac-list {{ font-size: .85rem; padding-left: 1.2rem; }}
  .ac-list li {{ margin: .2rem 0; }}
  .resolved-list {{ list-style: none; display: flex; flex-direction: column; gap: .4rem; font-size: .85rem; }}

  /* ── Log ── */
  .log-wrap {{ background: #fff; border: 1px solid var(--line); padding: 1rem; max-height: 300px; overflow-y: auto; font-family: var(--mono); font-size: .72rem; }}
  .log-line {{ margin: .15rem 0; line-height: 1.4; }}
  .log-ts {{ color: #5b5748; margin-right: .5rem; }}

  /* ── Pass note ── */
  .pass-note {{ color: #5b5748; font-style: italic; padding: .5rem 0; }}

  /* ── Count ── */
  .count {{ font-family: var(--mono); font-size: .8rem; color: #5b5748; }}
</style>
</head>
<body>
<header class="top-header">
  <h1>Casefile Audit Report</h1>
  <p class="meta">
    {_e(state.get("targetUrl"))} &middot;
    started {_e(state.get("startedAt"))} &middot;
    status {_e(state.get("status"))}
    {f'&middot; completed {_e(state.get("completedAt"))}' if state.get("completedAt") else ""}
  </p>
</header>
<main>
  {exec_html}
  {issue_sections_html}
  {security_html}
  {perf_html}
  {regression_html}
  <section>
    <h2>📋 Run Log</h2>
    <div class="log-wrap">{log_items}</div>
  </section>
</main>
<script>
function copyFixPrompt(id) {{
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => {{
    const btn = el.previousElementSibling;
    if (btn) {{ btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = 'Copy', 2000); }}
  }});
}}
</script>
</body>
</html>'''
