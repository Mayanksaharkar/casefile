import os
import json
import hashlib
import time
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import logging

from src.intelligence import run_instruction_loop
from src.utils import make_logger

log = make_logger('browser_engine')

MAX_LOG_ENTRIES = 1500

_cachedAxeSource = None

def getAxeSource() -> str:
    global _cachedAxeSource
    if _cachedAxeSource is None:
        # Fallback path if axe-core cannot be resolved via require in JS
        # Assuming we can read it from a local node_modules or equivalent
        axe_path = os.path.join(os.getcwd(), 'node_modules', 'axe-core', 'axe.min.js')
        try:
            with open(axe_path, 'r', encoding='utf-8') as f:
                _cachedAxeSource = f.read()
        except FileNotFoundError:
            _cachedAxeSource = "/* axe-core not found */"
    return _cachedAxeSource

DANGEROUS_KEYWORDS = [
    'delete', 'remove', 'destroy', 'cancel subscription', 'deactivate',
    'pay', 'charge', 'checkout', 'purchase', 'send invite', 'send email',
    'wipe', 'reset all', 'permanently',
]

def isDangerous(label: str) -> bool:
    lower = (label or '').lower()
    return any(kw in lower for kw in DANGEROUS_KEYWORDS)

def hashState(url: str, domSignature: str) -> str:
    data = f"{url}::{domSignature}".encode('utf-8')
    return hashlib.sha1(data).hexdigest()[:16]

class BrowserDriver:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.consoleLog: List[Dict[str, Any]] = []
        self.networkLog: List[Dict[str, Any]] = []
        self.tracingStarted = False
        self._ownsBrowser = True

    async def launch(self, storageState=None):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self._ownsBrowser = True
        return await self._createContext(storageState)

    async def attach(self, browser: Browser, storageState=None):
        self.browser = browser
        self._ownsBrowser = False
        return await self._createContext(storageState)

    async def spawnSibling(self, storageState=None):
        sibling = BrowserDriver(headless=self.headless)
        await sibling.attach(self.browser, storageState=storageState)
        return sibling

    async def _createContext(self, storageState=None):
        context_options = {"viewport": {"width": 1920, "height": 1080}}
        if storageState:
            context_options["storage_state"] = storageState
        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()
        self._attachListeners()
        return self

    async def startTracing(self):
        await self.context.tracing.start(screenshots=True, snapshots=True, sources=False)
        self.tracingStarted = True

    async def stopTracing(self, destPath: str):
        if not self.tracingStarted:
            return None
        await self.context.tracing.stop(path=destPath)
        self.tracingStarted = False
        return destPath

    def _pushConsole(self, entry: dict):
        if len(self.consoleLog) < MAX_LOG_ENTRIES:
            self.consoleLog.append(entry)

    def _pushNetwork(self, entry: dict):
        if len(self.networkLog) < MAX_LOG_ENTRIES:
            self.networkLog.append(entry)

    def _attachListeners(self):
        self._captured_responses = getattr(self, '_captured_responses', [])

        def on_console(msg):
            self._pushConsole({
                "type": msg.type,
                "text": msg.text,
                "at": int(time.time() * 1000)
            })
        self.page.on("console", on_console)

        def on_pageerror(err):
            self._pushConsole({
                "type": "error",
                "text": f"Uncaught exception: {err}",
                "at": int(time.time() * 1000)
            })
        self.page.on("pageerror", on_pageerror)

        async def on_response(response):
            try:
                request = response.request
                # Basic push for networkSummary
                self._pushNetwork({
                    "url": response.url,
                    "method": request.method,
                    "status": response.status,
                    "resourceType": request.resource_type,
                    "at": int(time.time() * 1000)
                })

                # Capture detailed API responses for Phase 7
                if request.resource_type in ('fetch', 'xhr'):
                    req_body = request.post_data
                    resp_body = None
                    if response.status < 400:
                        try:
                            # Only parse JSON or text bodies
                            ct = response.headers.get('content-type', '')
                            if 'json' in ct or 'text' in ct:
                                resp_body = await response.text()
                        except Exception:
                            pass
                    self._captured_responses.append({
                        'url': response.url,
                        'method': request.method,
                        'status': response.status,
                        'requestBody': req_body,
                        'responseBody': resp_body,
                        'responseTimeMs': 0  # To track properly we'd need request object timing
                    })
            except Exception:
                pass
        self.page.on("response", on_response)

        def on_requestfailed(request):
            failure_text = request.failure if request.failure else None
            self._pushNetwork({
                "url": request.url,
                "method": request.method,
                "status": 0,
                "resourceType": request.resource_type,
                "failure": failure_text,
                "at": int(time.time() * 1000)
            })
        self.page.on("requestfailed", on_requestfailed)

    def consoleSince(self, markerIndex: int):
        return self.consoleLog[markerIndex:]

    def networkSince(self, markerIndex: int):
        return self.networkLog[markerIndex:]

    def clearLogs(self):
        self.consoleLog = []
        self.networkLog = []

    def markers(self):
        return {"consoleIndex": len(self.consoleLog), "networkIndex": len(self.networkLog)}

    async def goto(self, url: str, **options):
        opts = {"wait_until": "domcontentloaded", "timeout": 15000}
        opts.update(options)
        await self.page.goto(url, **opts)
        await self._settle()

    async def _settle(self):
        await self.page.wait_for_timeout(400)

    async def currentUrl(self):
        return self.page.url

    async def title(self):
        try:
            return await self.page.title()
        except Exception:
            return ""

    async def accessibilitySnapshot(self):
        try:
            return await self.page.accessibility.snapshot(interesting_only=True)
        except Exception:
            return None

    async def getInteractiveElements(self):
        js_code = """
        () => {
          function labelFor(el) {
            return (
              el.getAttribute('aria-label') ||
              el.innerText ||
              el.getAttribute('placeholder') ||
              el.getAttribute('name') ||
              el.getAttribute('title') ||
              ''
            ).trim().slice(0, 120);
          }

          function cssPathFor(el) {
            if (el.id) return `#${CSS.escape(el.id)}`;
            const parts = [];
            let node = el;
            let depth = 0;
            while (node && node.nodeType === 1 && depth < 6) {
              let selector = node.tagName.toLowerCase();
              if (node.className && typeof node.className === 'string') {
                const classNames = node.className.trim().split(/\\s+/).filter(Boolean).slice(0, 2);
                for (const cls of classNames) selector += `.${CSS.escape(cls)}`;
              }
              const parent = node.parentElement;
              if (parent) {
                const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
                if (siblings.length > 1) selector += `:nth-of-type(${siblings.indexOf(node) + 1})`;
              }
              parts.unshift(selector);
              node = parent;
              depth += 1;
            }
            return parts.join(' > ');
          }

          function visible(el) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          }

          const links = Array.from(document.querySelectorAll('a[href]'))
            .filter(visible)
            .map((a) => ({ href: a.getAttribute('href'), text: labelFor(a) }));

          const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]'))
            .filter(visible)
            .map((btn) => ({ selector: cssPathFor(btn), label: labelFor(btn) }));

          const forms = Array.from(document.querySelectorAll('form')).map((form) => ({
            selector: cssPathFor(form),
            fields: Array.from(form.querySelectorAll('input, textarea, select'))
              .filter(visible)
              .map((field) => ({
                selector: cssPathFor(field),
                type: field.tagName.toLowerCase() === 'select' ? 'select' : field.type || 'text',
                name: field.getAttribute('name') || '',
                label: labelFor(field),
                required: field.required || false,
              })),
          }));

          return { links, buttons, forms, bodyTextSignature: document.body.innerText.slice(0, 2000) };
        }
        """
        return await self.page.evaluate(js_code)

    async def computeStateHash(self, elements=None):
        url = await self.currentUrl()
        els = elements if elements is not None else await self.getInteractiveElements()
        return hashState(url, els.get("bodyTextSignature", ""))

    async def screenshotBuffer(self):
        return await self.page.screenshot(full_page=False)

    async def click(self, selector: str, force: bool = False):
        locator = self.page.locator(selector).first
        try:
            await locator.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        await locator.click(timeout=5000, force=force)

    async def fill(self, selector: str, value: Any):
        locator = self.page.locator(selector).first
        try:
            await locator.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        await locator.fill(str(value), timeout=5000)

    async def selectOption(self, selector: str, value: Any):
        locator = self.page.locator(selector).first
        await locator.select_option(value, timeout=5000)

    async def selectFirstOption(self, selector: str):
        locator = self.page.locator(selector).first
        try:
            await locator.select_option(index=1, timeout=3000)
        except Exception:
            try:
                await locator.select_option(index=0, timeout=3000)
            except Exception:
                pass

    async def count(self, selector: str):
        return await self.page.locator(selector).count()

    async def waitBriefly(self, ms: int = 600):
        await self.page.wait_for_timeout(ms)

    async def runAxe(self):
        try:
            await self.page.evaluate(getAxeSource())
            results = await self.page.evaluate("""
                async () => {
                    return await axe.run(document, { resultTypes: ['violations'] });
                }
            """)
            return results.get("violations", [])
        except Exception as err:
            log.warning(f"axe run failed: {err}")
            return []

    def isDangerous(self, label: str) -> bool:
        return isDangerous(label)

    async def close(self):
        try:
            if self.context:
                await self.context.close()
        except Exception as err:
            log.warning(f"Error closing context: {err}")
        if self._ownsBrowser:
            try:
                if self.browser:
                    await self.browser.close()
            except Exception as err:
                log.warning(f"Error closing browser: {err}")
            if self.playwright:
                try:
                    await self.playwright.stop()
                except Exception as err:
                    log.warning(f"Error stopping playwright: {err}")



    # Aliases for snake_case compatibility with orchestrator
    spawn_sibling = spawnSibling
    start_tracing = startTracing
    stop_tracing = stopTracing
    console_since = consoleSince
    network_since = networkSince
    clear_logs = clearLogs
    current_url = currentUrl
    accessibility_snapshot = accessibilitySnapshot
    get_interactive_elements = getInteractiveElements
    compute_state_hash = computeStateHash
    screenshot_buffer = screenshotBuffer
    select_option = selectOption
    select_first_option = selectFirstOption
    wait_briefly = waitBriefly
    run_axe = runAxe
    is_dangerous = isDangerous

def resolveStorageStatePath(profile: dict, repoPath: str) -> dict:
    if profile.get('storageStatePath') and repoPath and not os.path.isabs(profile['storageStatePath']):
        new_profile = profile.copy()
        new_profile['storageStatePath'] = os.path.join(repoPath, profile['storageStatePath'])
        return new_profile
    return profile

def isProfileLike(obj: dict) -> bool:
    if not obj:
        return False
    return bool(obj.get('storageState') or obj.get('storageStatePath') or obj.get('loginUrl'))

def resolve_auth_profiles(authOverride=None, credentialsFromRepo=None, repoPath: str = None) -> List[dict]:
    raw = None

    if authOverride and isinstance(authOverride.get('profiles'), list) and len(authOverride['profiles']) > 0:
        raw = authOverride['profiles']
    elif isProfileLike(authOverride):
        raw = [{**authOverride, 'name': authOverride.get('name', 'primary')}]
    elif credentialsFromRepo and isinstance(credentialsFromRepo.get('profiles'), list) and len(credentialsFromRepo['profiles']) > 0:
        raw = credentialsFromRepo['profiles']
    elif isProfileLike(credentialsFromRepo):
        raw = [{**credentialsFromRepo, 'name': credentialsFromRepo.get('name', 'primary')}]

    if not raw:
        return []

    resolved = []
    for i, profile in enumerate(raw):
        named = profile.copy()
        if not named.get('name'):
            named['name'] = 'primary' if i == 0 else f"user{i + 1}"
        resolved.append(resolveStorageStatePath(named, repoPath))
    return resolved

def load_storage_state(auth: dict) -> Optional[Any]:
    if not auth:
        return None
    if auth.get('storageState'):
        return auth['storageState']
    path = auth.get('storageStatePath')
    if path and os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as err:
            log.warning(f"Could not parse storage state at {path}: {err}")
            return None
    return None

def can_adaptive_login(auth: dict) -> bool:
    return bool(auth and auth.get('loginUrl') and auth.get('credentialsText'))

def can_auto_login_form(auth: dict) -> bool:
    return bool(
        auth and
        auth.get('loginUrl') and
        auth.get('usernameSelector') and
        auth.get('passwordSelector') and
        auth.get('submitSelector') and
        auth.get('username') and
        auth.get('password')
    )

async def perform_adaptive_login(driver: BrowserDriver, auth: dict, onStep=None):
    log.info(f"Attempting adaptive login at {auth.get('loginUrl')}")
    await driver.goto(auth['loginUrl'])
    return await run_instruction_loop(driver, {
        "instruction": (
            "Log in using the given credentials. Fill in whatever fields are needed (email/username, "
            "password, or a one-time code) and submit - this may take more than one screen, e.g. enter an "
            "email first, submit, then enter a one-time code that appears next."
        ),
        "extraContext": {"credentials": auth.get('credentialsText')},
        "maxSteps": auth.get('maxSteps', 6),
        "onStep": onStep
    })

async def perform_form_login(driver: BrowserDriver, auth: dict):
    log.info(f"Attempting form login at {auth.get('loginUrl')}")
    await driver.goto(auth['loginUrl'])
    await driver.fill(auth['usernameSelector'], auth['username'])
    await driver.fill(auth['passwordSelector'], auth['password'])
    await driver.click(auth['submitSelector'])
    await driver.waitBriefly(1200)

