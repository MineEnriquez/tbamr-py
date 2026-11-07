"""Small helpers so stage and agent work shows up in the Logs tab execution capture."""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_MAX_ARG = 120


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= _MAX_ARG else text[: _MAX_ARG - 3] + "..."


def _arg_hint(args: tuple, kwargs: dict) -> str:
    # Skip `self` / `cls` for methods.
    tail = args[1:] if args else ()
    parts = [_short(a) for a in tail[:4]]
    if len(tail) > 4:
        parts.append(f"...+{len(tail) - 4}")
    parts.extend(f"{k}={_short(v)}" for k, v in list(kwargs.items())[:6])
    return ", ".join(parts)


def logged(logger_name: str) -> Callable[[F], F]:
    """Log enter/exit (and errors) at INFO for execution log capture."""

    def deco(fn: F) -> F:
        log = logging.getLogger(logger_name)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            qual = fn.__qualname__
            hint = _arg_hint(args, kwargs)
            log.info("→ %s(%s)", qual, hint or "—")
            t0 = time.perf_counter()
            try:
                out = fn(*args, **kwargs)
            except Exception as e:
                log.info("← %s %s: %s (%.3fs)", qual, type(e).__name__, e, time.perf_counter() - t0)
                raise
            dt = time.perf_counter() - t0
            summary = _short(out) if out is not None else "None"
            log.info("← %s ok (%.3fs) → %s", qual, dt, summary)
            return out

        return wrapper  # type: ignore[return-value]

    return deco
