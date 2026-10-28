"""Execution log capture.

Every substantial user-triggered action (stage run, gate approval, hold resolution, TB-Profiler
batch, …) is wrapped in `capture_execution(...)`. For the duration of the `with` block, all
log output on the root logger — our own loggers, httpx request lines, uvicorn errors, agent
traces that use logging — is tee'd into an in-memory buffer, then persisted as one row in the
`executions` table at the end. The UI's Logs tab reads these rows: the user sees a scoped
log for each operation they triggered, not an unbounded live tail.

Captures are thread-local: a background TB-Profiler worker's logs go only to that worker's
execution, not to other requests served concurrently.
"""
from __future__ import annotations

import io
import logging
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Iterator

from .decisions import DecisionLog


_tls = threading.local()


class _TLSHandler(logging.Handler):
    """A handler that writes to the thread-local buffer stack (so concurrent executions don't bleed into each other)."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        try:
            stack = getattr(_tls, "stack", None)
            if not stack:
                return
            msg = self.format(record)
            stack[-1].write(msg + "\n")
            if record.exc_info:
                stack[-1].write("".join(traceback.format_exception(*record.exc_info)))
        except Exception:
            pass


_handler: _TLSHandler | None = None


def _install_handler() -> None:
    global _handler
    if _handler is not None:
        return
    _handler = _TLSHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(_handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    # Uvicorn/fastapi loggers propagate=False by default; flip them on so our handler sees them.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "httpx"):
        lg = logging.getLogger(name)
        lg.propagate = True
        if lg.level == 0:
            lg.setLevel(logging.INFO)


@contextmanager
def capture_execution(log: DecisionLog, trigger: str) -> Iterator[io.StringIO]:
    """Capture logs emitted on this thread for the duration of the block, then persist as one execution."""
    _install_handler()
    buf = io.StringIO()
    stack: list[io.StringIO] = getattr(_tls, "stack", None) or []
    if not stack:
        _tls.stack = stack
    stack.append(buf)
    start = time.time()
    status = "ok"
    error = ""
    logging.getLogger("tbamr.executions").info("Start: %s", trigger)
    try:
        yield buf
    except Exception as e:
        status = "error"
        error = f"{type(e).__name__}: {e}"
        logging.getLogger("tbamr.executions").exception("Failed: %s", trigger)
        raise
    finally:
        logging.getLogger("tbamr.executions").info("End: %s (%s)", trigger, status)
        stack.pop()
        end = time.time()
        try:
            log.add_execution(trigger, start, end, status, buf.getvalue(), error)
        except Exception:
            pass  # never let a logging failure break the real action
