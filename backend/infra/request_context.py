"""Request-scoped context vars + structlog binding.

Adds an `X-Request-ID` header to every HTTP response and stores the id
in a contextvar so structlog automatically tags every log line emitted
during that request. Useful for grepping logs after a failure:

    ❯ grep request_id=abc123 backend.log
    2026-05-16 ... workflow.task_failed task_id=t_xyz request_id=abc123
    2026-05-16 ... crewai_runner.kickoff_failed task_id=t_xyz request_id=abc123

WebSocket events do NOT pass through the middleware; the contextvar
defaults to "" for them (they have their own task_id / project_id which
is more meaningful than a synthetic request id).

Audit (2026-05-16 architecture-audit.md, dimension 7) flagged the
absence of request correlation as a Phase 2 item.
"""
from __future__ import annotations

import contextvars
import uuid

# Default is empty so non-HTTP code (worker threads, watchdog, etc.) just
# emits an empty request_id rather than failing.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="",
)


def gen_request_id() -> str:
    """Short hex id — enough entropy to disambiguate a few thousand
    concurrent requests without bloating every log line."""
    return uuid.uuid4().hex[:12]


def structlog_request_id_processor(_logger, _method_name, event_dict):
    """structlog processor that pulls request_id from the contextvar
    into every log record. Wired in by infra.logging setup if present;
    otherwise the var is still inspectable via request_id_var.get()."""
    rid = request_id_var.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict
