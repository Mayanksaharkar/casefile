"""
hitl.py — Human-in-the-Loop pause/resume machinery.

A run enters the Blocked state when:
  (a) The judge emits a `request_input` action, OR
  (b) The stuck-loop detector fires (page state unchanged for N iterations).

While blocked:
  - The Playwright browser context stays alive (browser NOT torn down).
  - An asyncio.Event is set when human provides input via POST /runs/{id}/resume.
  - The run loop awaits that event with a configurable timeout.
  - On timeout the run transitions to failed with an explanation.

Fixture Vault:
  - Stored in data/fixtures.json (encrypted at rest with Fernet).
  - Each fixture: { id, target_app, field_key, value_enc, field_type, vault_type, last_verified }.
  - vault_type: 'static' (can be auto-applied) | 'ephemeral' (never auto-applied, never cached).
  - OTP/code fields are ALWAYS treated as ephemeral in code, regardless of user flag.
  - Values are Fernet-encrypted before writing. Masked in all read APIs.
"""

import os
import json
import uuid
import asyncio
import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.utils import make_logger

log = make_logger('hitl')

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

HITL_ENABLED_ENV = 'HITL_ENABLED'

def hitl_enabled() -> bool:
    return os.environ.get(HITL_ENABLED_ENV, 'true').lower() not in ('false', '0', 'no')

# ---------------------------------------------------------------------------
# Stuck-loop detector threshold
# ---------------------------------------------------------------------------

STUCK_THRESHOLD = int(os.environ.get('HITL_STUCK_THRESHOLD', '3'))
BLOCK_TIMEOUT_SECONDS = int(os.environ.get('HITL_BLOCK_TIMEOUT', '600'))  # 10 min default

# ---------------------------------------------------------------------------
# Per-run block state (in-process, not persisted — driver lives here too)
# ---------------------------------------------------------------------------

class BlockState:
    """Held in memory for the lifetime of a blocked run."""
    def __init__(self):
        self.event: asyncio.Event = asyncio.Event()
        self.answer: Optional[str] = None
        self.question: Optional[str] = None
        self.field_selector: Optional[str] = None
        self.field_type: Optional[str] = None
        self.screenshot_path: Optional[str] = None

_block_states: Dict[str, BlockState] = {}

def create_block_state(run_id: str) -> BlockState:
    bs = BlockState()
    _block_states[run_id] = bs
    return bs

def get_block_state(run_id: str) -> Optional[BlockState]:
    return _block_states.get(run_id)

def clear_block_state(run_id: str):
    _block_states.pop(run_id, None)

# ---------------------------------------------------------------------------
# Fixture Vault — encryption helpers
# ---------------------------------------------------------------------------

FIXTURES_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'fixtures.json'

# Ephemeral-only field patterns — NEVER auto-apply, NEVER cache as static
_ALWAYS_EPHEMERAL_PATTERNS = [
    'otp', 'one-time', 'verification code', 'sms code', 'auth code',
    'magic link', 'captcha', '2fa', 'mfa', 'totp',
]

def _is_always_ephemeral(field_key: str, question: str = '') -> bool:
    combined = (field_key + ' ' + question).lower()
    return any(p in combined for p in _ALWAYS_EPHEMERAL_PATTERNS)

def _derive_key() -> bytes:
    """Derive a Fernet-compatible 32-byte key from HITL_VAULT_SECRET env var.
    Falls back to a machine-stable hash so the vault still works without config.
    """
    secret = os.environ.get('HITL_VAULT_SECRET', '')
    if not secret:
        # Machine-stable fallback: hash of the DB path
        secret = str(FIXTURES_FILE)
    digest = hashlib.sha256(secret.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)

try:
    from cryptography.fernet import Fernet
    _fernet = Fernet(_derive_key())
    ENCRYPTION_AVAILABLE = True
except ImportError:
    log.warn('cryptography package not installed — fixture values stored in base64 only (install with: pip install cryptography)')
    ENCRYPTION_AVAILABLE = False
    _fernet = None

def _encrypt(value: str) -> str:
    if ENCRYPTION_AVAILABLE and _fernet:
        return _fernet.encrypt(value.encode('utf-8')).decode('utf-8')
    # Fallback: base64 — better than plaintext, not cryptographically secure
    return base64.b64encode(value.encode('utf-8')).decode('utf-8')

def _decrypt(enc: str) -> str:
    if ENCRYPTION_AVAILABLE and _fernet:
        try:
            return _fernet.decrypt(enc.encode('utf-8')).decode('utf-8')
        except Exception:
            pass
    # Fallback: try base64
    try:
        return base64.b64decode(enc.encode('utf-8')).decode('utf-8')
    except Exception:
        return ''

def _mask(value: str) -> str:
    if not value:
        return ''
    if len(value) <= 4:
        return '****'
    return value[:2] + '****' + value[-2:]

# ---------------------------------------------------------------------------
# Fixture CRUD
# ---------------------------------------------------------------------------

def _load_fixtures() -> list:
    if not FIXTURES_FILE.exists():
        return []
    try:
        with open(FIXTURES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def _save_fixtures(fixtures: list):
    FIXTURES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FIXTURES_FILE.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(fixtures, f, indent=2)
    tmp.rename(FIXTURES_FILE)

def list_fixtures(target_app: Optional[str] = None) -> list:
    """Return fixtures with values masked."""
    fixtures = _load_fixtures()
    result = []
    for fx in fixtures:
        if target_app and fx.get('target_app') != target_app:
            continue
        result.append({
            **fx,
            'value': _mask(_decrypt(fx['value_enc'])),
            'value_enc': '***',
        })
    return result

def upsert_fixture(
    target_app: str,
    field_key: str,
    value: str,
    field_type: str = 'text',
    vault_type: str = 'ephemeral',
    fixture_id: Optional[str] = None,
) -> dict:
    """Create or update a fixture. Enforces ephemeral for OTP-like fields."""
    # Safety: force ephemeral for OTP/captcha regardless of user request
    if _is_always_ephemeral(field_key):
        vault_type = 'ephemeral'
        log.info(f'Fixture for field "{field_key}" forced to ephemeral (OTP/captcha pattern detected).')

    fixtures = _load_fixtures()
    now = datetime.now(timezone.utc).isoformat()
    enc_value = _encrypt(value)

    # Look for existing fixture by id or by (target_app, field_key)
    existing = None
    if fixture_id:
        existing = next((fx for fx in fixtures if fx.get('id') == fixture_id), None)
    if not existing:
        existing = next((fx for fx in fixtures
                         if fx.get('target_app') == target_app and fx.get('field_key') == field_key), None)

    if existing:
        existing['value_enc'] = enc_value
        existing['field_type'] = field_type
        existing['vault_type'] = vault_type
        existing['last_verified'] = now
        _save_fixtures(fixtures)
        return {**existing, 'value': _mask(value), 'value_enc': '***'}
    else:
        fx = {
            'id': fixture_id or str(uuid.uuid4()),
            'target_app': target_app,
            'field_key': field_key,
            'value_enc': enc_value,
            'field_type': field_type,
            'vault_type': vault_type,
            'last_verified': now,
        }
        fixtures.append(fx)
        _save_fixtures(fixtures)
        return {**fx, 'value': _mask(value), 'value_enc': '***'}

def delete_fixture(fixture_id: str) -> bool:
    fixtures = _load_fixtures()
    before = len(fixtures)
    fixtures = [fx for fx in fixtures if fx.get('id') != fixture_id]
    if len(fixtures) == before:
        return False
    _save_fixtures(fixtures)
    return True

def lookup_static_fixture(target_app: str, field_key: str) -> Optional[str]:
    """Return the plaintext value of a matching STATIC fixture, or None.
    Ephemeral fixtures are NEVER returned here — they must always go through
    human input.
    """
    if _is_always_ephemeral(field_key):
        return None  # Hard block: never auto-apply OTP/captcha

    fixtures = _load_fixtures()
    for fx in fixtures:
        if (
            fx.get('target_app') == target_app
            and fx.get('field_key') == field_key
            and fx.get('vault_type') == 'static'
        ):
            return _decrypt(fx['value_enc'])
    return None

# ---------------------------------------------------------------------------
# Stuck-loop detector
# ---------------------------------------------------------------------------

class StuckDetector:
    """Tracks consecutive unchanged page states and fires when threshold hit."""

    def __init__(self, threshold: int = STUCK_THRESHOLD):
        self.threshold = threshold
        self._last_hash: Optional[str] = None
        self._count: int = 0

    def record(self, page_hash: str) -> bool:
        """Return True if stuck (unchanged for `threshold` consecutive iterations)."""
        if page_hash == self._last_hash:
            self._count += 1
        else:
            self._last_hash = page_hash
            self._count = 1
        return self._count >= self.threshold

    def reset(self):
        self._last_hash = None
        self._count = 0
