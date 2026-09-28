import uuid
from typing import Dict, Any
from src.db.database import SessionLocal
from src.db.models import Run, Finding, EvalLog

def sync_state_to_db(state: Dict[str, Any]):
    """Syncs the flat JSON state dictionary to the relational DB."""
    db = SessionLocal()
    try:
        run_id = state.get('id')
        if not run_id:
            return

        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            run = Run(id=run_id)
            db.add(run)

        run.target_url = state.get('targetUrl', '')
        run.repo_path = state.get('repoPath')
        run.status = state.get('status', 'running')
        run.phase = state.get('phase', 'starting')
        run.budget = state.get('budget', 40)
        run.config_summary = state.get('configSummary')
        run.summary = state.get('summary')
        
        # We don't overwrite created_at, but we can set completed_at if done
        if run.status == 'completed' and not run.completed_at:
            from datetime import datetime
            run.completed_at = datetime.utcnow()
            
        # Sync Findings (formerly state['issues'])
        issues = state.get('issues', [])
        
        # Flush to ensure run is in session and findings can be accessed safely if new
        db.flush()
        existing_findings = {f.id: f for f in run.findings} if run.findings else {}
        
        for issue in issues:
            issue_id = issue.get('id')
            if not issue_id:
                issue_id = str(uuid.uuid4())
                issue['id'] = issue_id # back-populate the state
                
            finding = existing_findings.get(issue_id)
            if not finding:
                finding = Finding(id=issue_id, run_id=run.id)
                db.add(finding)
                
            finding.category = issue.get('category', 'functional')
            finding.severity = issue.get('severity', 'low')
            finding.title = issue.get('title', 'Untitled Issue')
            finding.description = issue.get('description', '')
            finding.route = issue.get('route')
            finding.element_selector = issue.get('element')
            
        db.commit()
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.close()

def log_eval(run_id: str, prompt: str, response: str, parsed_action: dict = None, outcome: str = None):
    """Records a Gemini judgment to EvalLog."""
    db = SessionLocal()
    try:
        log_entry = EvalLog(
            id=str(uuid.uuid4()),
            run_id=run_id,
            prompt=prompt,
            response=response,
            parsed_action=parsed_action,
            outcome=outcome
        )
        db.add(log_entry)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
