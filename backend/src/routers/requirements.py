import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional

from src.db.database import get_db
from src.db.models import Requirement, TestCase
from src.test_plan_generator import generate_test_cases_for_requirement

router = APIRouter(prefix="/api/requirements", tags=["Requirements"])

class RequirementIngestRequest(BaseModel):
    target_app: str
    source: str
    raw_text: str

class TestCaseResponse(BaseModel):
    id: str
    description: str
    steps: List[str]
    expected_result: str

class RequirementResponse(BaseModel):
    id: str
    target_app: str
    source: str
    raw_text: str
    test_cases: List[TestCaseResponse]

@router.post("/", response_model=RequirementResponse)
async def ingest_requirement(req: RequirementIngestRequest, db = Depends(get_db)):
    """Ingests a requirement, generates test cases via AI, and stores both."""
    
    # 1. Create the Requirement record
    req_id = str(uuid.uuid4())
    new_req = Requirement(
        id=req_id,
        target_app=req.target_app,
        source=req.source,
        raw_text=req.raw_text
    )
    db.add(new_req)
    
    # 2. Generate Test Cases using Gemini
    generated_cases = await generate_test_cases_for_requirement(req.raw_text)
    
    response_cases = []
    
    # 3. Store Test Cases
    for tc in generated_cases:
        tc_id = str(uuid.uuid4())
        new_tc = TestCase(
            id=tc_id,
            requirement_id=req_id,
            target_app=req.target_app,
            steps=tc.get('steps', []),
            expected_result=tc.get('expected_result', tc.get('description', 'Pass'))
        )
        db.add(new_tc)
        
        response_cases.append(TestCaseResponse(
            id=tc_id,
            description=tc.get('description', 'Generated Test Case'),
            steps=new_tc.steps,
            expected_result=new_tc.expected_result
        ))
        
    db.commit()
    
    return RequirementResponse(
        id=req_id,
        target_app=req.target_app,
        source=req.source,
        raw_text=req.raw_text,
        test_cases=response_cases
    )

@router.get("/{target_app}")
async def get_requirements(target_app: str, db = Depends(get_db)):
    """Fetch all requirements and test cases for a target app."""
    reqs = db.query(Requirement).filter(Requirement.target_app == target_app).all()
    
    result = []
    for r in reqs:
        tcs = [{"id": tc.id, "steps": tc.steps, "expected_result": tc.expected_result} for tc in r.test_cases]
        result.append({
            "id": r.id,
            "source": r.source,
            "raw_text": r.raw_text[:100] + "...",
            "test_cases": tcs
        })
        
    return result
