import os
import sys
import traceback
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import uvicorn

load_dotenv()

from .utils import make_logger
from .routers.audits import router as audits_router
from .routers.webhooks import router as webhooks_router
from .routers.schedules import router as schedules_router
from .routers.requirements import router as requirements_router
from .routers.evals import router as evals_router
from .routers.hitl import router as hitl_router
from .intelligence import is_configured
from .storage import DATA_ROOT
from .db.database import init_db

log = make_logger("server")

# Initialize relational DB for Phase 0
init_db()


def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Suppress the noisy traceback when shutting down via Ctrl+C
        return
    err_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    log.error(f"Uncaught exception: {err_str}")


sys.excepthook = handle_unhandled_exception


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()

    def handle_exception(loop, context):
        msg = context.get("exception", context.get("message"))
        log.error(f"Unhandled task exception: {msg}")

    loop.set_exception_handler(handle_exception)

    # Load cron schedules from the default repo path (if configured)
    repo_path = os.environ.get("DEFAULT_REPO_PATH", "")
    if repo_path:
        try:
            from .scheduler import load_schedules_from_yaml
            load_schedules_from_yaml(repo_path)
        except Exception as e:
            log.warning(f"Could not load schedules.yaml: {e}")

    try:
        yield
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan, title="Casefile API", version="2.0.0")

origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check():
    return {
        "ok": True,
        "geminiConfigured": is_configured(),
        "version": "2.0.0",
    }


@app.get("/api/system/test-llm")
async def test_llm():
    if not is_configured():
        return JSONResponse(status_code=400, content={"error": "LLM is not configured (missing API keys)"})
    
    from .intelligence import generate_json
    try:
        res = await generate_json(
            system_prompt="You are a helpful test bot. Please respond exactly with the following JSON format: {\"status\": \"ok\", \"message\": \"<insert a brief friendly hello>\"}",
            user_prompt="Hello, is this working?",
            temperature=0.0
        )
        if res and res.get("status") == "ok":
            return {"ok": True, "message": res.get("message", "Live")}
        return JSONResponse(status_code=500, content={"error": "LLM responded but output was malformed JSON."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# Mount routers
app.include_router(audits_router, prefix="/api/audits")
app.include_router(webhooks_router, prefix="/api/webhooks")
app.include_router(schedules_router, prefix="/api/schedules")
app.include_router(requirements_router)
app.include_router(evals_router)
app.include_router(hitl_router, prefix="/api/hitl")

# Static files — audit data (screenshots, reports, etc.)
os.makedirs(DATA_ROOT, exist_ok=True)
app.mount("/data/audits", StaticFiles(directory=DATA_ROOT), name="data_audits")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    err_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log.error(err_str)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4001))
    log.info(f"Casefile audit API v2.0 listening on http://localhost:{port}")
    if not is_configured():
        log.warning("GEMINI_API_KEY not set — running in deterministic-only mode.")
    uvicorn.run("src.main:app", host="0.0.0.0", port=port, reload=True)
