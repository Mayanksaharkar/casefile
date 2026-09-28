import re
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional

def normalize_route(route: str) -> str:
    if not route:
        return ''
    pathname = str(route)
    try:
        parsed = urlparse(pathname)
        if parsed.scheme and parsed.netloc:
            pathname = parsed.path
        else:
            raise ValueError("Not an absolute URL")
    except Exception:
        pathname = pathname.split('?')[0]

    pathname = re.sub(r'/\d+(?=/|#|$)', '/:id', pathname)
    pathname = re.sub(r'/[0-9a-f-]{8,}(?=/|#|$)', '/:id', pathname, flags=re.IGNORECASE)
    pathname = re.sub(r'#state-[0-9a-f]+$', '', pathname, flags=re.IGNORECASE)
    
    return pathname

def normalize_title(title: str) -> str:
    t = str(title or '').lower()
    t = re.sub(r'[^a-z0-9\s]', '', t)
    t = re.sub(r'\s+', ' ', t)
    t = t.strip()
    if not t:
        return ''
    words = t.split(' ')[:8]
    return ' '.join(words)

def normalize_endpoint(entry: Dict[str, Any]) -> Optional[str]:
    if not entry or not entry.get('url'):
        return None
    
    pathname = str(entry['url'])
    try:
        parsed = urlparse(pathname)
        if parsed.scheme and parsed.netloc:
            pathname = parsed.path
        else:
            raise ValueError("Not an absolute URL")
    except Exception:
        pass
        
    pathname = re.sub(r'/\d+(?=/|$)', '/:id', pathname)
    pathname = re.sub(r'/[0-9a-f-]{8,}(?=/|$)', '/:id', pathname, flags=re.IGNORECASE)
    
    method = entry.get('method', 'GET')
    return f"{method} {pathname}"

def fingerprint_issue(issue: Dict[str, Any]) -> str:
    """
    Prefers deterministic evidence (an axe rule id, a specific failing
    endpoint) over the AI-generated title, since Gemini's wording for the
    "same" bug can vary slightly between runs even when nothing changed.
    """
    route = normalize_route(issue.get('route'))

    if issue.get('category') == 'ACCESSIBILITY' and issue.get('ruleId'):
        return f"ACCESSIBILITY::{route}::{issue['ruleId']}"

    evidence = issue.get('evidence')
    failed_endpoint = None
    if evidence and isinstance(evidence.get('networkSummary'), list) and len(evidence['networkSummary']) > 0:
        failed_endpoint = normalize_endpoint(evidence['networkSummary'][0])

    if failed_endpoint:
        return f"{issue.get('category')}::{route}::{failed_endpoint}"

    return f"{issue.get('category')}::{route}::{normalize_title(issue.get('title'))}"

def compare_runs(previous_state: Dict[str, Any], current_issues: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Compares the current run's issues against a previous completed run.
    Mutates each current issue in place with a `regressionStatus` of
    'new' or 'recurring', and returns a summary plus the list of issues
    that were present before but aren't anymore (i.e. resolved).
    """
    if not previous_state:
        return None

    previous_issues = previous_state.get('issues', [])
    previous_by_fingerprint = {}
    
    for issue in previous_issues:
        previous_by_fingerprint[fingerprint_issue(issue)] = issue

    seen_fingerprints = set()
    for issue in current_issues:
        fp = fingerprint_issue(issue)
        seen_fingerprints.add(fp)
        issue['regressionStatus'] = 'recurring' if fp in previous_by_fingerprint else 'new'

    resolved = []
    for issue in previous_issues:
        if fingerprint_issue(issue) not in seen_fingerprints:
            resolved.append({
                'id': issue.get('id'),
                'title': issue.get('title'),
                'category': issue.get('category'),
                'severity': issue.get('severity'),
                'route': issue.get('route'),
                'foundAt': issue.get('foundAt'),
            })

    return {
        'previousAuditId': previous_state.get('id'),
        'previousStartedAt': previous_state.get('startedAt'),
        'resolvedCount': len(resolved),
        'stillPresentCount': sum(1 for i in current_issues if i.get('regressionStatus') == 'recurring'),
        'newCount': sum(1 for i in current_issues if i.get('regressionStatus') == 'new'),
        'resolved': resolved,
    }
