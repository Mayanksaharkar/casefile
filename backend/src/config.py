import os
import json
import yaml
import logging
from typing import Dict, Any, Optional

try:
    from src.utils import make_logger
    log = make_logger('auditConfigLoader')
except ImportError:
    log = logging.getLogger('auditConfigLoader')

def safe_read_yaml(file_path: str) -> Optional[Any]:
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as err:
        log.warning(f"Failed to parse YAML at {file_path}: {err}")
        return None

def safe_read_json(file_path: str) -> Optional[Any]:
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as err:
        log.warning(f"Failed to parse JSON at {file_path}: {err}")
        return None

def safe_read_text(file_path: str) -> Optional[str]:
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as err:
        return None

def load_audit_config(repo_path: str) -> Dict[str, Any]:
    """
    Loads the optional business-rules contract from <repoPath>/.audit/.
    This is what lets the planner and bug-judge know what the app is
    SUPPOSED to do, instead of only what it observably does.

    Returns a config object; every field defaults to null/empty so the
    rest of the system can run fine with no .audit folder at all.
    """
    config = {
        'repoPath': repo_path if repo_path else None,
        'appSpec': None,
        'flows': None,
        'rules': None,
        'credentials': None,
        'cursorContext': None,
        'found': False,
    }

    if not repo_path:
        return config

    audit_dir = os.path.join(repo_path, '.audit')
    if not os.path.exists(audit_dir):
        log.info(f"No .audit/ folder found at {repo_path} - running without a business-rules contract.")
        return config

    config['found'] = True
    config['appSpec'] = safe_read_text(os.path.join(audit_dir, 'app-spec.md'))
    config['flows'] = safe_read_yaml(os.path.join(audit_dir, 'flows.yaml'))
    config['rules'] = safe_read_yaml(os.path.join(audit_dir, 'rules.yaml'))
    config['cursorContext'] = safe_read_text(os.path.join(audit_dir, 'cursor-context.md'))
    config['credentials'] = safe_read_json(os.path.join(audit_dir, 'credentials.json'))

    log.info(
        f"Loaded .audit/ config from {repo_path} "
        f"(appSpec: {str(bool(config['appSpec'])).lower()}, flows: {str(bool(config['flows'])).lower()}, "
        f"rules: {str(bool(config['rules'])).lower()}, credentials: {str(bool(config['credentials'])).lower()}, "
        f"cursorContext: {str(bool(config['cursorContext'])).lower()})"
    )

    return config
