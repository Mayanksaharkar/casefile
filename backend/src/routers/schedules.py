"""
schedules.py — REST API for managing Casefile audit schedules.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..scheduler import add_schedule, remove_schedule, list_schedules, get_schedule
from ..utils import make_logger

log = make_logger('routes:schedules')
router = APIRouter()


class ScheduleCreate(BaseModel):
    name: str
    cron: str
    targetUrl: str
    repoPath: Optional[str] = None
    budget: Optional[int] = 30
    notify: Optional[dict] = None


@router.post('', status_code=201)
def create_schedule(body: ScheduleCreate):
    """Register a new cron schedule."""
    schedule = body.dict()
    schedule_id = add_schedule(schedule)
    return {'id': schedule_id, **schedule}


@router.get('')
def get_schedules():
    """List all active schedules."""
    return list_schedules()


@router.get('/{schedule_id}')
def get_schedule_by_id(schedule_id: str):
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail='Schedule not found')
    return schedule


@router.delete('/{schedule_id}', status_code=204)
def delete_schedule(schedule_id: str):
    """Stop and remove a schedule."""
    removed = remove_schedule(schedule_id)
    if not removed:
        raise HTTPException(status_code=404, detail='Schedule not found')
