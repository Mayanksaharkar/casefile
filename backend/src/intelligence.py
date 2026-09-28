import os
import json
import re
import aiohttp
import asyncio
import logging

def make_logger(name):
    try:
        from ..utils import make_logger as ml
        return ml(name)
    except ImportError:
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

# --- geminiClient.js ---
log_ai_client = make_logger('aiClient')

GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'
OPENROUTER_API_BASE = 'https://openrouter.ai/api/v1/chat/completions'

def is_configured():
    return bool(os.environ.get('OPENROUTER_API_KEY')) or bool(os.environ.get('GEMINI_API_KEY'))

def strip_code_fence(text):
    trimmed = text.strip()
    fence_match = re.match(r'^```(?:json)?\s*([\s\S]*?)\s*```$', trimmed)
    return fence_match.group(1) if fence_match else trimmed

async def generate_json_open_router(system_prompt, user_prompt, temperature):
    model = os.environ.get('OPENROUTER_MODEL', 'meta-llama/llama-3.1-8b-instruct:free')
    body = {
        'model': model,
        'messages': [
            { 'role': 'system', 'content': system_prompt },
            { 'role': 'user', 'content': user_prompt }
        ],
        'temperature': temperature,
        'response_format': { 'type': 'json_object' }
    }

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
        'HTTP-Referer': os.environ.get('FRONTEND_ORIGIN', 'http://localhost:3000'),
        'X-Title': 'Casefile'
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(OPENROUTER_API_BASE, headers=headers, json=body) as response:
            if not response.ok:
                try:
                    err_text = await response.text()
                except Exception:
                    err_text = ""
                
                # Retry without response_format if JSON mode is unsupported
                if response.status == 400 and ("JSON mode" in err_text or "json_object" in err_text or "provider_error" in err_text):
                    log_ai_client.info(f"Model doesn't support JSON mode (400), retrying without response_format flag.")
                    body.pop('response_format', None)
                    async with session.post(OPENROUTER_API_BASE, headers=headers, json=body) as retry_response:
                        if not retry_response.ok:
                            try:
                                retry_err = await retry_response.text()
                            except:
                                retry_err = ""
                            log_ai_client.warning(f"OpenRouter API error {retry_response.status} (retry): {retry_err[:300]}")
                            return None
                        data = await retry_response.json()
                        return data.get('choices', [{}])[0].get('message', {}).get('content')

                log_ai_client.warning(f"OpenRouter API error {response.status}: {err_text[:300]}")
                return None
            data = await response.json()
            return data.get('choices', [{}])[0].get('message', {}).get('content')

async def generate_json_gemini(system_prompt, user_prompt, temperature):
    model = os.environ.get('GEMINI_MODEL', 'gemini-3.8-flash')
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={os.environ.get('GEMINI_API_KEY')}"
    
    body = {
        'systemInstruction': { 'parts': [{ 'text': system_prompt }] },
        'contents': [{ 'role': 'user', 'parts': [{ 'text': user_prompt }] }],
        'generationConfig': {
            'temperature': temperature,
            'responseMimeType': 'application/json',
        },
    }

    headers = { 'Content-Type': 'application/json' }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body) as response:
            if not response.ok:
                try:
                    err_text = await response.text()
                except Exception:
                    err_text = ""
                log_ai_client.warning(f"Gemini API error {response.status}: {err_text[:300]}")
                return None
            data = await response.json()
            parts = data.get('candidates', [{}])[0].get('content', {}).get('parts', [])
            return ''.join([p.get('text', '') for p in parts]) if parts else None

from src.context import current_run_id
from src.db.sync import log_eval

async def generate_json(system_prompt, user_prompt, temperature=0.2):
    if not is_configured():
        log_ai_client.debug('No AI API key set - skipping AI reasoning call.')
        return None

    try:
        text = None
        if os.environ.get('OPENROUTER_API_KEY'):
            text = await generate_json_open_router(system_prompt, user_prompt, temperature)
        else:
            text = await generate_json_gemini(system_prompt, user_prompt, temperature)

        if not text:
            log_ai_client.warning('AI response had no text content.')
            return None

        try:
            parsed = json.loads(strip_code_fence(text))
            
            # Phase 0: store every judgment call
            run_id = current_run_id.get(None)
            if run_id:
                log_eval(run_id, prompt=f"{system_prompt}\n\n{user_prompt}", response=text, parsed_action=parsed)
                
            return parsed
        except json.JSONDecodeError as err:
            log_ai_client.warning(f"Could not parse AI JSON response: {str(err)}")
            return None
    except Exception as err:
        log_ai_client.warning(f"AI request failed: {str(err)}")
        return None


# --- actionAgent.js ---
log_action_agent = make_logger('actionAgent')

STEP_SYSTEM_PROMPT = """You are Casefile's action agent. You are given a plain-language
instruction, optional extra context (such as credentials to use), and the buttons/form
fields actually visible on the current page (each with a CSS selector). Decide the SINGLE
next action that makes progress on the instruction. Only ever reference a selector that is
listed - never invent one. If the instruction appears already fulfilled (the described
outcome is already visible, or nothing left on this page relates to it), respond with type
"done". If you encounter a required field you cannot fill (CAPTCHA, OTP, unknown required
field, unresolvable validation error), respond with type "request_input": provide a
human-readable question and a reference to the target field selector. Do NOT use "fail"
when a human could unblock you — use "fail" only when the page itself is broken or the
instruction is impossible regardless of human input.
Respond with strict JSON only."""

VERIFY_SYSTEM_PROMPT = """You are Casefile's verification agent. You are given a
plain-language expectation about what the current page should show, and a summary of the
page's visible text and URL. Decide whether the expectation is satisfied by what's actually
there - do not assume it passed just because the page loaded without error. Respond with
strict JSON only."""

def build_step_prompt(instruction, extra_context, elements, steps_taken, max_steps):
    buttons = elements.get('buttons', [])
    forms = elements.get('forms', [])
    
    formatted_buttons = [{'selector': b.get('selector'), 'label': b.get('label')} for b in buttons]
    
    formatted_fields = []
    for f in forms:
        fields = f.get('fields', [])
        for fld in fields:
            formatted_fields.append({
                'selector': fld.get('selector'),
                'type': fld.get('type'),
                'label': fld.get('label'),
                'name': fld.get('name')
            })
            
    payload = {
        'instruction': instruction,
        'extra_context': extra_context or None,
        'current_page': {
            'buttons': formatted_buttons,
            'fields': formatted_fields,
        },
        'steps_already_taken': steps_taken,
        'step_number': len(steps_taken) + 1,
        'max_steps': max_steps,
        'response_schema': {
            'type': '"fill" | "click" | "wait" | "done" | "fail" | "request_input"',
            'selector': 'string - required for fill/click/request_input, must exactly match a listed selector',
            'value': 'string - required for fill (e.g. an email, code, or password taken from extra_context)',
            'ms': 'number - optional for wait, defaults to 800',
            'reason': 'string, one sentence',
            'question': 'string - required for request_input: human-readable question describing what value is needed',
            'field_type': 'string - for request_input: guessed type of the field (email|otp|text|select|password)',
        }
    }
    return json.dumps(payload, indent=2)

async def decide_next_step(instruction, extra_context, elements, steps_taken, max_steps):
    if not is_configured():
        return { 'type': 'fail', 'reason': 'Gemini is not configured - the adaptive action agent requires GEMINI_API_KEY.' }
    
    result = await generate_json(
        system_prompt=STEP_SYSTEM_PROMPT,
        user_prompt=build_step_prompt(instruction, extra_context, elements, steps_taken, max_steps)
    )
    
    if not result or not result.get('type'):
        return { 'type': 'fail', 'reason': 'The action agent returned an unusable response.' }
    return result

async def run_instruction_loop(driver, instruction, extra_context=None, max_steps=6, on_step=None):
    if isinstance(instruction, dict):
        extra_context = instruction.get('extraContext', extra_context)
        max_steps = instruction.get('maxSteps', max_steps)
        on_step = instruction.get('onStep', on_step)
        if isinstance(on_step, dict) and 'onStep' in on_step:
            on_step = on_step['onStep']
        instruction = instruction.get('instruction', str(instruction))

    steps_taken = []
    
    for _ in range(max_steps):
        from src.context import current_run_id
        from src.orchestrator import is_cancelled
        
        run_id = current_run_id.get()
        if run_id and is_cancelled(run_id):
            return { 'success': False, 'steps': steps_taken, 'reason': 'Audit stopped by user.' }

        try:
            elements = await driver.getInteractiveElements()
        except Exception:
            elements = {'buttons': [], 'forms': []}
            
        decision = await decide_next_step(instruction, extra_context, elements, steps_taken, max_steps)
        
        if decision.get('type') == 'done':
            return { 'success': True, 'steps': steps_taken, 'reason': decision.get('reason', 'Instruction complete.') }
        if decision.get('type') == 'fail':
            return { 'success': False, 'steps': steps_taken, 'reason': decision.get('reason', 'The action agent could not proceed.') }
        
        if decision.get('type') == 'request_input':
            from src.context import current_run_id
            import src.hitl as hitl_module
            from src.orchestrator import emit_event, persist
            from src import storage
            import asyncio
            
            run_id = current_run_id.get()
            if hitl_module.hitl_enabled() and run_id:
                state = storage.read_audit_state(run_id)
                if state:
                    selector = decision.get('selector')
                    target_url = state.get('targetUrl', 'unknown')
                    
                    # 1. Check static fixture vault first
                    static_val = hitl_module.lookup_static_fixture(target_url, selector or '') if selector else None
                    if static_val:
                        try:
                            await driver.fill(selector, static_val)
                            continue
                        except Exception:
                            pass
                            
                    # 2. No static fixture, so we block and ask the human
                    old_phase = state.get('phase', 'exploring')
                    state['phase'] = 'blocked'
                    state['status'] = 'blocked'
                    state['blockedQuestion'] = decision.get('question', 'Input requested by agent.')
                    state['blockedFieldType'] = decision.get('field_type', 'text')
                    screenshot_buf = None
                    try:
                        screenshot_buf = await driver.screenshot_buffer()
                    except Exception:
                        pass
                    if screenshot_buf:
                        storage.save_screenshot(run_id, screenshot_buf, 'hitl-blocked.png')
                        state['blockedScreenshotPath'] = 'screenshots/hitl-blocked.png'
                    
                    bs = hitl_module.create_block_state(run_id)
                    bs.question = state['blockedQuestion']
                    bs.field_type = state['blockedFieldType']
                    bs.screenshot_path = state.get('blockedScreenshotPath')
                    bs.field_selector = decision.get('selector')
                    await persist(state)
                    
                    emit_event(run_id, 'needs_input', {
                        'runId': run_id,
                        'question': state['blockedQuestion'],
                        'fieldType': state['blockedFieldType'],
                        'screenshotPath': state.get('blockedScreenshotPath')
                    })
                    
                    try:
                        await asyncio.wait_for(bs.event.wait(), timeout=hitl_module.BLOCK_TIMEOUT_SECONDS)
                        human_answer = bs.answer
                        hitl_module.clear_block_state(run_id)
                        
                        from src.orchestrator import is_cancelled
                        if is_cancelled(run_id):
                            return { 'success': False, 'steps': steps_taken, 'reason': 'Audit stopped by user.' }
                            
                        state['status'] = 'running'
                        state['phase'] = old_phase
                        state.pop('blockedQuestion', None)
                        state.pop('blockedFieldType', None)
                        state.pop('blockedScreenshotPath', None)
                        await persist(state)
                        if human_answer and bs.field_selector:
                            try:
                                await driver.fill(bs.field_selector, human_answer)
                            except Exception:
                                pass
                    except asyncio.TimeoutError:
                        hitl_module.clear_block_state(run_id)
                        return { 'success': False, 'steps': steps_taken, 'reason': 'Timed out waiting for human input.' }
                
                # Continue loop after human resolves it
                continue
            else:
                return { 'success': False, 'steps': steps_taken, 'reason': 'HITL is disabled but agent requested input.' }
            
        valid_selectors = set()
        for b in elements.get('buttons', []):
            if 'selector' in b:
                valid_selectors.add(b['selector'])
        for f in elements.get('forms', []):
            for fld in f.get('fields', []):
                if 'selector' in fld:
                    valid_selectors.add(fld['selector'])
                    
        step_record = dict(decision)
        try:
            dec_type = decision.get('type')
            if dec_type == 'fill':
                selector = decision.get('selector')
                if selector not in valid_selectors:
                    raise Exception(f"Selector not present on page: {selector}")
                await driver.fill(selector, decision.get('value', ''))
            elif dec_type == 'click':
                selector = decision.get('selector')
                if selector not in valid_selectors:
                    raise Exception(f"Selector not present on page: {selector}")
                await driver.click(selector)
            elif dec_type == 'wait':
                await driver.waitBriefly(decision.get('ms', 800))
            else:
                raise Exception(f"Unknown action type \"{dec_type}\"")
        except Exception as err:
            step_record['error'] = str(err)
            steps_taken.append(step_record)
            if on_step:
                if asyncio.iscoroutinefunction(on_step):
                    await on_step(step_record)
                else:
                    on_step(step_record)
            continue
            
        steps_taken.append(step_record)
        if on_step:
            if asyncio.iscoroutinefunction(on_step):
                await on_step(step_record)
            else:
                on_step(step_record)
        await driver.waitBriefly(500)
        
    return { 'success': False, 'steps': steps_taken, 'reason': f"Gave up after {max_steps} steps without the agent reporting done." }

async def verify_expectation(driver, expect_text):
    if not is_configured():
        return { 'satisfied': None, 'confidence': 0, 'explanation': 'Gemini is not configured - cannot verify cross-user expectations.' }
        
    try:
        elements = await driver.getInteractiveElements()
    except Exception:
        elements = { 'bodyTextSignature': '' }
        
    try:
        url = await driver.currentUrl()
    except Exception:
        url = ''
        
    result = await generate_json(
        system_prompt=VERIFY_SYSTEM_PROMPT,
        user_prompt=json.dumps({
            'expectation': expect_text,
            'current_url': url,
            'visible_text': elements.get('bodyTextSignature', ''),
            'response_schema': { 'satisfied': 'boolean', 'confidence': 'number 0 to 1', 'explanation': 'one or two sentences' }
        }, indent=2)
    )
    
    if not result or not isinstance(result.get('satisfied'), bool):
        log_action_agent.debug('Verification agent returned an unusable response.')
        return { 'satisfied': None, 'confidence': 0, 'explanation': 'Verification agent returned an unusable response.' }
        
    return result


# --- bugJudge.js ---
log_bug_judge = make_logger('bugJudge')

CATEGORIES = [
    'FUNCTIONAL_BUG', 'LOGIC_BUG', 'UI_BUG', 'UX_ISSUE', 'ACCESSIBILITY',
    'NETWORK_ERROR', 'STATE_MANAGEMENT', 'DATA_INCONSISTENCY',
    'MISSING_VALIDATION', 'EDGE_CASE', 'BROKEN_WORKFLOW', 'SECURITY_SUSPICION',
]

BUG_JUDGE_SYSTEM_PROMPT = f"""You are the bug-judge layer of Casefile, an adaptive web application auditor.
You receive a single observation gathered by a deterministic browser-automation layer
(Playwright): what action was taken, what was expected, what actually happened, and the
raw evidence (network requests, console errors). Decide whether this is a genuine issue.
Never invent facts not present in the evidence. If the evidence is inconclusive, say so
honestly with lower confidence rather than guessing. Categories you may use: {', '.join(CATEGORIES)}.
Respond with strict JSON only, matching the requested schema."""

def build_bug_judge_user_prompt(action, expected, actual, evidence, business_rules):
    instructions = 'Evaluate the deviation.'
    if business_rules and business_rules.get('cursorContext'):
        instructions += f"\n\n[CURSOR IDE CONTEXT]\nPay close attention to this context from the developer to determine if this is an intended feature or a bug: {business_rules.get('cursorContext')}"
        
    return json.dumps({
        'instructions': instructions,
        'action': action,
        'expected': expected,
        'actual': actual,
        'evidence': evidence,
        'business_rules': business_rules or None,
        'response_schema': {
            'is_issue': 'boolean',
            'category': f"one of: {', '.join(CATEGORIES)}",
            'severity': 'one of: critical, high, medium, low',
            'confidence': 'number 0 to 1',
            'title': 'short string, under 12 words',
            'description': 'one to two sentences',
            'likely_root_cause': 'one to two sentences, or null if unclear',
        },
    }, indent=2)

def deterministic_verdict(evidence):
    if evidence and evidence.get('uiApiMismatch'):
        return {
            'is_issue': True,
            'category': 'LOGIC_BUG',
            'severity': 'high',
            'confidence': 0.75,
            'title': 'UI reports success despite a failed request',
            'description': 'The interface displayed a success message while the underlying network request returned an error status.',
            'likely_root_cause': 'The success message is likely shown unconditionally instead of being gated on the request outcome.',
        }
    if evidence and evidence.get('consoleErrorCount', 0) > 0:
        return {
            'is_issue': True,
            'category': 'FUNCTIONAL_BUG',
            'severity': 'medium',
            'confidence': 0.5,
            'title': 'Console error during interaction',
            'description': 'One or more console errors were logged while performing this action.',
            'likely_root_cause': None,
        }
    return { 'is_issue': False }

async def evaluate_evidence(action, expected, actual, evidence, business_rules=None):
    if is_configured():
        result = await generate_json(
            system_prompt=BUG_JUDGE_SYSTEM_PROMPT,
            user_prompt=build_bug_judge_user_prompt(action, expected, actual, evidence, business_rules)
        )
        if result and isinstance(result.get('is_issue'), bool):
            return result
        log_bug_judge.debug('Gemini bug-judge call unusable - falling back to deterministic verdict.')
    return deterministic_verdict(evidence)


# --- fixPromptGenerator.js ---

def build_fix_prompt(issue, business_rules=None, cursor_context=None):
    """Build a rich, self-contained fix prompt that a developer can paste into
    Cursor / Claude Code and resolve without any follow-up questions."""
    evidence = issue.get('evidence', {}) or {}
    category = issue.get('category', 'FUNCTIONAL_BUG')
    severity = issue.get('severity', 'medium')
    route = issue.get('route', 'unknown')
    title = issue.get('title', 'Untitled issue')
    viewport = issue.get('viewport', 'desktop 1280x800')
    auth_mode = issue.get('authMode', 'unauthenticated')

    # ── Network HAR entry ──────────────────────────────────────────────────────
    har_entry = evidence.get('harEntry') or {}
    if har_entry:
        req_body = har_entry.get('requestBody') or har_entry.get('request_body') or '(none)'
        resp_body = har_entry.get('responseBodySnippet') or har_entry.get('response_body_snippet') or '(none)'
        har_block = (
            f"  Method:          {har_entry.get('method', 'unknown')}\n"
            f"  URL:             {har_entry.get('url', 'unknown')}\n"
            f"  Request Body:    {str(req_body)[:500]}\n"
            f"  Response Status: {har_entry.get('status', 'unknown')}\n"
            f"  Response Body:   {str(resp_body)[:1000]}"
        )
    else:
        failed_requests = (evidence.get('networkSummary') or [])[:3]
        if failed_requests:
            har_block = '\n'.join(
                f"  [{r.get('status', '?')}] {r.get('method', 'GET')} {r.get('url', '')}"
                for r in failed_requests
            )
        else:
            har_block = '  No network failures captured during this action.'

    # ── Console errors ─────────────────────────────────────────────────────────
    console_errors = evidence.get('consoleErrors') or []
    if console_errors:
        console_block = '\n'.join(f"  {e}" for e in console_errors[:10])
    else:
        console_block = '  No console errors captured.'

    # ── DOM snapshot ───────────────────────────────────────────────────────────
    dom_snapshot = evidence.get('domSnapshot') or 'No DOM snapshot available.'
    dom_block = str(dom_snapshot)[:2000]

    # ── Screenshot paths ───────────────────────────────────────────────────────
    screenshot_after = evidence.get('annotatedScreenshotPath') or evidence.get('screenshotAfter') or 'n/a'
    screenshot_before = evidence.get('screenshotBefore') or 'n/a'

    # ── Reproduction steps ─────────────────────────────────────────────────────
    reproduction_steps = issue.get('reproductionSteps') or []
    if reproduction_steps:
        reproduction_block = '\n'.join(f"  {i+1}. {s}" for i, s in enumerate(reproduction_steps))
    else:
        reproduction_block = f"  1. Navigate to {route}\n  2. Observe the issue described above."

    # ── Business rule violated ─────────────────────────────────────────────────
    violated_rule = issue.get('violatedRule', None)
    if not violated_rule and business_rules:
        if isinstance(business_rules, dict):
            rules_text = business_rules.get('rules') or business_rules.get('appSpec') or ''
            violated_rule = str(rules_text)[:500] if rules_text else None
        elif isinstance(business_rules, str):
            violated_rule = business_rules[:500]
    violated_rule = violated_rule or 'No specific business rule on file — apply standard correctness expectations.'

    # ── Acceptance criteria ────────────────────────────────────────────────────
    ac_list = issue.get('acceptanceCriteria') or []
    if not ac_list:
        # Auto-generate from category
        ac_map = {
            'UI_API_MISMATCH': [
                '[ ] The UI correctly reflects success only when the underlying API request returns 2xx.',
                '[ ] The UI shows an appropriate error state when the API returns 4xx or 5xx.',
                '[ ] No console errors during the happy path of this flow.',
            ],
            'ACCESSIBILITY': [
                '[ ] axe-core reports zero violations of this rule on the affected page.',
                '[ ] The element is keyboard-accessible with a visible focus indicator.',
            ],
            'PERFORMANCE': [
                '[ ] The metric is within the required threshold defined in rules.yaml.',
                '[ ] No render-blocking resources introduced by the fix.',
            ],
            'SECURITY': [
                '[ ] The vulnerability is not reproducible using the same probe.',
                '[ ] Security headers are correctly set in the response.',
            ],
        }
        ac_list = ac_map.get(category, [
            '[ ] The flow completes without errors end-to-end.',
            '[ ] The UI reflects the correct state after the action.',
            '[ ] No new console errors are introduced.',
        ])
    ac_block = '\n'.join(f"  {ac}" for ac in ac_list)

    # ── Cursor IDE context ─────────────────────────────────────────────────────
    cursor_block = (
        f"\n\n━━━ CURSOR IDE CONTEXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{cursor_context}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ) if cursor_context else ''

    prompt = f"""━━━ CASEFILE BUG REPORT — ACTION REQUIRED ━━━━━━━━━━━━━━━━━━━━━━━

Severity:   {severity.upper()}
Category:   {category}
Route:      {route}
Viewport:   {viewport}
Auth state: {auth_mode}
Confidence: {round((issue.get('confidence') or 0) * 100)}%

━━━ WHAT BROKE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{title}

{issue.get('description', '')}

━━━ EXPECTED vs ACTUAL ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Expected:
  {issue.get('expected', 'n/a')}

Actual:
  {issue.get('actual', 'n/a')}

━━━ REPRODUCTION STEPS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{reproduction_block}

━━━ NETWORK EVIDENCE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{har_block}

━━━ CONSOLE ERRORS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{console_block}

━━━ DOM SNAPSHOT (broken element) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{dom_block}

━━━ SCREENSHOTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before: {screenshot_before}
After:  {screenshot_after}

━━━ LIKELY ROOT CAUSE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{issue.get('likelyRootCause') or 'Inspect the failing request and UI state handler.'}

━━━ VIOLATED BUSINESS RULE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{violated_rule}

━━━ ACCEPTANCE CRITERIA (must all pass before closing) ━━━━━━━━━━━

{ac_block}

━━━ IMPLEMENTATION RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Inspect the existing implementation of this flow before changing anything.
2. Reproduce the issue using the steps above to confirm you understand it.
3. Fix the root cause, not just the symptom described above.
4. Preserve the current UI/UX unless a change is required to fix the bug.
5. Do not rewrite unrelated components or add unnecessary abstractions.
6. Handle failure and success paths separately — never show a success state for a failed request.
7. Add or update a regression test for this behavior if the project has a test suite.
8. Verify the acceptance criteria above pass after your fix before committing.{cursor_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generated by Casefile — adaptive web auditor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    return prompt


# --- planner.js ---
log_planner = make_logger('planner')

PLANNER_SYSTEM_PROMPT = """You are the planning layer of Casefile, an adaptive web application auditor.
You do not control the browser directly - you choose which already-discovered action to
investigate next, from the candidate list you are given. You never invent actions that
aren't in the candidate list. Favor actions that exercise real business workflows (create,
save, submit, edit, delete, invite, login) over static/informational pages. Avoid repeating
an action id already listed under "already explored". Respond with strict JSON only."""

PLANNER_BATCH_SYSTEM_PROMPT = """You are the planning layer of Casefile, an adaptive web application auditor.
You do not control the browser directly - you choose an ORDERED BATCH of already-discovered
actions to investigate next, from the candidate list you are given, most valuable first. You
never invent actions that aren't in the candidate list. Favor actions that exercise real
business workflows (create, save, submit, edit, delete, invite, login) over static/informational
pages, and prefer diversity (don't just return five buttons on the same page if others are
available). Respond with strict JSON only."""

def build_planner_user_prompt(app_map, candidates, recent_findings, business_rules, actions_remaining):
    candidate_actions = [{
        'id': c.get('id'),
        'page': c.get('pageUrl'),
        'kind': c.get('kind'),
        'label': c.get('label'),
        'priority_hint': c.get('priority')
    } for c in candidates]
    
    instructions = 'Pick ONE candidate action id to investigate next, and say why.'
    if business_rules and business_rules.get('cursorContext'):
        instructions += f"\n\n[CURSOR IDE CONTEXT]\nPay close attention to this context from the developer: {business_rules.get('cursorContext')}"
        
    return json.dumps({
        'instructions': instructions,
        'app_map': app_map,
        'candidate_actions': candidate_actions,
        'recent_findings': recent_findings[-5:] if recent_findings else [],
        'business_rules': business_rules or None,
        'actions_remaining_in_budget': actions_remaining,
        'response_schema': { 'action_id': 'string (must match a candidate id)', 'reason': 'string, one sentence' }
    }, indent=2)

def build_planner_batch_user_prompt(app_map, candidates, recent_findings, business_rules, batch_size, actions_remaining):
    candidate_actions = [{
        'id': c.get('id'),
        'page': c.get('pageUrl'),
        'kind': c.get('kind'),
        'label': c.get('label'),
        'priority_hint': c.get('priority')
    } for c in candidates]
    
    instructions = f"Return up to {batch_size} candidate action ids, ordered from most to least valuable to investigate next."
    if business_rules and business_rules.get('cursorContext'):
        instructions += f"\n\n[CURSOR IDE CONTEXT]\nPay close attention to this context from the developer: {business_rules.get('cursorContext')}"
        
    return json.dumps({
        'instructions': instructions,
        'app_map': app_map,
        'candidate_actions': candidate_actions,
        'recent_findings': recent_findings[-5:] if recent_findings else [],
        'business_rules': business_rules or None,
        'actions_remaining_in_budget': actions_remaining,
        'response_schema': { 'action_ids': f"array of up to {batch_size} candidate id strings, ordered", 'reason': 'string, one sentence' }
    }, indent=2)

async def plan_next_action(app_map, candidates, recent_findings, business_rules, actions_remaining):
    if not candidates:
        return None

    if is_configured() and len(candidates) > 1:
        result = await generate_json(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=build_planner_user_prompt(app_map, candidates, recent_findings, business_rules, actions_remaining)
        )
        if result and result.get('action_id'):
            chosen = next((c for c in candidates if c.get('id') == result['action_id']), None)
            if chosen:
                return { 'action': chosen, 'reason': result.get('reason', 'Chosen by Gemini planner'), 'source': 'gemini' }
            log_planner.debug(f"Gemini chose an unknown action id \"{result['action_id']}\" - falling back to priority queue.")

    sorted_candidates = sorted(candidates, key=lambda x: x.get('priority', 0), reverse=True)
    return { 'action': sorted_candidates[0], 'reason': 'Highest priority unexplored action (deterministic)', 'source': 'heuristic' }

async def plan_batch(app_map, candidates, recent_findings, business_rules, actions_remaining, batch_size=5):
    if not candidates:
        return { 'queue': [], 'source': 'none', 'reason': 'No candidates remaining.' }

    if is_configured() and len(candidates) > 1:
        result = await generate_json(
            system_prompt=PLANNER_BATCH_SYSTEM_PROMPT,
            user_prompt=build_planner_batch_user_prompt(app_map, candidates, recent_findings, business_rules, batch_size, actions_remaining)
        )
        if result and isinstance(result.get('action_ids'), list) and len(result['action_ids']) > 0:
            valid_ids = [aid for aid in result['action_ids'] if any(c.get('id') == aid for c in candidates)]
            if valid_ids:
                return { 'queue': valid_ids[:batch_size], 'source': 'gemini', 'reason': result.get('reason', 'Batch chosen by Gemini planner') }
        log_planner.debug('Gemini batch plan unusable - falling back to priority queue.')

    sorted_candidates = sorted(candidates, key=lambda x: x.get('priority', 0), reverse=True)[:batch_size]
    return { 'queue': [c.get('id') for c in sorted_candidates], 'source': 'heuristic', 'reason': 'Highest priority unexplored actions (deterministic)' }
