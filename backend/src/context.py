from contextvars import ContextVar

# To log eval metrics, we need the run_id in context.
current_run_id: ContextVar[str] = ContextVar("current_run_id", default=None)
