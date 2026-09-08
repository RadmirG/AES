from __future__ import annotations

import logging
from unittest.mock import Mock, patch

from aes_agent import logging_config
from aes_agent.logging_config import RecentLogHandler, recent_log_entries, log_value


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


def test_log_preview_does_not_traverse_full_solution_arrays():
    class GuardedSamples(list):
        def __iter__(self):
            for index, value in enumerate(super().__iter__()):
                assert index < 20, "preview scanned the full field"
                yield value

    samples = GuardedSamples(range(10000))
    preview = log_value({"field_samples": samples, "password": "hidden"}, max_chars=1200)
    assert "omitted" in preview
    assert "hidden" not in preview
    assert len(preview) <= 1200


def test_log_preview_bounds_file_content_before_redaction():
    content = "token=hidden " + "x" * 1000000
    with patch.object(logging_config, "_sanitize_string", wraps=logging_config._sanitize_string) as sanitize:
        preview = log_value({"content": content}, max_chars=1200)
    assert all(len(call.args[0]) <= 1200 for call in sanitize.call_args_list)
    assert "hidden" not in preview
    assert len(preview) <= 1200


def test_log_preview_handles_cycles_and_does_not_stringify_large_objects():
    value = []
    value.append(value)
    assert "omitted" in log_value(value)

    class LargeObject:
        def __str__(self):
            raise AssertionError("preview rendered an arbitrary full object")

    assert "LargeObject" in log_value(LargeObject())


def test_disabled_log_level_does_not_prepare_content(monkeypatch):
    monkeypatch.setenv("AES_LOG_CONTENT", "true")
    logger = Mock()
    logger.isEnabledFor.return_value = False
    with patch.object(logging_config, "log_value") as render:
        logging_config.log_content_preview(logger, "unused", {"large": "data"})
    render.assert_not_called()
