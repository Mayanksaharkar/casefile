"""
tests/test_hitl.py — Unit tests for the HITL blocker-resolution feature.

Tests cover:
  1. Stuck-loop detector triggers after N unchanged states
  2. lookup_static_fixture returns a static fixture value and never returns ephemeral
  3. OTP/captcha fields are ALWAYS treated as ephemeral (cannot be made static)
  4. StuckDetector.reset() clears the counter
  5. upsert_fixture / delete_fixture round-trip
  6. _mask() helper always masks values appropriately

Run with:
  cd /home/mayank/Desktop/casefile && \
  python -m pytest backend/tests/test_hitl.py -v
"""

import asyncio
import os
import sys
import tempfile
import json
import uuid
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# Allow import from backend/src without installing as a package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Patch FIXTURES_FILE before importing the module so we use a temp file
_tmp_fixtures = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
_tmp_fixtures.close()

import importlib

with patch.dict(os.environ, {'HITL_ENABLED': 'true', 'HITL_STUCK_THRESHOLD': '3'}):
    # We need to patch FIXTURES_FILE inside hitl module after import
    import src.hitl as hitl

# Point FIXTURES_FILE at our temp file for tests
hitl.FIXTURES_FILE = Path(_tmp_fixtures.name)


def _clear_fixtures():
    """Reset the temp fixtures file to an empty list."""
    with open(hitl.FIXTURES_FILE, 'w') as f:
        json.dump([], f)


# ---------------------------------------------------------------------------
# StuckDetector tests
# ---------------------------------------------------------------------------

class TestStuckDetector:
    def test_triggers_after_threshold(self):
        """StuckDetector fires True after STUCK_THRESHOLD identical hashes."""
        det = hitl.StuckDetector(threshold=3)
        assert det.record('abc') is False   # 1st occurrence
        assert det.record('abc') is False   # 2nd occurrence
        assert det.record('abc') is True    # 3rd → stuck!

    def test_does_not_trigger_on_changing_hashes(self):
        """If the hash changes, counter resets and should not trigger."""
        det = hitl.StuckDetector(threshold=3)
        det.record('aaa')
        det.record('aaa')
        # Change breaks the streak — 'bbb' counter resets to 1
        assert det.record('bbb') is False   # 1st 'bbb' → count=1
        assert det.record('bbb') is False   # 2nd 'bbb' → count=2
        # 3rd consecutive 'bbb' would trigger — but let's change again first
        assert det.record('ccc') is False   # reset again → count=1 for 'ccc'


    def test_reset_clears_counter(self):
        """After reset(), stuck detector should not carry over previous counts."""
        det = hitl.StuckDetector(threshold=3)
        det.record('xyz')
        det.record('xyz')
        det.reset()
        # After reset, needs threshold more consecutive identical hashes
        assert det.record('xyz') is False
        assert det.record('xyz') is False
        assert det.record('xyz') is True

    def test_higher_threshold(self):
        """Custom threshold = 5 should only fire on 5th identical hash."""
        det = hitl.StuckDetector(threshold=5)
        for i in range(4):
            assert det.record('same') is False
        assert det.record('same') is True


# ---------------------------------------------------------------------------
# Fixture Vault tests
# ---------------------------------------------------------------------------

class TestFixtureVault:
    def setup_method(self):
        _clear_fixtures()

    def teardown_method(self):
        _clear_fixtures()

    def test_upsert_and_lookup_static(self):
        """A static fixture is returned by lookup_static_fixture."""
        hitl.upsert_fixture(
            target_app='http://example.com',
            field_key='input[name="username"]',
            value='testuser@example.com',
            field_type='email',
            vault_type='static',
        )
        result = hitl.lookup_static_fixture('http://example.com', 'input[name="username"]')
        assert result == 'testuser@example.com'

    def test_ephemeral_fixture_never_returned_by_lookup(self):
        """An ephemeral fixture must NEVER be auto-applied."""
        hitl.upsert_fixture(
            target_app='http://example.com',
            field_key='input[name="code"]',
            value='12345',
            field_type='text',
            vault_type='ephemeral',
        )
        result = hitl.lookup_static_fixture('http://example.com', 'input[name="code"]')
        assert result is None, "Ephemeral fixture must never be auto-applied"

    def test_otp_field_always_ephemeral_regardless_of_user_flag(self):
        """Requesting vault_type='static' for an OTP field must be rejected — forced to ephemeral."""
        fx = hitl.upsert_fixture(
            target_app='http://example.com',
            field_key='input[name="otp"]',
            value='999888',
            field_type='otp',
            vault_type='static',   # user wants static — must be silently overridden
        )
        assert fx['vault_type'] == 'ephemeral', (
            "OTP fixture must be forced to ephemeral even if user requested static"
        )
        # Also verify it's not returned by lookup
        result = hitl.lookup_static_fixture('http://example.com', 'input[name="otp"]')
        assert result is None

    def test_captcha_field_forced_ephemeral(self):
        """CAPTCHA fields must always be ephemeral."""
        fx = hitl.upsert_fixture(
            target_app='http://example.com',
            field_key='captcha-answer',
            value='XKCD42',
            field_type='text',
            vault_type='static',
        )
        assert fx['vault_type'] == 'ephemeral'

    def test_mfa_totp_forced_ephemeral(self):
        """2FA/TOTP fields must always be ephemeral."""
        for field_key in ['2fa-code', 'totp-input', 'mfa_token']:
            _clear_fixtures()
            fx = hitl.upsert_fixture(
                target_app='http://app.com',
                field_key=field_key,
                value='123456',
                vault_type='static',
            )
            assert fx['vault_type'] == 'ephemeral', f"Field '{field_key}' should be forced to ephemeral"

    def test_delete_fixture(self):
        """Deleting a fixture removes it from the vault."""
        fx = hitl.upsert_fixture(
            target_app='http://example.com',
            field_key='input[name="city"]',
            value='New York',
            vault_type='static',
        )
        deleted = hitl.delete_fixture(fx['id'])
        assert deleted is True
        assert hitl.lookup_static_fixture('http://example.com', 'input[name="city"]') is None

    def test_delete_nonexistent_fixture(self):
        """Deleting a fixture that doesn't exist returns False."""
        assert hitl.delete_fixture('does-not-exist-' + str(uuid.uuid4())) is False

    def test_values_masked_in_list(self):
        """list_fixtures() must never expose plaintext values."""
        hitl.upsert_fixture(
            target_app='http://example.com',
            field_key='input[name="password"]',
            value='supersecretpassword',
            vault_type='static',
        )
        items = hitl.list_fixtures('http://example.com')
        for item in items:
            raw = item.get('value', '')
            assert 'supersecretpassword' not in raw, (
                f"Plaintext value must not appear in list_fixtures output: got '{raw}'"
            )
            # Masked value should contain asterisks
            assert '****' in raw or len(raw) == 0

    def test_upsert_updates_existing(self):
        """Upserting same (target_app, field_key) updates instead of creating duplicate."""
        hitl.upsert_fixture('http://a.com', 'field', 'v1', vault_type='static')
        hitl.upsert_fixture('http://a.com', 'field', 'v2', vault_type='static')
        result = hitl.lookup_static_fixture('http://a.com', 'field')
        assert result == 'v2'
        # Only one entry should exist
        fixtures = hitl.list_fixtures('http://a.com')
        assert len(fixtures) == 1


# ---------------------------------------------------------------------------
# BlockState tests
# ---------------------------------------------------------------------------

class TestBlockState:
    def test_create_and_get_block_state(self):
        run_id = 'test-run-' + str(uuid.uuid4())
        bs = hitl.create_block_state(run_id)
        assert hitl.get_block_state(run_id) is bs
        hitl.clear_block_state(run_id)
        assert hitl.get_block_state(run_id) is None

    def test_event_set_on_answer(self):
        """Setting bs.event should unblock an awaiting coroutine."""
        run_id = 'test-run-' + str(uuid.uuid4())
        bs = hitl.create_block_state(run_id)
        bs.answer = 'some-answer'
        bs.event.set()
        assert bs.event.is_set()
        hitl.clear_block_state(run_id)


# ---------------------------------------------------------------------------
# hitl_enabled() feature flag test
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    def test_disabled_via_env(self):
        with patch.dict(os.environ, {'HITL_ENABLED': 'false'}):
            assert hitl.hitl_enabled() is False

    def test_enabled_via_env(self):
        with patch.dict(os.environ, {'HITL_ENABLED': 'true'}):
            assert hitl.hitl_enabled() is True

    def test_enabled_by_default(self):
        env = dict(os.environ)
        env.pop('HITL_ENABLED', None)
        with patch.dict(os.environ, env, clear=True):
            assert hitl.hitl_enabled() is True


# ---------------------------------------------------------------------------
# _mask() helper tests
# ---------------------------------------------------------------------------

class TestMask:
    def test_short_value_fully_masked(self):
        assert hitl._mask('ab') == '****'
        assert hitl._mask('') == ''

    def test_longer_value_partially_masked(self):
        result = hitl._mask('hello@world.com')
        assert '****' in result
        assert 'hello@world.com' not in result

    def test_mask_preserves_prefix_suffix(self):
        result = hitl._mask('abcdefgh')
        assert result.startswith('ab')
        assert result.endswith('gh')
        assert '****' in result
