import uuid
from typing import Optional
from sqlalchemy.orm import Session
from src.db.database import SessionLocal
from src.db.models import Run, Finding, FindingDiff, Label
from src.utils import make_logger

log = make_logger('regression')

def compute_confidence(finding: Finding, db: Session) -> float:
    """
    Computes a confidence score (0.0 to 1.0) for a finding.
    Combines signal type, severity, and historical false-positive rates.
    """
    base_score = 0.8
    
    # 1. Signal Type Heuristics
    if finding.category == 'a11y':
        base_score = 0.98  # Axe-core is highly deterministic
    elif finding.category == 'network':
        base_score = 0.95  # 404s/500s are hard facts
    elif finding.category == 'functional':
        # If it comes from an assertion engine, it's high. If exploratory LLM, it's lower.
        # We can guess based on title context for now.
        if "Test Case Failed" in finding.title:
            base_score = 0.95
        else:
            base_score = 0.70  # LLM judgment might hallucinate
            
    # 2. Historical Penalty (Feedback loop)
    # If similar findings on this route were marked false-positive, drop confidence.
    similar_past_findings = db.query(Finding).join(Label).filter(
        Finding.route == finding.route,
        Finding.category == finding.category,
        Label.decision == 'false-positive'
    ).count()
    
    if similar_past_findings > 0:
        penalty = min(0.4, similar_past_findings * 0.1)
        base_score -= penalty
        
    # Cap between 0.1 and 1.0
    return max(0.1, min(1.0, base_score))

def run_post_audit_analysis(run_id: str):
    """
    Called after an audit completes. 
    1. Computes confidence scores for all findings.
    2. Runs the Regression Diff Engine against the previous run.
    """
    db = SessionLocal()
    try:
        current_run = db.query(Run).filter(Run.id == run_id).first()
        if not current_run:
            return
            
        # 1. Compute Confidence
        for finding in current_run.findings:
            if finding.confidence_score is None:
                finding.confidence_score = compute_confidence(finding, db)
                
        # 2. Find previous run for the same target
        previous_run = db.query(Run).filter(
            Run.target_url == current_run.target_url,
            Run.id != current_run.id,
            Run.status == 'completed'
        ).order_by(Run.completed_at.desc()).first()
        
        if previous_run:
            log.info(f"Diffing run {current_run.id} against previous run {previous_run.id}")
            _compute_diff(current_run, previous_run, db)
        else:
            # First run ever, everything is 'new'
            for finding in current_run.findings:
                diff = FindingDiff(
                    id=str(uuid.uuid4()),
                    current_finding_id=finding.id,
                    resolution='new'
                )
                db.add(diff)
                
        
        
        db.commit()
        
        # Phase 3: Ticket Integration - Auto-file high-confidence, new issues
        import asyncio
        from src.integrations import file_linear_ticket
        
        async def _auto_file_tickets():
            for fnd in current_run.findings:
                if fnd.severity in ('critical', 'high') and fnd.confidence_score and fnd.confidence_score >= 0.90:
                    # Check if it's new
                    from src.db.models import FindingDiff
                    diff = db.query(FindingDiff).filter(FindingDiff.current_finding_id == fnd.id).first()
                    if diff and diff.resolution == 'new':
                        priority = 1 if fnd.severity == 'critical' else 2
                        desc = f"{fnd.description}\n\n**Route:** {fnd.route}\n**Run:** {current_run.id}\n**Confidence:** {fnd.confidence_score}"
                        await file_linear_ticket(fnd.title, desc, priority)
                        
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_auto_file_tickets())
        except RuntimeError:
            asyncio.run(_auto_file_tickets())

        
        # Back-propagate to JSON for frontend
        import json
        from src.storage import state_file
        state_path = state_file(current_run.id)
        with open(state_path, 'r') as f:
            state_data = json.load(f)
        
        # update issues in state
        curr_findings = {f.id: f for f in current_run.findings}
        for issue in state_data.get('issues', []):
            if issue['id'] in curr_findings:
                fnd = curr_findings[issue['id']]
                issue['confidence_score'] = fnd.confidence_score
                issue['status'] = fnd.status
                # Find diff
                from src.db.models import FindingDiff
                diff = db.query(FindingDiff).filter(FindingDiff.current_finding_id == fnd.id).first()
                if diff:
                    issue['resolution'] = diff.resolution
        
        with open(state_path, 'w') as f:
            json.dump(state_data, f, indent=2)
            

    except Exception as e:
        db.rollback()
        log.error(f"Post-audit analysis failed: {e}")
    finally:
        db.close()

def _compute_diff(current_run: Run, previous_run: Run, db: Session):
    prev_findings = {f.id: f for f in previous_run.findings}
    curr_findings = {f.id: f for f in current_run.findings}
    
    matched_prev_ids = set()
    
    for curr_f in curr_findings.values():
        # Heuristic match: same category, severity, and route
        # In a real NLP scenario, we'd embed the title/description and do cosine similarity.
        match = None
        for prev_f in prev_findings.values():
            if prev_f.id in matched_prev_ids: continue
            if prev_f.category == curr_f.category and prev_f.route == curr_f.route:
                if prev_f.title == curr_f.title or prev_f.element_selector == curr_f.element_selector:
                    match = prev_f
                    break
        
        diff = FindingDiff(id=str(uuid.uuid4()), current_finding_id=curr_f.id)
        if match:
            diff.prior_finding_id = match.id
            # If it was fixed but came back, it's a regression. Otherwise recurring.
            diff.resolution = 'recurring' 
            matched_prev_ids.add(match.id)
        else:
            diff.resolution = 'new'
            
        db.add(diff)
        
    # Mark anything in prev but not in curr as 'fixed' (Optional, requires finding placeholders)
    # We'll stick to diffing current findings for now as per the DB schema (which binds to current_finding_id)
