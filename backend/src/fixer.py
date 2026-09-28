import asyncio
import os
import sys
import json
import logging
import urllib.request
import urllib.error
import time
import secrets
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# Assume these will be available in the Python backend
try:
    from ..utils import make_logger
except ImportError:
    def make_logger(name):
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

try:
    from ..browser.playwright_driver import BrowserDriver
    from ..intelligence import action_agent, bug_judge
    from ..analyzers import console_analyzer, network_analyzer
except ImportError:
    # placeholders for imports if they are not yet translated
    pass

log_coding_agent = make_logger('codingAgent')
log_dev_server = make_logger('devServerManager')
log_git = make_logger('gitWorkspace')
log_pr = make_logger('prCreator')
log_orchestrator = make_logger('fixOrchestrator')


# --- codingAgent.py equivalent ---

def build_args(prompt):
    """
    UNVERIFIED IN THIS BUILD: I don't have a live Claude Code installation
    to test this invocation against, so the exact CLI flags below are my
    best understanding of Claude Code's non-interactive ("print") mode as
    of writing, not something I've run. Two env vars let you correct this
    without touching code:
      CLAUDE_CODE_COMMAND - the binary to run (default "claude")
      CLAUDE_CODE_EXTRA_ARGS - space-separated extra args appended as-is
    If the exact flags for non-interactive, auto-accepting invocation have
    changed, check `claude --help` and adjust CLAUDE_CODE_EXTRA_ARGS or the
    ARGS array below.

    --dangerously-skip-permissions bypasses Claude Code's interactive
    edit-approval prompts, which is required for unattended use - this is
    only safe here because it runs inside a disposable git worktree (see
    gitWorkspace.js), never the user's real working directory.
    """
    args = ['-p', prompt, '--dangerously-skip-permissions']
    extra = os.environ.get('CLAUDE_CODE_EXTRA_ARGS')
    if extra:
        args.extend([arg for arg in extra.split(' ') if arg])
    return args

async def run_coding_agent_fix(cwd, prompt, timeout_ms=600000, on_output=None):
    """
    Runs the coding agent against `cwd` (must be an isolated worktree) with
    a single fix prompt, non-interactively. Resolves with the agent's
    output either way - callers decide success by checking for actual file
    changes afterward (gitWorkspace.hasChanges), not just exit code, since
    an agent can exit 0 having decided no change was needed.
    """
    command = os.environ.get('CLAUDE_CODE_COMMAND', 'claude')
    args = build_args(prompt)
    
    try:
        process = await asyncio.create_subprocess_exec(
            command, *args,
            cwd=cwd,
            env=os.environ.copy(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    except Exception as err:
        return {"success": False, "output": "", "error": f"Could not start \"{command}\": {str(err)}"}

    output_chunks = []

    async def read_stream(stream):
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            text = chunk.decode(errors='replace')
            output_chunks.append(text)
            if on_output:
                on_output(text)

    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(process.stdout),
                read_stream(process.stderr),
                process.wait()
            ),
            timeout=timeout_ms / 1000.0
        )
        code = process.returncode
        output = "".join(output_chunks)
        log_coding_agent.info(f"Coding agent exited with code {code}")
        return {
            "success": code == 0,
            "output": output,
            "error": None if code == 0 else f"Coding agent exited with code {code}."
        }
    except asyncio.TimeoutError:
        try:
            process.terminate()
            await asyncio.sleep(0.1)
            if process.returncode is None:
                process.kill()
        except Exception:
            pass
        output = "".join(output_chunks)
        return {
            "success": False,
            "output": output,
            "error": f"Coding agent timed out after {round(timeout_ms / 1000)}s."
        }
    except Exception as err:
        output = "".join(output_chunks)
        return {
            "success": False,
            "output": output,
            "error": f"Could not run \"{command}\": {str(err)}. Is Claude Code installed and on PATH? Set CLAUDE_CODE_COMMAND in backend/.env if it's installed under a different name."
        }


# --- devServerManager.py equivalent ---

async def wait_for_port(url, timeout_ms=45000, interval_ms=1000):
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method='GET')
            # Use a brief timeout for the request itself
            with urllib.request.urlopen(req, timeout=3.0) as response:
                if response:
                    return True
        except urllib.error.HTTPError:
            return True # Any HTTP response (even 4xx/5xx) means something is listening
        except Exception:
            pass # Keep polling
        await asyncio.sleep(interval_ms / 1000.0)
    return False

async def start_dev_server(cwd, start_command, port, ready_url=None):
    """
    Starts `start_command` (e.g. "npm run dev") inside `cwd` with PORT set
    to an unused verification port, and waits for it to actually accept
    connections before returning. Runs detached so the whole process group
    (a dev command's real server is often a child of the shell it spawns)
    can be killed together on stop().
    """
    parts = start_command.split(' ')
    cmd = parts[0]
    args = parts[1:]
    is_windows = sys.platform == 'win32'
    
    env = os.environ.copy()
    env['PORT'] = str(port)
    
    # We use start_new_session (equivalent to detached: true on Unix)
    process = await asyncio.create_subprocess_exec(
        cmd, *args,
        cwd=cwd,
        env=env,
        start_new_session=not is_windows,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    output_chunks = []
    
    async def read_stream(stream):
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            output_chunks.append(chunk.decode(errors='replace'))

    # Start reading streams in the background
    asyncio.create_task(read_stream(process.stdout))
    asyncio.create_task(read_stream(process.stderr))
    
    url = ready_url or f"http://localhost:{port}"
    ready = await wait_for_port(url, timeout_ms=45000)
    
    if not ready:
        await stop_dev_server(process)
        output = "".join(output_chunks)
        raise Exception(f"Dev server did not respond at {url} within 45s. Last output:\n{output[-2000:]}")
    
    log_dev_server.info(f"Verification dev server ready at {url}")
    return {"process": process, "port": port, "url": url}

async def stop_dev_server(child):
    if not child or child.returncode is not None:
        return
    try:
        if sys.platform != 'win32':
            import os
            import signal
            os.killpg(os.getpgid(child.pid), signal.SIGTERM) # negative pid = whole process group equivalent
        else:
            child.terminate()
    except Exception as err:
        log_dev_server.warning(f"Could not stop dev server cleanly: {str(err)}")
        try:
            if sys.platform != 'win32':
                os.killpg(os.getpgid(child.pid), signal.SIGKILL)
            else:
                child.kill()
        except Exception:
            pass


# --- gitWorkspace.py equivalent ---

async def git(args, cwd):
    try:
        process = await asyncio.create_subprocess_exec(
            'git', *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=20 * 1024 * 1024
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode().strip() if stderr else f"Exit code {process.returncode}"
            raise Exception(f"git {' '.join(args)} failed: {detail}")
        return stdout.decode().strip()
    except Exception as err:
        if isinstance(err, Exception) and not str(err).startswith("git"):
            raise Exception(f"git {' '.join(args)} failed: {str(err)}")
        raise

async def is_git_repo(repo_path):
    try:
        result = await git(['rev-parse', '--is-inside-work-tree'], repo_path)
        return result == 'true'
    except Exception:
        return False

def parse_github_remote(url):
    """Parses github.com/owner/repo out of either an https or ssh remote URL."""
    if not url:
        return None
    match = re.search(r'github\.com[/:]([^/]+)/([^/.]+?)(\.git)?$', url)
    if not match:
        return None
    return {"owner": match.group(1), "repo": match.group(2)}

async def get_remote_owner_repo(repo_path, remote='origin'):
    try:
        url = await git(['remote', 'get-url', remote], repo_path)
        return parse_github_remote(url)
    except Exception:
        return None

async def get_default_branch(repo_path):
    try:
        ref = await git(['symbolic-ref', '--short', 'HEAD'], repo_path)
        return ref
    except Exception:
        return 'main'

def worktrees_root(repo_path):
    return os.path.join(repo_path, '.casefile-worktrees')

def slugify(text):
    text = str(text).lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text[:40]

async def create_fix_worktree(repo_path, issue_id, issue_title):
    """
    Creates a fresh, isolated checkout on a brand-new branch, off the
    current HEAD - not a copy of uncommitted changes in the main working
    tree (worktrees are independent; commit or stash first if you want the
    fixer to see in-progress edits). This is the ONLY directory the coding
    agent is ever given as its working directory.
    """
    root = worktrees_root(repo_path)
    os.makedirs(root, exist_ok=True)
    
    suffix = secrets.token_hex(3)
    branch = f"casefile-fix/{issue_id}-{slugify(issue_title or 'fix')}-{suffix}"
    worktree_dir = os.path.join(root, f"{issue_id}-{suffix}")
    
    await git(['worktree', 'add', '-b', branch, worktree_dir, 'HEAD'], repo_path)
    log_git.info(f"Created worktree {worktree_dir} on branch {branch}")
    return {"worktreeDir": worktree_dir, "branch": branch}

async def has_changes(worktree_dir):
    try:
        status = await git(['status', '--porcelain'], worktree_dir)
        return len(status) > 0
    except Exception:
        return False

async def commit_all(worktree_dir, message):
    await git(['add', '-A'], worktree_dir)
    await git(['commit', '-m', message], worktree_dir)

async def push_branch(worktree_dir, branch, remote='origin'):
    await git(['push', '-u', remote, branch], worktree_dir)

async def remove_worktree(repo_path, worktree_dir):
    """Best-effort cleanup - never let a failure here mask the real result of a fix attempt."""
    try:
        await git(['worktree', 'remove', worktree_dir, '--force'], repo_path)
    except Exception as err:
        log_git.warning(f"Could not remove worktree {worktree_dir}: {str(err)}")


# --- prCreator.py equivalent ---

def is_configured():
    return bool(os.environ.get('GITHUB_TOKEN'))

async def create_pull_request(owner, repo, branch, base_branch, title, body):
    if not is_configured():
        raise Exception('GITHUB_TOKEN is not set - cannot open a pull request automatically.')
    
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        'Authorization': f"Bearer {os.environ.get('GITHUB_TOKEN')}",
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    data = json.dumps({
        "title": title,
        "body": body,
        "head": branch,
        "base": base_branch
    }).encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        # Avoid blocking the event loop
        loop = asyncio.get_running_loop()
        def fetch():
            with urllib.request.urlopen(req) as response:
                return response.read(), response.status
        response_data, status = await loop.run_in_executor(None, fetch)
        resp_json = json.loads(response_data)
        log_pr.info(f"Opened PR {resp_json.get('html_url')}")
        return {"url": resp_json.get('html_url'), "number": resp_json.get('number')}
    except urllib.error.HTTPError as e:
        err_text = e.read().decode('utf-8')
        raise Exception(f"GitHub PR creation failed ({e.code}): {err_text[:500]}")

def build_pr_body(issue, fix_summary=None, evidence_note=None):
    category = issue.get('category', '')
    severity = issue.get('severity', '')
    confidence = round(float(issue.get('confidence', 0)) * 100)
    description = issue.get('description', '')
    route = issue.get('route', 'n/a')
    expected = issue.get('expected', 'n/a')
    actual = issue.get('actual', 'n/a')
    title = issue.get('title', '')
    
    fix = fix_summary or "Applied by Claude Code from the issue's fix prompt."
    verification = evidence_note or "Re-checked against a fresh dev server running this branch, using the same detection logic that originally found the issue."
    
    return f"""## Casefile fix: {title}

**Category:** {category} · **Severity:** {severity} · **Confidence:** {confidence}%

### Original issue
{description}

**Route:** {route}

**Expected:** {expected}
**Actual (at time of audit):** {actual}

### Fix
{fix}

### Verification
{verification}

---
Opened automatically by Casefile. This PR was never auto-merged - please review before merging, same as any other PR."""


# --- verifier.py equivalent ---

def rewrite_origin(original_url, new_origin):
    """Swaps the origin (scheme+host+port) of a URL for the verification server's origin, keeping the path."""
    try:
        parsed_original = urlparse(original_url)
        parsed_target = urlparse(new_origin)
        # Reconstruct with target protocol and host
        new_url = urlunparse((
            parsed_target.scheme,
            parsed_target.netloc,
            parsed_original.path,
            parsed_original.params,
            parsed_original.query,
            parsed_original.fragment
        ))
        return new_url
    except Exception:
        return new_origin

def is_verifiable(issue):
    """Cross-user issues need a full multi-profile flow re-run to verify, which this pass doesn't automate."""
    evidence = issue.get('evidence', {})
    if evidence and evidence.get('crossUserFlow'):
        return False
    return True

async def verify_issue_fixed(issue, verify_origin, headless=True):
    if not is_verifiable(issue):
        return {"fixed": None, "explanation": "Cross-user flow issues are not automatically re-verifiable yet - review manually."}
    
    try:
        driver = BrowserDriver(headless=headless)
    except NameError:
        # Fallback if BrowserDriver is not imported correctly due to missing modules yet
        return {"fixed": None, "explanation": "BrowserDriver not implemented in this build."}
        
    await driver.launch()
    
    try:
        route = rewrite_origin(issue.get('route', ''), verify_origin)
        
        if issue.get('category') == 'ACCESSIBILITY' and issue.get('ruleId'):
            await driver.goto(route)
            violations = await driver.run_axe()
            rule_id = issue.get('ruleId')
            still_violating = any(v.get('id') == rule_id for v in violations)
            return {
                "fixed": not still_violating,
                "explanation": f"The \"{rule_id}\" axe rule is still violated on {route}." if still_violating else f"The \"{rule_id}\" axe rule no longer fires on {route}."
            }
            
        # Action-based issue: replay the reproduction steps as an instruction,
        # then re-run the exact same deterministic checks that originally
        # flagged it - this is the same yardstick, not a new one.
        await driver.goto(route)
        markers = driver.markers()
        steps = issue.get('reproductionSteps', [])
        instruction = ". ".join(steps) if steps else issue.get('title', '')
        await action_agent.run_instruction_loop(driver, instruction=instruction, max_steps=5)
        await driver.wait_briefly(700)
        
        console_events = driver.console_since(markers.get('consoleIndex', 0))
        network_events = driver.network_since(markers.get('networkIndex', 0))
        try:
            elements = await driver.get_interactive_elements()
        except Exception:
            elements = {"bodyTextSignature": ""}
            
        console_summary = console_analyzer.summarize(console_events)
        network_summary = network_analyzer.summarize(network_events)
        ui_api_mismatch = network_analyzer.find_ui_api_mismatch(network_events, elements.get('bodyTextSignature', ''))
        
        still_suspicious = (console_summary.get('errorCount', 0) > 0) or (network_summary.get('failedCount', 0) > 0) or bool(ui_api_mismatch)
        
        if not still_suspicious:
            return {
                "fixed": True,
                "explanation": "Replaying the original reproduction steps no longer triggers the console/network anomaly that was originally flagged."
            }
            
        # Something is still off - confirm it's genuinely the same class of
        # problem (not unrelated noise) before calling the fix unsuccessful.
        verdict = await bug_judge.evaluate_evidence(
            action={"kind": "verification-replay", "label": issue.get('title', ''), "page": route},
            expected=issue.get('expected'),
            actual="Replaying the original reproduction steps.",
            evidence={
                "consoleErrorCount": console_summary.get('errorCount', 0),
                "consoleErrors": console_summary.get('errors', []),
                "networkSummary": network_summary.get('failed', []),
                "uiApiMismatch": bool(ui_api_mismatch)
            },
            business_rules=None
        )
        
        is_issue = verdict and verdict.get('is_issue')
        return {
            "fixed": not is_issue,
            "explanation": f"The issue still reproduces: {verdict.get('description', 'anomaly persists.')}" if is_issue else "The original anomaly no longer reproduces."
        }
    finally:
        await driver.close()


# --- fixOrchestrator.py equivalent ---

MAX_ATTEMPTS = 2

async def attempt_fix(
    issue,
    repo_path,
    start_command='npm run dev',
    verify_port=4310,
    auto_pr=False,
    headless=True,
    on_log=None,
    on_update=None,
    cursor_context=None
):
    """
    Attempts to fix ONE issue: isolated worktree -> coding agent -> live
    verification -> (if verified) commit -> (if autoPR) push + open a PR.
    Never merges anything, ever - that boundary doesn't move regardless of
    the autoPR setting. autoPR only controls whether the verified fix gets
    pushed and turned into a PR automatically, or left as a local, verified,
    committed branch for the user to push themselves.
    """
    import datetime
    
    def report(msg):
        log_orchestrator.info(msg)
        if on_log:
            on_log(msg)
            
    def update(patch):
        if on_update:
            on_update(patch)
            
    if not is_verifiable(issue):
        update({"status": "failed", "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
        report("This issue type (cross-user flow) cannot be automatically re-verified yet - use the fix prompt manually instead.")
        return
        
    if not repo_path:
        update({"status": "failed", "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
        report("No repository path was given for this audit - the fixer needs one to make changes.")
        return
        
    try:
        is_repo = await is_git_repo(repo_path)
    except Exception:
        is_repo = False
        
    if not is_repo:
        update({"status": "failed", "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
        report(f"{repo_path} does not look like a git repository - the fixer requires one.")
        return
        
    worktree_dir = None
    branch = None
    try:
        report("Creating an isolated git worktree on a new branch...")
        res = await create_fix_worktree(repo_path, issue.get('id', ''), issue.get('title', ''))
        worktree_dir = res['worktreeDir']
        branch = res['branch']
        update({"branch": branch, "worktreeDir": worktree_dir})
    except Exception as err:
        update({"status": "failed", "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
        report(f"Could not create a worktree: {str(err)}")
        return
        
    prompt = issue.get('fixPrompt', '')
    if cursor_context:
        prompt += f"\n\n[CURSOR IDE CONTEXT]\nThe developer's IDE has provided the following context for this audit:\n{cursor_context}\n"
    dev_server = None
    last_verdict = None
    
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            update({"attempts": attempt})
            report(f"Attempt {attempt}/{MAX_ATTEMPTS}: running the coding agent (this can take a few minutes)...")
            
            last_reported_at = 0
            
            def handle_output(chunk):
                nonlocal last_reported_at
                now = time.time()
                if now - last_reported_at > 4.0:
                    last_reported_at = now
                    lines = [line for line in chunk.strip().split('\n') if line]
                    if lines:
                        preview = lines[-1]
                        report(f"Coding agent: {preview[:160]}")
                        
            agent_result = await run_coding_agent_fix(
                cwd=worktree_dir,
                prompt=prompt,
                on_output=handle_output
            )
            
            if not agent_result.get('success'):
                report(f"Coding agent did not exit cleanly: {agent_result.get('error', 'unknown error')}")
                
            try:
                changed = await has_changes(worktree_dir)
            except Exception:
                changed = False
                
            if not changed:
                report("The coding agent made no file changes - stopping.")
                update({"status": "failed", "verified": False, "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
                return
                
            report("Changes detected. Starting a verification dev server on the fixed branch...")
            
            try:
                dev_server = await start_dev_server(cwd=worktree_dir, start_command=start_command, port=verify_port)
            except Exception as err:
                report(f"Could not start a verification server: {str(err)}")
                update({"status": "failed", "verified": None, "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
                return
                
            report(f"Re-checking the original issue against {dev_server['url']}...")
            last_verdict = await verify_issue_fixed(issue=issue, verify_origin=dev_server['url'], headless=headless)
            await stop_dev_server(dev_server['process'])
            dev_server = None
            
            if last_verdict.get('fixed') is True:
                report(f"Verified fixed: {last_verdict.get('explanation')}")
                update({"verified": True})
                break
                
            report(f"Not verified as fixed on attempt {attempt}: {last_verdict.get('explanation')}")
            if attempt < MAX_ATTEMPTS:
                prompt = (f"{issue.get('fixPrompt', '')}\n\n"
                          f"A previous attempt did not resolve this issue: {last_verdict.get('explanation')}\n"
                          "Inspect the actual current implementation before changing it again - do not repeat the same change.")
                          
        if not last_verdict or last_verdict.get('fixed') is not True:
            update({
                "status": "failed",
                "verified": last_verdict.get('fixed') if last_verdict else None,
                "completedAt": datetime.datetime.utcnow().isoformat() + "Z"
            })
            report(f"Giving up after {MAX_ATTEMPTS} attempt(s). The unverified changes are left on branch \"{branch}\" ({worktree_dir}) for manual review.")
            return
            
        try:
            changed_after = await has_changes(worktree_dir)
        except Exception:
            changed_after = False
            
        if changed_after:
            report("Committing the fix...")
            await commit_all(worktree_dir, f"Fix: {issue.get('title', '')} (Casefile {issue.get('id', '')})")
            
        if not auto_pr:
            update({"status": "succeeded", "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
            report(f"Fix verified and committed locally on branch \"{branch}\". Auto-PR is off - push and open a PR yourself when ready.")
            return
            
        report("Auto-PR is on - pushing and opening a pull request...")
        remote_info = await get_remote_owner_repo(repo_path)
        if not remote_info:
            update({"status": "succeeded", "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
            report(f"Fix verified and committed on branch \"{branch}\", but no GitHub remote was found - push and open a PR yourself.")
            return
            
        if not is_configured():
            update({"status": "succeeded", "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
            report(f"Fix verified and committed on branch \"{branch}\", but GITHUB_TOKEN is not set - push and open a PR yourself.")
            return
            
        await push_branch(worktree_dir, branch)
        base_branch = await get_default_branch(repo_path)
        pr = await create_pull_request(
            owner=remote_info['owner'],
            repo=remote_info['repo'],
            branch=branch,
            base_branch=base_branch,
            title=f"Fix: {issue.get('title', '')}",
            body=build_pr_body(issue)
        )
        
        update({"status": "succeeded", "prUrl": pr.get('url'), "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
        report(f"Opened pull request: {pr.get('url')}")
        
    except Exception as err:
        if dev_server:
            try:
                await stop_dev_server(dev_server['process'])
            except Exception:
                pass
        update({"status": "failed", "completedAt": datetime.datetime.utcnow().isoformat() + "Z"})
        report(f"Fix attempt failed: {str(err)}")
