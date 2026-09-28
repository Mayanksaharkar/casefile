import uuid
from typing import List, Dict, Any
from src.intelligence import generate_json
from src.utils import make_logger

log = make_logger('test_plan_gen')

TEST_PLAN_SYSTEM_PROMPT = """You are an expert QA Automation Engineer.
Your task is to take a raw product requirement, PRD excerpt, or bug ticket, and convert it into a set of structured, deterministic test cases.

Return a JSON object with a single key "test_cases" containing an array of objects.
Each test case object must have:
1. "description": A brief summary of what is being tested.
2. "steps": An array of specific user actions required to reach the state being tested (e.g., ["Navigate to /login", "Click 'Forgot Password'", "Enter email"]).
3. "expected_result": The exact state, text, or visual cue that indicates the test passed.

Keep steps actionable and realistic for a web automation engine like Playwright."""

async def generate_test_cases_for_requirement(raw_text: str) -> List[Dict[str, Any]]:
    """Uses Gemini to parse raw requirements into structured TestCases."""
    
    user_prompt = f"Requirement to parse:\n\n{raw_text}\n\nPlease generate the structured test cases."
    
    result = await generate_json(TEST_PLAN_SYSTEM_PROMPT, user_prompt, temperature=0.2)
    
    if not result or 'test_cases' not in result:
        log.warning("Failed to generate test cases or invalid JSON format returned.")
        return []
        
    return result.get('test_cases', [])
