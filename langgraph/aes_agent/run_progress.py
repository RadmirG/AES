"""Request-scoped progress reporting, propagated through LangGraph's context."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

_sink: ContextVar[Callable[[str, str], None] | None] = ContextVar("run_progress", default=None)


@contextmanager
def use_run_progress(sink: Callable[[str, str], None]):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def report_progress(node: str, phase: str) -> None:
    sink = _sink.get()
    if sink is not None:
        sink(node, phase)
