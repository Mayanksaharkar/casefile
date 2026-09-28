import os
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.utils import make_logger

log = make_logger('diskStorage')

DATA_ROOT = Path(__file__).resolve().parent.parent / 'data' / 'audits'

def ensure_dir(dir_path):
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    return str(d)

def audit_dir(audit_id):
    return str(DATA_ROOT / audit_id)

def screenshots_dir(audit_id):
    return str(DATA_ROOT / audit_id / 'screenshots')

def network_dir(audit_id):
    return str(DATA_ROOT / audit_id / 'network')

def console_dir(audit_id):
    return str(DATA_ROOT / audit_id / 'console')

def traces_dir(audit_id):
    return str(DATA_ROOT / audit_id / 'traces')

def state_file(audit_id):
    return str(DATA_ROOT / audit_id / 'audit.json')

def report_file(audit_id):
    return str(DATA_ROOT / audit_id / 'report.html')

def init_audit_dirs(audit_id):
    ensure_dir(audit_dir(audit_id))
    ensure_dir(screenshots_dir(audit_id))
    ensure_dir(network_dir(audit_id))
    ensure_dir(console_dir(audit_id))
    ensure_dir(traces_dir(audit_id))
    return audit_dir(audit_id)

from src.db.sync import sync_state_to_db

def write_audit_state(audit_id, state):
    file_path = Path(state_file(audit_id))
    tmp_path = file_path.with_name(f"{file_path.name}.tmp")
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    tmp_path.rename(file_path)
    
    # Mirror state to relational DB (Phase 0)
    sync_state_to_db(state)

def read_audit_state(audit_id):
    file_path = Path(state_file(audit_id))
    if not file_path.exists():
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as err:
        log.error(f"Corrupt audit.json for {audit_id}: {err}")
        return None

def parse_date(date_str):
    if not date_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    date_str = date_str.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

def list_audits():
    if not DATA_ROOT.exists():
        return []
    
    ids = [entry.name for entry in DATA_ROOT.iterdir() if entry.is_dir()]
    
    audits = [read_audit_state(audit_id) for audit_id in ids]
    audits = [a for a in audits if a is not None]
    
    audits.sort(key=lambda a: parse_date(a.get('startedAt')), reverse=True)
    return audits

def delete_audit(audit_id):
    dir_path = Path(audit_dir(audit_id))
    if dir_path.exists():
        shutil.rmtree(dir_path, ignore_errors=True)
        return True
    return False

def save_screenshot(audit_id, buffer, name):
    dir_path = Path(screenshots_dir(audit_id))
    ensure_dir(dir_path)
    file_path = dir_path / name
    with open(file_path, 'wb') as f:
        f.write(buffer)
    return f"screenshots/{name}"

def save_json(audit_id, subdir, name, data):
    dir_path = Path(audit_dir(audit_id)) / subdir
    ensure_dir(dir_path)
    file_path = dir_path / name
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    return f"{subdir}/{name}"

def save_report_html(audit_id, html):
    with open(report_file(audit_id), 'w', encoding='utf-8') as f:
        f.write(html)
    return 'report.html'

def save_trace_file(audit_id, src_path, name):
    dir_path = Path(traces_dir(audit_id))
    ensure_dir(dir_path)
    dest = dir_path / name
    shutil.copyfile(src_path, dest)
    return f"traces/{name}"

def save_fix_prompt(issue_id, prompt_content):
    root_dir = Path(__file__).resolve().parent.parent.parent
    fix_prompts_dir = root_dir / '.audit' / 'fix-prompts'
    ensure_dir(fix_prompts_dir)
    file_path = fix_prompts_dir / f"{issue_id}.md"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(prompt_content)
    return str(file_path)
