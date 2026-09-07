from __future__ import annotations

import logging

from aes_agent.logging_config import RecentLogHandler, recent_log_entries


def test_recent_log_handler_keeps_bounded_redacted_records():
    existing = recent_log_entries(limit=1000)
    after = existing[-1]["sequence"] if existing else 0
    record = logging.LogRecord(
        name="aes_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="model request token=secret-value password=hunter2",
        args=(),
        exc_info=None,
    )
    record.component = "langgraph"

    RecentLogHandler().emit(record)

    entries = recent_log_entries(after=after, limit=10)
    assert len(entries) == 1
    assert entries[0]["component"] == "langgraph"
    assert entries[0]["logger"] == "aes_agent.test"
    assert "secret-value" not in entries[0]["message"]
    assert "hunter2" not in entries[0]["message"]
    assert entries[0]["message"].count("***redacted***") == 2
