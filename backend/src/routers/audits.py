import os
import uuid
import math
import json
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from .. import storage
import src.orchestrator as audit_controller
import src.orchestrator as event_bus
import src.fixer as fix_orchestrator
from ..utils import make_logger
from ..config import load_audit_config

log = make_logger('routes:audits')
router = APIRouter()

def is_valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ["http", "https"]
    except Exception:
        return False

class AuditRequest(BaseModel):
    targetUrl: Optional[str] = None
    repoPath: Optional[str] = None
    budget: Optional[float] = None
    safeMode: Optional[bool] = None
    maxPages: Optional[float] = None
    compareAgainstId: Optional[str] = None
    testCaseId: Optional[str] = None
    auth: Optional[Dict[str, Any]] = None

class FixRequest(BaseModel):
    startCommand: Optional[str] = None
    verifyPort: Optional[float] = None
    autoPR: Optional[bool] = None

@router.post("/", status_code=202)
async def create_audit(background_tasks: BackgroundTasks, req_body: Optional[AuditRequest] = None):
    if req_body is None:
        req_body = AuditRequest()
        
    target_url = req_body.targetUrl
    if not target_url or not is_valid_url(target_url):
        raise HTTPException(
            status_code=400,
            detail="targetUrl is required and must be a valid http(s) URL, e.g. http://localhost:3000"
        )
    
    audit_id = str(uuid.uuid4())
    
    repo_path = req_body.repoPath.strip() if req_body.repoPath and str(req_body.repoPath).strip() else None
    
    budget_val = req_body.budget
    if budget_val is not None and math.isfinite(float(budget_val)) and float(budget_val) > 0:
        budget = min(float(budget_val), 200.0)
    else:
        budget = 40.0
        
    safe_mode = req_body.safeMode is not False
    
    max_pages_val = req_body.maxPages
    if max_pages_val is not None and math.isfinite(float(max_pages_val)) and float(max_pages_val) > 0:
        max_pages = min(float(max_pages_val), 60.0)
    else:
        max_pages = 15.0
        
    compare_against_id = req_body.compareAgainstId.strip() if req_body.compareAgainstId and str(req_body.compareAgainstId).strip() else None
    
    auth_val = req_body.auth
    auth = auth_val if auth_val and isinstance(auth_val, dict) else None

    options = {
        "id": audit_id,
        "targetUrl": target_url,
        "repoPath": repo_path,
        "budget": budget,
        "safeMode": safe_mode,
        "maxPages": max_pages,
        "compareAgainstId": compare_against_id,
        "testCaseId": req_body.testCaseId,
        "auth": auth,
    }

    async def async_run_audit(opts):
        try:
            if asyncio.iscoroutinefunction(audit_controller.run_audit):
                await audit_controller.run_audit(opts)
            else:
                await asyncio.to_thread(audit_controller.run_audit, opts)
        except Exception as err:
            import traceback
            err_str = "".join(traceback.format_exception(type(err), err, err.__traceback__))
            log.error(f"Unhandled error running audit {opts['id']}: {err_str}")

    background_tasks.add_task(async_run_audit, options)
    return {"id": audit_id}


@router.get("/")
def list_audits():
    audits = storage.list_audits()
    result = []
    for a in audits:
        result.append({
            "id": a.get("id"),
            "targetUrl": a.get("targetUrl"),
            "status": a.get("status"),
            "phase": a.get("phase"),
            "startedAt": a.get("startedAt"),
            "completedAt": a.get("completedAt"),
            "summary": a.get("summary"),
            "progress": a.get("progress"),
        })
    return result


@router.get("/{id}")
def get_audit(id: str):
    state = storage.read_audit_state(id)
    if not state:
        raise HTTPException(status_code=404, detail="Audit not found")
    return state


@router.get("/{id}/stream")
async def stream_audit(id: str, request: Request):
    initial = storage.read_audit_state(id)
    if not initial:
        raise HTTPException(status_code=404, detail="Audit not found")

    async def event_generator():
        yield ServerSentEvent(event="state", data=json.dumps(initial))
        
        queue = asyncio.Queue()
        loop = asyncio.get_event_loop()
        
        def callback(event_type, payload):
            loop.call_soon_threadsafe(queue.put_nowait, (event_type, payload))

        unsubscribe = event_bus.subscribe(id, callback)
        
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_type, payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield ServerSentEvent(event=event_type, data=json.dumps(payload))
                except asyncio.TimeoutError:
                    yield ServerSentEvent(comment="heartbeat")
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe()

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no"
        }
    )


@router.delete("/{id}", status_code=204)
def delete_audit(id: str):
    state = storage.read_audit_state(id)
    if not state:
        raise HTTPException(status_code=404, detail="Audit not found")
    if state.get("status") == "running":
        raise HTTPException(status_code=409, detail="Cannot delete an audit while it is still running - wait for it to finish first.")
    
    storage.delete_audit(id)
    return Response(status_code=204)


@router.post("/{id}/stop", status_code=202)
def stop_audit(id: str):
    state = storage.read_audit_state(id)
    if not state:
        raise HTTPException(status_code=404, detail="Audit not found")
    if state.get("status") not in ("running", "blocked"):
        raise HTTPException(status_code=409, detail="Audit is not running.")
    audit_controller.request_cancel(id)
    return {"stopping": True}


@router.post("/{id}/issues/{issue_id}/fix", status_code=202)
def fix_issue(id: str, issue_id: str, background_tasks: BackgroundTasks, req_body: Optional[FixRequest] = None):
    if req_body is None:
        req_body = FixRequest()
        
    state = storage.read_audit_state(id)
    if not state:
        raise HTTPException(status_code=404, detail="Audit not found")
        
    issues = state.get("issues", [])
    issue = next((i for i in issues if i.get("id") == issue_id), None)
    
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
        
    if issue.get("fixAttempt") and issue["fixAttempt"].get("status") == "running":
        raise HTTPException(status_code=409, detail="A fix attempt is already running for this issue.")
        
    if not state.get("repoPath"):
        raise HTTPException(status_code=400, detail="This audit was not given a repository path - fixing requires one so Casefile can create a branch.")

    start_command = req_body.startCommand.strip() if req_body.startCommand and str(req_body.startCommand).strip() else "npm run dev"
    
    verify_port_val = req_body.verifyPort
    if verify_port_val is not None and math.isfinite(float(verify_port_val)) and float(verify_port_val) > 0:
        verify_port = int(verify_port_val)
    else:
        verify_port = 4310
        
    auto_pr = bool(req_body.autoPR)
    
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    issue["fixAttempt"] = {
        "status": "running",
        "startedAt": now_iso,
        "completedAt": None,
        "branch": None,
        "worktreeDir": None,
        "attempts": 0,
        "verified": None,
        "prUrl": None,
        "autoPR": auto_pr,
        "log": []
    }
    
    storage.write_audit_state(state.get("id"), state)
    event_bus.emit_event(state.get("id"), "state", state)

    def persist_and_broadcast():
        storage.write_audit_state(state.get("id"), state)
        event_bus.emit_event(state.get("id"), "state", state)

    def on_log(message: str):
        at_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        issue["fixAttempt"]["log"].append({"at": at_iso, "message": message})
        persist_and_broadcast()

    def on_update(patch: dict):
        issue["fixAttempt"].update(patch)
        persist_and_broadcast()

    async def run_fix():
        try:
            headless = os.environ.get("HEADLESS") != "false"
            repo_path = state.get("repoPath")
            audit_config = load_audit_config(repo_path) if repo_path else {}
            fix_args = {
                "issue": issue,
                "repo_path": repo_path,
                "start_command": start_command,
                "verify_port": verify_port,
                "auto_pr": auto_pr,
                "headless": headless,
                "on_log": on_log,
                "on_update": on_update,
                "cursor_context": audit_config.get("cursorContext")
            }
            if asyncio.iscoroutinefunction(fix_orchestrator.attempt_fix):
                await fix_orchestrator.attempt_fix(**fix_args)
            else:
                await asyncio.to_thread(fix_orchestrator.attempt_fix, **fix_args)
        except Exception as err:
            import traceback
            err_str = "".join(traceback.format_exception(type(err), err, err.__traceback__))
            log.error(f"Unhandled error fixing issue {issue.get('id')}: {err_str}")
            issue["fixAttempt"]["status"] = "failed"
            at_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            issue["fixAttempt"]["completedAt"] = at_iso
            issue["fixAttempt"]["log"].append({"at": at_iso, "message": f"Unexpected error: {str(err)}"})
            persist_and_broadcast()

    background_tasks.add_task(run_fix)
    
    return {"started": True}

class LabelRequest(BaseModel):
    decision: str
    comment: Optional[str] = None
    author: Optional[str] = None

@router.post("/{id}/findings/{finding_id}/labels", status_code=201)
def add_finding_label(id: str, finding_id: str, req: LabelRequest):
    from src.db.database import SessionLocal
    from src.db.models import Label, Finding
    db = SessionLocal()
    try:
        finding = db.query(Finding).filter(Finding.id == finding_id).first()
        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")
        
        label = Label(
            id=str(uuid.uuid4()),
            finding_id=finding_id,
            decision=req.decision,
            comment=req.comment,
            author=req.author
        )
        db.add(label)
        
        # Update finding status
        if req.decision == 'confirm':
            finding.status = 'confirmed'
        elif req.decision == 'false-positive':
            finding.status = 'false-positive'
            
        db.commit()
        return {"status": "success", "label_id": label.id}
    finally:
        db.close()

