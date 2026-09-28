"""
Routes for HITL resume and Fixture Vault management.

Endpoints:
  POST /api/hitl/{run_id}/resume       — Feed human answer; unblocks the run.
  GET  /api/hitl/fixtures              — List all fixtures (values masked).
  GET  /api/hitl/fixtures/{app}        — List fixtures for one target app.
  POST /api/hitl/fixtures              — Upsert a fixture.
  DELETE /api/hitl/fixtures/{id}       — Delete a fixture.
"""

import base64
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src import hitl as vault
from src.utils import make_logger

log = make_logger('routes:hitl')
router = APIRouter()


class ResumeRequest(BaseModel):
    value: str
    save_as_fixture: Optional[bool] = False
    fixture_vault_type: Optional[str] = 'ephemeral'  # 'static' or 'ephemeral'


@router.post('/{run_id}/resume')
async def resume_run(run_id: str, body: ResumeRequest):
    """Unblock a paused run by providing the human answer."""
    if not vault.hitl_enabled():
        raise HTTPException(status_code=403, detail='HITL is disabled (set HITL_ENABLED=true to enable).')

    bs = vault.get_block_state(run_id)
    if not bs:
        raise HTTPException(status_code=404, detail='No blocked run found with that id.')
    if bs.event.is_set():
        raise HTTPException(status_code=409, detail='Run is not currently blocked.')

    bs.answer = body.value

    # Optionally persist as a fixture so future runs can reuse it
    if body.save_as_fixture and bs.field_selector:
        from src import storage
        # Derive target_app from the run state file
        state = storage.read_audit_state(run_id)
        target_app = state.get('targetUrl', 'unknown') if state else 'unknown'
        try:
            vault.upsert_fixture(
                target_app=target_app,
                field_key=bs.field_selector,
                value=body.value,
                field_type=bs.field_type or 'text',
                vault_type=body.fixture_vault_type or 'ephemeral',
            )
        except Exception as e:
            log.warning(f'Failed to save fixture for run {run_id}: {e}')

    bs.event.set()  # Unblock the waiting run loop
    log.info(f'Run {run_id} unblocked by human input.')
    return {'resumed': True}


class FixtureRequest(BaseModel):
    target_app: str
    field_key: str
    value: str
    field_type: Optional[str] = 'text'
    vault_type: Optional[str] = 'ephemeral'
    id: Optional[str] = None


@router.get('/fixtures')
def get_fixtures():
    return vault.list_fixtures()


@router.get('/fixtures/app/{target_app}')
def get_fixtures_for_app(target_app: str):
    return vault.list_fixtures(target_app=target_app)


@router.post('/fixtures', status_code=201)
def create_fixture(body: FixtureRequest):
    return vault.upsert_fixture(
        target_app=body.target_app,
        field_key=body.field_key,
        value=body.value,
        field_type=body.field_type or 'text',
        vault_type=body.vault_type or 'ephemeral',
        fixture_id=body.id,
    )


@router.delete('/fixtures/{fixture_id}', status_code=204)
def remove_fixture(fixture_id: str):
    deleted = vault.delete_fixture(fixture_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='Fixture not found.')
    return None
