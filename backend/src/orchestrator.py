import os
import uuid
import asyncio
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

import src.storage as storage
from src.config import load_audit_config
from src.discovery import analyze_repo
from src.source_mapper import generate_test_vectors
from src.browser_engine import BrowserDriver, isDangerous as play_is_dangerous
import src.browser_engine as authHandler
from src.discovery import discover_app
from src.intelligence import plan_batch
from src.intelligence import evaluate_evidence
from src.intelligence import build_fix_prompt
from src.regression import compare_runs
from src.analyzers import (
    summarize_accessibility,
    find_console_errors,
    summarize_console,
    find_failed_requests,
    find_ui_api_mismatch,
    summarize_network,
    check_visual_regression,
    collect_web_vitals,
    analyze_performance,
    analyze_response_headers,
    analyze_url_for_secrets,
    analyze_cookies,
    analyze_api_responses,
    analyze_keyboard_navigation,
)
from src.reports import generate_report_html
from src.utils import make_logger
import src.intelligence as actionAgent

# Viewport matrix for Phase 4 (multi-viewport testing)
VIEWPORT_MATRIX = [
    {"name": "desktop", "width": 1280, "height": 800},
    {"name": "tablet", "width": 768, "height": 1024},
    {"name": "mobile", "width": 390, "height": 844},
]


# ---------------------------------------------------------
# EventBus (from eventBus.js)
# ---------------------------------------------------------

_buses = {}

class EventBus:
    def __init__(self):
        self.listeners = []

    def on(self, handler):
        self.listeners.append(handler)

    def off(self, handler):
        if handler in self.listeners:
            self.listeners.remove(handler)

    def emit(self, event_type: str, payload: Any):
        for handler in list(self.listeners):
            handler(event_type, payload)

    def remove_all_listeners(self):
        self.listeners.clear()

def get_bus(id: str) -> EventBus:
    if id not in _buses:
        _buses[id] = EventBus()
    return _buses[id]

def emit_event(id: str, event_type: str, payload: Any):
    bus = _buses.get(id)
    if bus:
        bus.emit(event_type, payload)

def subscribe(id: str, handler: Callable[[str, Any], None]) -> Callable[[], None]:
    bus = get_bus(id)
    bus.on(handler)
    return lambda: bus.off(handler)

def cleanup_bus(id: str):
    bus = _buses.get(id)
    if bus:
        bus.remove_all_listeners()
        del _buses[id]

# ---------------------------------------------------------
# Cancellation registry
# ---------------------------------------------------------

_cancelled: set = set()

def request_cancel(run_id: str):
    """Signal a running audit to stop at the next safe checkpoint."""
    _cancelled.add(run_id)
    # If the run is currently blocked waiting for HITL, unblock it immediately
    try:
        import src.hitl as hitl_module
        bs = hitl_module.get_block_state(run_id)
        if bs:
            bs.event.set()
    except Exception:
        pass

def is_cancelled(run_id: str) -> bool:
    return run_id in _cancelled

def clear_cancel(run_id: str):
    _cancelled.discard(run_id)

# ---------------------------------------------------------
# StateManager (from stateManager.js)
# ---------------------------------------------------------

HIGH_VALUE_KEYWORDS = [
    'create', 'save', 'submit', 'add', 'invite', 'checkout', 'pay',
    'delete', 'remove', 'update', 'edit', 'login', 'sign in', 'sign up',
    'register', 'confirm', 'send',
]
LOW_VALUE_KEYWORDS = ['about', 'faq', 'terms', 'privacy', 'help']

def normalize_flow_label(label: str) -> str:
    if not label:
        return ''
    label = str(label).lower()
    return re.sub(r'[_-]+', ' ', label).strip()

def is_dangerous(label: str) -> bool:
    return play_is_dangerous(label)

def score_action(label: str, kind: str, critical_flow_keywords: List[str] = None, low_priority_keywords: List[str] = None) -> int:
    if critical_flow_keywords is None: critical_flow_keywords = []
    if low_priority_keywords is None: low_priority_keywords = []
    
    score = 5
    lower = str(label or '').lower()
    if any(kw in lower for kw in HIGH_VALUE_KEYWORDS):
        score += 4
    if any(kw in lower for kw in LOW_VALUE_KEYWORDS):
        score -= 3
    if any(kw and kw in lower for kw in critical_flow_keywords):
        score += 6
    if any(kw and kw in lower for kw in low_priority_keywords):
        score -= 3
    if kind == 'form':
        score += 2
    if is_dangerous(label):
        score += 1
    return score

class StateManager:
    def __init__(self, flows=None):
        self.visited_state_hashes = set()
        self.pages = {}
        self.action_queue = []
        self.explored_action_ids = set()
        self.next_action_seq = 1
        self.critical_flow_keywords = [normalize_flow_label(kw) for kw in (flows.get('critical_flows', []) if flows else [])]
        self.low_priority_keywords = [normalize_flow_label(kw) for kw in (flows.get('low_priority', []) if flows else [])]

    def register_page(self, page_info: Dict[str, Any]):
        self.pages[page_info['url']] = page_info
        self.visited_state_hashes.add(page_info['stateHash'])

        for button in page_info.get('buttons', []):
            self._enqueue({
                'pageUrl': page_info['url'],
                'kind': 'button',
                'selector': button.get('selector'),
                'label': button.get('label'),
                'dangerous': is_dangerous(button.get('label'))
            })
            
        for form in page_info.get('forms', []):
            self._enqueue({
                'pageUrl': page_info['url'],
                'kind': 'form',
                'selector': form.get('selector'),
                'fields': form.get('fields', []),
                'label': f"form ({len(form.get('fields', []))} fields)",
                'dangerous': False
            })

    def _enqueue(self, action: Dict[str, Any]):
        action['id'] = f"a{self.next_action_seq}"
        self.next_action_seq += 1
        action['priority'] = score_action(action.get('label'), action.get('kind'), self.critical_flow_keywords, self.low_priority_keywords)
        self.action_queue.append(action)

    def has_visited_state_hash(self, hash_val: str) -> bool:
        return hash_val in self.visited_state_hashes

    def mark_state_visited(self, hash_val: str):
        self.visited_state_hashes.add(hash_val)

    def pop_next_action(self, allow_dangerous: bool) -> Optional[Dict[str, Any]]:
        self.action_queue.sort(key=lambda a: a['priority'], reverse=True)
        for idx, a in enumerate(self.action_queue):
            if a['id'] not in self.explored_action_ids and (allow_dangerous or not a['dangerous']):
                self.explored_action_ids.add(a['id'])
                return a
        return None

    def count_remaining(self, allow_dangerous: bool) -> int:
        return sum(1 for a in self.action_queue if a['id'] not in self.explored_action_ids and (allow_dangerous or not a['dangerous']))

    def count_skipped_dangerous(self) -> int:
        return sum(1 for a in self.action_queue if a['dangerous'] and a['id'] not in self.explored_action_ids)

    def summary(self) -> Dict[str, Any]:
        return {
            'pagesDiscovered': len(self.pages),
            'actionsQueued': len(self.action_queue),
            'actionsExplored': len(self.explored_action_ids),
            'statesVisited': len(self.visited_state_hashes)
        }

    def app_map_for_planner(self) -> List[Dict[str, Any]]:
        return [{
            'url': p['url'],
            'title': p.get('title'),
            'buttonCount': len(p.get('buttons', [])),
            'formCount': len(p.get('forms', []))
        } for p in self.pages.values()]

# ---------------------------------------------------------
# Cross User Flows (from crossUserFlows.js)
# ---------------------------------------------------------

class ProfileSessionPool:
    def __init__(self, primary_driver, profiles, push_log):
        self.primary_driver = primary_driver
        self.profiles_by_name = {p['name']: p for p in profiles}
        self.drivers = {}
        self.push_log = push_log

    async def get_driver(self, name: str):
        if name in self.drivers:
            return self.drivers[name]

        profile = self.profiles_by_name.get(name)
        if not profile:
            raise Exception(f'No login profile named "{name}" was configured for this run.')

        self.push_log(f'Logging in as "{name}" for cross-user flow...')
        storage_state = authHandler.load_storage_state(profile)
        driver = await self.primary_driver.spawnSibling(storageState=storage_state)

        if not storage_state:
            if authHandler.can_adaptive_login(profile):
                result = await authHandler.perform_adaptive_login(driver, profile)
                self.push_log(f'Login as "{name}": {"succeeded" if result.get("success") else "did not complete (" + str(result.get("reason")) + ")" }')
            elif authHandler.can_auto_login_form(profile):
                await authHandler.perform_form_login(driver, profile)
                self.push_log(f'Login as "{name}" via form submitted.')
            else:
                self.push_log(f'Warning: no usable login method for "{name}" - continuing unauthenticated.')

        self.drivers[name] = driver
        return driver

    async def close_all(self):
        for driver in self.drivers.values():
            try:
                await driver.close()
            except Exception:
                pass

def _cross_next_issue_id(state: Dict[str, Any]) -> str:
    return f"issue-{str(len(state['issues']) + 1).zfill(3)}"

async def run_cross_user_flows(primary_driver, profiles, flows, state, id, push_log_fn, persist_fn, update_live_view_fn):
    pool = ProfileSessionPool(primary_driver, profiles, lambda msg: push_log_fn(state, msg))

    try:
        for flow in flows:
            push_log_fn(state, f'Cross-user flow: "{flow.get("name")}"')
            await persist_fn(state)

            for step in flow.get('steps', []):
                try:
                    driver = await pool.get_driver(step['user'])
                except Exception as err:
                    push_log_fn(state, f'Skipping step ("{step.get("action")}"): {str(err)}')
                    continue
                await persist_fn(state)

                current_url = ''
                try:
                    current_url = await driver.current_url()
                except Exception:
                    pass

                state['currentAction'] = {
                    'kind': 'cross-user-step',
                    'label': step.get('action'),
                    'pageUrl': current_url,
                    'source': 'gemini',
                    'at': datetime.utcnow().isoformat() + 'Z'
                }
                await persist_fn(state)

                result = await actionAgent.run_instruction_loop(driver, {
                    'instruction': step.get('action'),
                    'maxSteps': step.get('maxSteps', 4)
                })
                push_log_fn(state, f'[{step.get("user")}] {step.get("action")} - {"done" if result.get("success") else "stopped (" + str(result.get("reason")) + ")"}')

                shot = None
                try:
                    shot = await driver.screenshot_buffer()
                except Exception:
                    pass
                await update_live_view_fn(id, state, shot)

                if step.get('expect'):
                    verdict = await actionAgent.verify_expectation(driver, step.get('expect'))

                    if verdict.get('satisfied') is False:
                        issue_id = _cross_next_issue_id(state)
                        evidence_shot = None
                        try:
                            evidence_shot = await driver.screenshot_buffer()
                        except Exception:
                            pass
                        
                        screenshot_path = storage.save_screenshot(id, evidence_shot, f"{issue_id}-crossuser.png") if evidence_shot else None

                        try:
                            route = await driver.current_url()
                        except Exception:
                            route = ''

                        issue = {
                            'id': issue_id,
                            'category': 'DATA_INCONSISTENCY',
                            'severity': 'high',
                            'confidence': verdict.get('confidence') if isinstance(verdict.get('confidence'), (int, float)) else 0.6,
                            'title': f"Cross-user expectation not met: {flow.get('name')}",
                            'description': verdict.get('explanation') or f"Expected (as \"{step.get('user')}\"): {step.get('expect')}",
                            'route': route,
                            'reproductionSteps': [
                                f"Run cross-user flow \"{flow.get('name')}\" up to and including the step (as {step.get('user')}): \"{step.get('action')}\"",
                                f"Check, still as {step.get('user')}: {step.get('expect')}"
                            ],
                            'expected': step.get('expect'),
                            'actual': verdict.get('explanation') or 'The expected condition was not observed.',
                            'likelyRootCause': None,
                            'evidence': {
                                'screenshotAfter': screenshot_path,
                                'crossUserFlow': flow.get('name')
                            },
                            'foundAt': datetime.utcnow().isoformat() + 'Z'
                        }
                        issue['fixPrompt'] = build_fix_prompt(issue)
                        state['issues'].append(issue)
                        push_log_fn(state, f"Cross-user issue found: {issue['title']}")
                    elif verdict.get('satisfied') is True:
                        push_log_fn(state, f"Cross-user check passed (as {step.get('user')}): {step.get('expect')}")
                    else:
                        push_log_fn(state, f"Could not verify (as {step.get('user')}): {step.get('expect')} - {verdict.get('explanation') or 'no reason given'}")
                    await persist_fn(state)
    finally:
        state['currentAction'] = None
        await pool.close_all()
        await persist_fn(state)


# ---------------------------------------------------------
# Audit Controller (from auditController.js)
# ---------------------------------------------------------

log = make_logger('auditController')
MAX_LOG_LINES = 300

def new_state(id: str, target_url: str, repo_path: str, budget: int, max_pages: int, safe_mode: bool, compare_against_id: str) -> Dict[str, Any]:
    return {
        'id': id,
        'targetUrl': target_url,
        'repoPath': repo_path or None,
        'budget': budget,
        'maxPages': max_pages,
        'safeMode': safe_mode,
        'compareAgainstId': compare_against_id or None,
        'regression': None,
        'authMode': 'none',
        'status': 'running',
        'phase': 'starting',
        'startedAt': datetime.utcnow().isoformat() + 'Z',
        'completedAt': None,
        'error': None,
        'progress': {
            'pagesDiscovered': 0,
            'actionsExecuted': 0,
            'actionsRemaining': budget,
            'statesVisited': 0,
            'skippedDangerous': 0,
        },
        'log': [],
        'repoAnalysis': None,
        'configSummary': None,
        'issues': [],
        'summary': {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'total': 0},
        'currentAction': None,
        'liveViewVersion': 0,
        'blockedQuestion': None,
        'blockedFieldType': None,
        'blockedScreenshotPath': None,
    }

def push_log(state: Dict[str, Any], message: str):
    state['log'].append({'at': datetime.utcnow().isoformat() + 'Z', 'message': message})
    if len(state['log']) > MAX_LOG_LINES:
        state['log'].pop(0)
    log.info(message)

def severity_counts(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'total': len(issues)}
    for issue in issues:
        sev = issue.get('severity')
        if sev in counts:
            counts[sev] += 1
    return counts

async def persist(state: Dict[str, Any]):
    try:
        storage.write_audit_state(state['id'], state)
        emit_event(state['id'], 'state', state)
    except Exception as err:
        log.error(f"Failed to persist audit {state['id']}: {str(err)}")

async def update_live_view(id: str, state: Dict[str, Any], buffer: bytes):
    if not buffer: return
    storage.save_screenshot(id, buffer, 'live.png')
    state['liveViewVersion'] += 1
    await persist(state)

def sample_value_for(field: Dict[str, Any]) -> str:
    name = str(field.get('name') or field.get('label') or '').lower()
    type_ = field.get('type')
    if type_ == 'email' or 'email' in name: return 'casefile.audit@example.com'
    if type_ == 'password' or 'password' in name: return 'CasefileAudit123!'
    if type_ == 'number' or 'amount' in name or 'quantity' in name: return '1'
    if type_ == 'tel' or 'phone' in name: return '5555550123'
    if type_ == 'date': return datetime.utcnow().isoformat()[:10]
    if type_ == 'url' or 'url' in name or 'website' in name: return 'https://example.com'
    if 'name' in name: return 'Casefile Audit'
    return 'Casefile audit sample text'

async def fill_form_with_sample_data(driver, action: Dict[str, Any]):
    for field in action.get('fields', []):
        if field.get('type') in ('checkbox', 'radio'): continue
        if field.get('type') in ('hidden', 'submit', 'button'): continue
        if field.get('type') == 'select':
            try:
                await driver.select_first_option(field.get('selector'))
            except Exception:
                pass
            continue
        try:
            await driver.fill(field.get('selector'), sample_value_for(field))
        except Exception:
            pass

async def fill_form_with_vault(driver, action: Dict[str, Any], state: Dict[str, Any], run_id: str):
    """Fill form fields using Fixture Vault for static fixtures.
    For unknown required fields, check vault before falling back to sample data.
    HITL pause logic is only triggered from the main loop, not here — this function
    only does vault lookup and sample-data fill.
    """
    if not hitl_module.hitl_enabled():
        await fill_form_with_sample_data(driver, action)
        return

    target_url = state.get('targetUrl', 'unknown')
    for field in action.get('fields', []):
        if field.get('type') in ('checkbox', 'radio', 'hidden', 'submit', 'button'):
            continue
        if field.get('type') == 'select':
            try:
                await driver.select_first_option(field.get('selector'))
            except Exception:
                pass
            continue

        field_key = field.get('selector') or field.get('name') or field.get('label') or ''
        static_val = hitl_module.lookup_static_fixture(target_url, field_key)
        if static_val is not None:
            try:
                await driver.fill(field.get('selector'), static_val)
                push_log(state, f'[HITL] Auto-filled field "{field_key}" from static fixture vault.')
            except Exception:
                pass
            continue

        # No static fixture — use sample data
        try:
            await driver.fill(field.get('selector'), sample_value_for(field))
        except Exception:
            pass

async def find_submit_control(driver, form_selector: str) -> Optional[str]:
    candidates = [
        f"{form_selector} button[type=\"submit\"]",
        f"{form_selector} input[type=\"submit\"]",
        f"{form_selector} button:not([type=\"button\"])"
    ]
    for selector in candidates:
        try:
            count = await driver.count(selector)
            if count > 0: return selector
        except Exception:
            pass
    return None

def describe_actual(console_summary: Dict, network_summary: Dict, ui_api_mismatch: Any) -> str:
    parts = []
    if ui_api_mismatch:
        matched_words = '", "'.join(ui_api_mismatch.get('matchedSuccessWords', []))
        failed_reqs = ", ".join(f"{r['method']} {r['url']} -> {r['status']}" for r in ui_api_mismatch.get('failedRequests', []))
        parts.append(
            f"The page displayed a success-sounding message (\"{matched_words}\") while "
            f"{len(ui_api_mismatch.get('failedRequests', []))} request(s) actually failed: {failed_reqs}"
        )
    if network_summary.get('failedCount', 0) > 0 and not ui_api_mismatch:
        failed_reqs = ", ".join(f"{r['method']} {r['url']} -> {r['status']}" for r in network_summary.get('failed', []))
        parts.append(
            f"{network_summary.get('failedCount')} network request(s) failed: {failed_reqs}"
        )
    if console_summary.get('errorCount', 0) > 0:
        errors = " | ".join(console_summary.get('errors', [])[:3])
        parts.append(f"{console_summary.get('errorCount')} console error(s) were logged: {errors}")
    return " ".join(parts) if parts else "No anomaly description available."

def build_repro_steps(action: Dict[str, Any]) -> List[str]:
    steps = [f"Open {action.get('pageUrl')}"]
    if action.get('kind') == 'button':
        steps.append(f"Click \"{action.get('label') or action.get('selector')}\"")
    elif action.get('kind') == 'form':
        steps.append(f"Fill in the form ({len(action.get('fields', []))} field(s)) with valid sample data")
        steps.append("Submit the form")
    return steps

def next_issue_id(state: Dict[str, Any]) -> str:
    return f"issue-{str(len(state['issues']) + 1).zfill(3)}"

async def investigate_action(driver, action: Dict[str, Any], state: Dict[str, Any], state_manager, business_context: Dict, id: str):
    before_nav_url = None
    try:
        before_nav_url = await driver.current_url()
    except Exception:
        pass

    if before_nav_url != action.get('pageUrl'):
        try:
            await driver.goto(action.get('pageUrl'))
        except Exception:
            pass
            
    markers = driver.markers()
    before_screenshot = None
    try:
        before_screenshot = await driver.screenshot_buffer()
    except Exception:
        pass
        
    before_url = await driver.current_url()
    await update_live_view(id, state, before_screenshot)
    
    expected = ''
    executed = False
    
    try:
        if action.get('kind') == 'button':
            expected = f"Clicking \"{action.get('label')}\" should produce a correct, visible response (navigation, updated content, or confirmation) with no errors."
            await driver.click(action.get('selector'))
            executed = True
        elif action.get('kind') == 'form':
            expected = "Submitting the form with valid data should succeed, or show clear validation feedback."
            await fill_form_with_vault(driver, action, state, id)
            submit_selector = await find_submit_control(driver, action.get('selector'))
            if submit_selector:
                await driver.click(submit_selector)
            executed = True
    except Exception as err:
        push_log(state, f"Could not execute {action.get('kind')} \"{action.get('label')}\" on {action.get('pageUrl')}: {str(err)}")
        
    if not executed: return
    
    await driver.wait_briefly(700)
    
    after_screenshot = None
    try:
        after_screenshot = await driver.screenshot_buffer()
    except Exception:
        pass
        
    after_url = before_url
    try:
        after_url = await driver.current_url()
    except Exception:
        pass
        
    await update_live_view(id, state, after_screenshot)
    console_events = driver.console_since(markers.get('consoleIndex'))
    network_events = driver.network_since(markers.get('networkIndex'))
    
    elements_after = {'bodyTextSignature': '', 'buttons': [], 'forms': []}
    try:
        elements_after = await driver.get_interactive_elements()
    except Exception:
        pass
        
    driver.clear_logs()
    
    console_summary = summarize_console(console_events)
    network_summary = summarize_network(network_events)
    ui_api_mismatch = find_ui_api_mismatch(network_events, elements_after.get('bodyTextSignature'))
    
    new_hash = None
    try:
        new_hash = await driver.compute_state_hash(elements_after)
    except Exception:
        pass
        
    is_new_state = bool(new_hash and not state_manager.has_visited_state_hash(new_hash))
    if is_new_state:
        registry_url = after_url if after_url != before_url else f"{after_url}#state-{new_hash[:8]}"
        state_manager.register_page({
            'url': registry_url,
            'title': await driver.title(),
            'stateHash': new_hash,
            'buttons': elements_after.get('buttons', []),
            'forms': elements_after.get('forms', [])
        })
        state['progress']['pagesDiscovered'] = state_manager.summary()['pagesDiscovered']
        push_log(state, f"Reached new state while exploring: {registry_url}")
        
        violations = []
        try:
            violations = await driver.run_axe()
        except Exception:
            pass
            
        if violations:
            axe_issues = summarize_accessibility(violations, after_url)
            for axe_issue in axe_issues:
                axe_issue['id'] = next_issue_id(state)
                axe_issue['confidence'] = 0.9
                axe_issue['reproductionSteps'] = [f"Open {after_url}"]
                axe_issue['expected'] = 'Page should pass automated accessibility checks (axe-core).'
                axe_issue['actual'] = axe_issue.get('description')
                axe_issue['likelyRootCause'] = None
                axe_issue['evidence'] = {'sampleTargets': axe_issue.get('sampleTargets')}
                axe_issue['fixPrompt'] = build_fix_prompt(
                    axe_issue,
                    business_rules=business_context.get('raw', 'No specific rule provided.') if business_context else 'No specific rule provided.',
                    cursor_context=business_context.get('cursorContext') if business_context else None
                )
                storage.save_fix_prompt(axe_issue['id'], axe_issue['fixPrompt'])
                state['issues'].append(axe_issue)
            push_log(state, f"Accessibility scan of {after_url}: {len(axe_issues)} violation type(s) found")

        # ── Phase 3: Visual regression check ──────────────────────────────────
        if after_screenshot:
            try:
                vr_issue = await check_visual_regression(
                    page_url=after_url,
                    current_screenshot=after_screenshot,
                    audit_id=id,
                    threshold=float(os.environ.get('VISUAL_REGRESSION_THRESHOLD', '0.05')),
                    gemini_confirm=bool(os.environ.get('GEMINI_API_KEY')),
                )
                if vr_issue:
                    vr_issue['id'] = next_issue_id(state)
                    vr_issue['fixPrompt'] = build_fix_prompt(
                        vr_issue,
                        business_rules=business_context,
                        cursor_context=business_context.get('cursorContext') if business_context else None,
                    )
                    storage.save_fix_prompt(vr_issue['id'], vr_issue['fixPrompt'])
                    state['issues'].append(vr_issue)
                    push_log(state, f"Visual regression detected on {after_url}: {vr_issue['title']}")
            except Exception as vr_err:
                push_log(state, f"Visual regression check error: {vr_err}")

        # ── Phase 5: Performance (Web Vitals) ─────────────────────────────────
        try:
            driver_page = getattr(driver, '_page', None) or getattr(driver, 'page', None)
            if driver_page:
                vitals = await collect_web_vitals(driver_page)
                perf_issues = analyze_performance(
                    vitals, after_url,
                    rules=business_context.get('rules') if business_context else None
                )
                for p_issue in perf_issues:
                    p_issue['id'] = next_issue_id(state)
                    p_issue['fixPrompt'] = build_fix_prompt(p_issue, business_rules=business_context)
                    storage.save_fix_prompt(p_issue['id'], p_issue['fixPrompt'])
                    state['issues'].append(p_issue)
                if perf_issues:
                    push_log(state, f"Performance issues on {after_url}: {len(perf_issues)} metric(s) exceeded threshold")
        except Exception as perf_err:
            push_log(state, f"Performance check error: {perf_err}")

        # ── Phase 6: Security header scan ─────────────────────────────────────
        try:
            driver_page = getattr(driver, '_page', None) or getattr(driver, 'page', None)
            if driver_page:
                # Check cookies
                cookie_issues = await analyze_cookies(driver_page, after_url)
                for c_issue in cookie_issues:
                    c_issue['id'] = next_issue_id(state)
                    c_issue['fixPrompt'] = build_fix_prompt(c_issue, business_rules=business_context)
                    storage.save_fix_prompt(c_issue['id'], c_issue['fixPrompt'])
                    state['issues'].append(c_issue)

                # Check URL for secrets
                secret_issue = analyze_url_for_secrets(after_url)
                if secret_issue:
                    secret_issue['id'] = next_issue_id(state)
                    secret_issue['fixPrompt'] = build_fix_prompt(secret_issue, business_rules=business_context)
                    storage.save_fix_prompt(secret_issue['id'], secret_issue['fixPrompt'])
                    state['issues'].append(secret_issue)
        except Exception as sec_err:
            push_log(state, f"Security check error: {sec_err}")

        # ── Phase 7: API contract verification ────────────────────────────────
        try:
            captured_responses = getattr(driver, '_captured_responses', [])
            if captured_responses:
                api_issues = analyze_api_responses(
                    captured_responses, after_url, action_label=action.get('label', '')
                )
                for a_issue in api_issues:
                    a_issue['id'] = next_issue_id(state)
                    a_issue['fixPrompt'] = build_fix_prompt(a_issue, business_rules=business_context)
                    storage.save_fix_prompt(a_issue['id'], a_issue['fixPrompt'])
                    state['issues'].append(a_issue)
                # Clear captured responses for next action
                driver._captured_responses = []
        except Exception as api_err:
            push_log(state, f"API contract check error: {api_err}")

        # ── Phase 8: Keyboard navigation / ARIA ───────────────────────────────
        try:
            driver_page = getattr(driver, '_page', None) or getattr(driver, 'page', None)
            if driver_page:
                kb_issues = await analyze_keyboard_navigation(driver_page, after_url)
                for k_issue in kb_issues:
                    k_issue['id'] = next_issue_id(state)
                    k_issue['fixPrompt'] = build_fix_prompt(k_issue, business_rules=business_context)
                    storage.save_fix_prompt(k_issue['id'], k_issue['fixPrompt'])
                    state['issues'].append(k_issue)
                if kb_issues:
                    push_log(state, f"Keyboard/ARIA issues on {after_url}: {len(kb_issues)}")
        except Exception as kb_err:
            push_log(state, f"Keyboard nav check error: {kb_err}")

    suspicious = console_summary.get('errorCount', 0) > 0 or network_summary.get('failedCount', 0) > 0 or bool(ui_api_mismatch)
    if not suspicious: return
    
    evidence_for_judge = {
        'consoleErrorCount': console_summary.get('errorCount'),
        'consoleErrors': console_summary.get('errors'),
        'networkSummary': network_summary.get('failed'),
        'uiApiMismatch': bool(ui_api_mismatch)
    }
    
    actual = describe_actual(console_summary, network_summary, ui_api_mismatch)
    
    verdict = await evaluate_evidence(
        action={'kind': action.get('kind'), 'label': action.get('label'), 'page': action.get('pageUrl')},
        expected=expected,
        actual=actual,
        evidence=evidence_for_judge,
        business_rules=business_context
    )
    
    if not verdict or not verdict.get('is_issue'): return
    
    issue_id = next_issue_id(state)
    screenshot_before_path = storage.save_screenshot(id, before_screenshot, f"{issue_id}-before.png") if before_screenshot else None
    screenshot_after_path = storage.save_screenshot(id, after_screenshot, f"{issue_id}-after.png") if after_screenshot else None
    storage.save_json(id, 'network', f"{issue_id}.json", network_events)
    storage.save_json(id, 'console', f"{issue_id}.json", console_events)
    
    issue = {
        'id': issue_id,
        'category': verdict.get('category') or 'FUNCTIONAL_BUG',
        'severity': verdict.get('severity') or 'medium',
        'confidence': verdict.get('confidence') if isinstance(verdict.get('confidence'), (int, float)) else 0.5,
        'title': verdict.get('title') or f"Issue found on {action.get('pageUrl')}",
        'description': verdict.get('description') or '',
        'route': action.get('pageUrl'),
        'reproductionSteps': build_repro_steps(action),
        'expected': expected,
        'actual': actual,
        'likelyRootCause': verdict.get('likely_root_cause'),
        'evidence': {
            'screenshotBefore': screenshot_before_path,
            'screenshotAfter': screenshot_after_path,
            'networkSummary': network_summary.get('failed'),
            'consoleErrors': console_summary.get('errors')
        },
        'foundAt': datetime.utcnow().isoformat() + 'Z'
    }
    issue['fixPrompt'] = build_fix_prompt(
        issue,
        business_rules=business_context.get('raw', 'No specific rule provided.') if business_context else 'No specific rule provided.',
        cursor_context=business_context.get('cursorContext') if business_context else None
    )
    storage.save_fix_prompt(issue_id, issue['fixPrompt'])
    
    state['issues'].append(issue)
    push_log(state, f"Issue found: [{issue['severity'].upper()}] {issue['title']}")

from src.context import current_run_id
import src.hitl as hitl_module

async def run_audit(kwargs: Dict[str, Any]):
    id = kwargs.get('id')
    current_run_id.set(id)
    target_url = kwargs.get('targetUrl')
    repo_path = kwargs.get('repoPath')
    budget = kwargs.get('budget', 40)
    safe_mode = kwargs.get('safeMode', True)
    max_pages = kwargs.get('maxPages', 15)
    compare_against_id = kwargs.get('compareAgainstId')
    auth = kwargs.get('auth')
    test_case_id = kwargs.get('testCaseId')

    state = new_state(id, target_url, repo_path, budget, max_pages, safe_mode, compare_against_id)
    storage.init_audit_dirs(id)
    await persist(state)
    
    driver = None
    
    try:
        push_log(state, f"Loading business-rules contract from {repo_path or '(none provided)'}")
        audit_config = load_audit_config(repo_path)
        state['configSummary'] = {
            'found': audit_config.get('found'),
            'hasAppSpec': bool(audit_config.get('appSpec')),
            'hasFlows': bool(audit_config.get('flows')),
            'hasRules': bool(audit_config.get('rules'))
        }
        state_manager = StateManager(flows=audit_config.get('flows'))
        business_context = {
            'appSpec': audit_config.get('appSpec'),
            'rules': audit_config.get('rules'),
            'flows': audit_config.get('flows'),
            'cursorContext': audit_config.get('cursorContext')
        }
        if repo_path:
            push_log(state, f"Analyzing repository at {repo_path}")
            state['repoAnalysis'] = analyze_repo(repo_path)
            
            push_log(state, f"[Source-Aware] Mapping routes and generating test vectors from {repo_path}")
            try:
                vectors = generate_test_vectors(repo_path)
                state['testVectors'] = vectors
                push_log(state, f"[Source-Aware] Found {len(vectors)} test vectors from codebase.")
            except Exception as e:
                push_log(state, f"[Source-Aware] Failed to generate test vectors: {str(e)}")

            
        await persist(state)
        
        auth_profiles = authHandler.resolve_auth_profiles(
            authOverride=auth,
            credentialsFromRepo=audit_config.get('credentials'),
            repoPath=repo_path
        )
        effective_auth = auth_profiles[0] if auth_profiles else None
        storage_state = authHandler.load_storage_state(effective_auth)
        
        state['phase'] = 'discovery'
        push_log(state, f"Launching browser and discovering {target_url} across {len(VIEWPORT_MATRIX)} viewport(s)")
        await persist(state)
        
        for viewport in VIEWPORT_MATRIX:
            push_log(state, f"--- Starting pass for viewport: {viewport['name']} ({viewport['width']}x{viewport['height']}) ---")
            
            driver = BrowserDriver(headless=(os.environ.get('HEADLESS') != 'false'))
            
            # Create a custom storage state with the viewport injected if necessary, 
            # or pass viewport to the driver
            vp_opts = {"viewport": {"width": viewport['width'], "height": viewport['height']}}
            
            # Launch handles creating the context, we must pass viewport options somehow
            # For this patch, we will monkey-patch the driver's _createContext opts before calling launch
            original_create = driver._createContext
            async def patched_create(storageState=None):
                context_options = {"viewport": vp_opts["viewport"]}
                if storageState:
                    context_options["storage_state"] = storageState
                driver.context = await driver.browser.new_context(**context_options)
                driver.page = await driver.context.new_page()
                driver._attachListeners()
                return driver
            driver._createContext = patched_create

            await driver.launch(storageState=storage_state)
            await driver.startTracing()
            
            if storage_state:
                state['authMode'] = 'storageState'
                push_log(state, 'Authenticated using a saved session (storageState) - no login form was driven.')
            elif authHandler.can_adaptive_login(effective_auth):
                state['authMode'] = 'adaptive'
                try:
                    async def on_step(step):
                        msg = f"Login step: {step.get('type')}{' on ' + step.get('selector') if step.get('selector') else ''}"
                        msg += f" (failed: {step.get('error')})" if step.get('error') else ""
                        msg += f" - {step.get('reason')}" if step.get('reason') else ""
                        push_log(state, msg)
                        try:
                            curr_url = await driver.current_url()
                        except:
                            curr_url = effective_auth.get('loginUrl') if effective_auth else ''
                        state['currentAction'] = {
                            'kind': 'login-step',
                            'label': step.get('type'),
                            'pageUrl': curr_url,
                            'source': 'gemini',
                            'at': datetime.utcnow().isoformat() + 'Z'
                        }
                        shot = None
                        try:
                            shot = await driver.screenshot_buffer()
                        except:
                            pass
                        await update_live_view(id, state, shot)

                    result = await authHandler.perform_adaptive_login(driver, effective_auth, {'onStep': on_step})
                    if result.get('success'):
                        push_log(state, f"Adaptive login succeeded: {result.get('reason')}")
                    else:
                        push_log(state, f"Adaptive login did not complete ({result.get('reason')}) - continuing as an unauthenticated session.")
                except Exception as err:
                    push_log(state, f"Adaptive login failed ({str(err)}) - continuing as an unauthenticated session.")
                state['currentAction'] = None
            elif authHandler.can_auto_login_form(effective_auth):
                state['authMode'] = 'form'
                try:
                    await authHandler.perform_form_login(driver, effective_auth)
                    push_log(state, f"Logged in via automated form login at {effective_auth.get('loginUrl')}.")
                except Exception as err:
                    push_log(state, f"Automated form login failed ({str(err)}) - continuing as an unauthenticated session.")
            else:
                push_log(state, 'No authentication configured - crawling as an unauthenticated session.')
                
            await persist(state)
            
            async def on_page(page_info):
                state_manager.register_page(page_info)
                state['progress']['pagesDiscovered'] = state_manager.summary()['pagesDiscovered']
                state['progress']['statesVisited'] = state_manager.summary()['statesVisited']
                push_log(state, f"Discovered page: {page_info.get('url')} ({len(page_info.get('buttons', []))} buttons, {len(page_info.get('forms', []))} forms)")
                await persist(state)
                
            await discover_app(
                driver,
                target_url,
                max_pages=max_pages,
                on_page=on_page
            )
            

            state['phase'] = 'exploring'
            if test_case_id:
                from src.db.database import SessionLocal
                from src.db.models import TestCase
                db = SessionLocal()
                tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
                db.close()
                
                if tc:
                    push_log(state, f"Executing Test Case: {tc.expected_result}")
                    for step in tc.steps:
                        push_log(state, f"Executing step: {step}")
                        await actionAgent.run_instruction_loop(driver, step, extra_context=str(business_context), max_steps=2)
                        await persist(state)
                        
                    push_log(state, f"Verifying expectation: {tc.expected_result}")
                    verification = await actionAgent.verify_expectation(driver, tc.expected_result)
                    
                    if verification and verification.get('satisfied') is False:
                        issue_id = str(uuid.uuid4()) if 'uuid' in globals() else "tc_fail_" + str(int(datetime.utcnow().timestamp()))
                        issue = {
                            'id': issue_id,
                            'title': 'Test Case Failed',
                            'description': verification.get('explanation', 'Assertion failed.'),
                            'severity': 'high',
                            'category': 'functional',
                            'route': await driver.current_url()
                        }
                        state['issues'].append(issue)
                        push_log(state, f"Issue found: [HIGH] {issue['title']} - {issue['description']}")
                else:
                    push_log(state, "Test case not found. Skipping exploration.")
            else:
                push_log(state, f"Starting adaptive exploration with a budget of {budget} actions")
                driver.clear_logs()
                await persist(state)
                
                if state['progress']['pagesDiscovered'] == 0:

                    push_log(state, 'Warning: no pages were discovered - check that the target URL is reachable and try again.')
                
            actions_executed = 0
            planned_queue = []
            plan_source = 'heuristic'
            PLAN_BATCH_SIZE = 5
            stuck_detector = hitl_module.StuckDetector() if hitl_module.hitl_enabled() else None


            while actions_executed < budget:
                # ── Cancellation check ─────────────────────────────────────────
                if is_cancelled(id):
                    push_log(state, 'Audit stopped by user request.')
                    break

                pages_before_action = state_manager.summary()['pagesDiscovered']
                remaining_candidates = [a for a in state_manager.action_queue if a['id'] not in state_manager.explored_action_ids and (not a.get('dangerous') if safe_mode else True)]
                
                if not remaining_candidates:
                    push_log(state, 'No more candidate actions to explore - ending exploration early.')
                    break
                    
                planned_queue = [aid for aid in planned_queue if any(c['id'] == aid for c in remaining_candidates)]
                
                if not planned_queue:
                    batch = await plan_batch(
                        app_map=state_manager.app_map_for_planner(),
                        candidates=remaining_candidates,
                        recent_findings=state['issues'],
                        business_rules=business_context,
                        actions_remaining=budget - actions_executed,
                        batch_size=PLAN_BATCH_SIZE
                    )
                    planned_queue = batch.get('queue', [])
                    plan_source = batch.get('source')
                    push_log(state, f"[{batch.get('source')}] Planned next {len(planned_queue)} action(s) - {batch.get('reason')}")
                    if not planned_queue: break
                    
                action_id = planned_queue.pop(0)
                action = next((c for c in remaining_candidates if c['id'] == action_id), None)
                if not action: continue
                
                state_manager.explored_action_ids.add(action['id'])
                push_log(state, f"[{plan_source}] Investigating {action.get('kind')} \"{action.get('label')}\" on {action.get('pageUrl')}")
                
                state['currentAction'] = {
                    'kind': action.get('kind'),
                    'label': action.get('label'),
                    'pageUrl': action.get('pageUrl'),
                    'source': plan_source,
                    'at': datetime.utcnow().isoformat() + 'Z'
                }
                await persist(state)
                
                try:
                    await investigate_action(driver, action, state, state_manager, business_context, id)
                except Exception as err:
                    push_log(state, f"Error while investigating action {action['id']}: {str(err)}")

                # ── HITL: stuck-loop safety net ────────────────────────────────────
                if hitl_module.hitl_enabled() and stuck_detector:
                    try:
                        elements_check = await driver.get_interactive_elements()
                        page_hash = await driver.compute_state_hash(elements_check)
                    except Exception:
                        page_hash = ''
                    if stuck_detector.record(page_hash or ''):
                        push_log(state, '[HITL] Stuck-loop detected: page state unchanged for 3 consecutive iterations. Requesting human input.')
                        state['phase'] = 'blocked'
                        state['status'] = 'blocked'
                        state['blockedQuestion'] = 'The agent appears stuck on this page. Please review the current page screenshot and provide guidance or a value for the required field.'
                        state['blockedFieldType'] = 'text'
                        screenshot_buf = None
                        try:
                            screenshot_buf = await driver.screenshot_buffer()
                        except Exception:
                            pass
                        if screenshot_buf:
                            storage.save_screenshot(id, screenshot_buf, 'hitl-blocked.png')
                            state['blockedScreenshotPath'] = 'screenshots/hitl-blocked.png'
                        bs = hitl_module.create_block_state(id)
                        bs.question = state['blockedQuestion']
                        bs.field_type = 'text'
                        bs.screenshot_path = state.get('blockedScreenshotPath')
                        await persist(state)
                        emit_event(id, 'needs_input', {
                            'runId': id,
                            'question': state['blockedQuestion'],
                            'fieldType': state['blockedFieldType'],
                            'screenshotPath': state.get('blockedScreenshotPath'),
                        })
                        try:
                            await asyncio.wait_for(bs.event.wait(), timeout=hitl_module.BLOCK_TIMEOUT_SECONDS)
                            human_answer = bs.answer
                            hitl_module.clear_block_state(id)
                            state['status'] = 'running'
                            state['phase'] = 'exploring'
                            state.pop('blockedQuestion', None)
                            state.pop('blockedFieldType', None)
                            state.pop('blockedScreenshotPath', None)
                            push_log(state, f'[HITL] Human provided input. Resuming exploration.')
                            if human_answer:
                                # Inject into page if there's a selector; else treat as context
                                if bs.field_selector:
                                    try:
                                        await driver.fill(bs.field_selector, human_answer)
                                    except Exception as fe:
                                        push_log(state, f'[HITL] Could not inject answer into selector {bs.field_selector}: {fe}')
                            stuck_detector.reset()
                            await persist(state)
                        except asyncio.TimeoutError:
                            hitl_module.clear_block_state(id)
                            push_log(state, '[HITL] Blocked: no human input received within timeout. Ending run.')
                            state['status'] = 'failed'
                            state['error'] = 'Run timed out waiting for human input.'
                            await persist(state)
                            break

                state['currentAction'] = None
                actions_executed += 1
                state['progress']['actionsExecuted'] = actions_executed
                state['progress']['actionsRemaining'] = budget - actions_executed
                state['progress']['statesVisited'] = state_manager.summary()['statesVisited']
                state['progress']['skippedDangerous'] = state_manager.count_skipped_dangerous()
                state['summary'] = severity_counts(state['issues'])
                await persist(state)
                
                if state_manager.summary()['pagesDiscovered'] > pages_before_action:
                    planned_queue = []

            # ── Close browser for this viewport before looping ──
            if getattr(driver, 'browser', None):
                await driver.browser.close()
            if getattr(driver, 'playwright', None):
                await driver.playwright.stop()
                
            if is_cancelled(id):
                break

                
        cross_user_flows_list = business_context.get('flows', {}).get('cross_user_flows', []) if business_context.get('flows') else []
        if not is_cancelled(id) and cross_user_flows_list and len(auth_profiles) > 1:
            state['phase'] = 'cross-user-flows'
            push_log(state, f"Running {len(cross_user_flows_list)} cross-user flow(s) across {len(auth_profiles)} login profile(s)")
            await persist(state)
            try:
                await run_cross_user_flows(
                    primary_driver=driver,
                    profiles=auth_profiles,
                    flows=cross_user_flows_list,
                    state=state,
                    id=id,
                    push_log_fn=push_log,
                    persist_fn=persist,
                    update_live_view_fn=update_live_view
                )
            except Exception as err:
                push_log(state, f"Cross-user flow phase failed: {str(err)}")
            state['summary'] = severity_counts(state['issues'])
            await persist(state)
        elif cross_user_flows_list and len(auth_profiles) <= 1:
            push_log(state, 'flows.yaml defines cross_user_flows but fewer than 2 login profiles were configured - skipping.')
            
        state['phase'] = 'reporting'
        push_log(state, 'Generating final report')
        await persist(state)
        
        if compare_against_id:
            previous = storage.read_audit_state(compare_against_id)
            if previous:
                state['regression'] = compare_runs(previous, state['issues'])
                reg = state['regression']
                push_log(state, f"Regression vs previous run ({compare_against_id}): {reg.get('resolvedCount')} resolved, {reg.get('stillPresentCount')} still present, {reg.get('newCount')} new.")
            else:
                push_log(state, f"Could not find previous audit {compare_against_id} to compare against - skipping regression comparison.")
            state['summary'] = severity_counts(state['issues'])
            await persist(state)
            
        trace_path = os.path.join(storage.traces_dir(id), 'trace.zip')
        try:
            await driver.stopTracing(trace_path)
        except:
            pass
            
        html = generate_report_html(state)
        storage.save_report_html(id, html)
        
        if is_cancelled(id):
            state['status'] = 'stopped'
            state['phase'] = 'done'
            state['completedAt'] = datetime.utcnow().isoformat() + 'Z'
            state['summary'] = severity_counts(state['issues'])
            push_log(state, f"Audit stopped by user. {len(state['issues'])} issue(s) found so far across {state['progress']['pagesDiscovered']} page(s).")
        else:
            state['status'] = 'completed'
            state['phase'] = 'done'
            state['completedAt'] = datetime.utcnow().isoformat() + 'Z'
            state['summary'] = severity_counts(state['issues'])
            push_log(state, f"Audit complete: {len(state['issues'])} issue(s) found across {state['progress']['pagesDiscovered']} page(s).")
        await persist(state)
        from src.regression_engine import run_post_audit_analysis
        run_post_audit_analysis(id)
        
    except Exception as err:
        import traceback
        log.error(f"Audit {id} failed: {traceback.format_exc()}")
        state['status'] = 'failed'
        state['error'] = err_str
        state['completedAt'] = datetime.utcnow().isoformat() + 'Z'
        push_log(state, f"Audit failed: {str(err)}")
        await persist(state)
        
    finally:
        clear_cancel(id)
        if driver:
            try:
                await driver.close()
            except:
                pass
        
        async def delayed_cleanup():
            await asyncio.sleep(5 * 60)
            cleanup_bus(id)
            
        asyncio.create_task(delayed_cleanup())
