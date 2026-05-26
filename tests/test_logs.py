from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator, Sequence
from contextlib import redirect_stderr
from typing import TypedDict

import pytest
import structlog

from libsh import get_logger, setup_logging, setup_logging_from_env


class LoggerState(TypedDict):
  handlers: Sequence[logging.Handler]
  level: int
  disabled: bool
  propagate: bool


@pytest.fixture(autouse=True)
def isolated_logging_state() -> Iterator[None]:
  root_logger = logging.getLogger()
  original_root_handlers = list(root_logger.handlers)
  original_root_filters = list(root_logger.filters)
  original_root_level = root_logger.level
  original_logger_dict = dict(root_logger.manager.loggerDict)
  original_logger_states = {
    name: _snapshot_logger_state(logger)
    for name, logger in original_logger_dict.items()
    if isinstance(logger, logging.Logger)
  }

  root_logger.handlers.clear()
  root_logger.filters.clear()
  structlog.reset_defaults()
  structlog.contextvars.clear_contextvars()

  try:
    yield
  finally:
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()

    root_logger.handlers[:] = original_root_handlers
    root_logger.filters[:] = original_root_filters
    root_logger.setLevel(original_root_level)

    root_logger.manager.loggerDict.clear()
    root_logger.manager.loggerDict.update(original_logger_dict)
    for name, state in original_logger_states.items():
      logger = root_logger.manager.loggerDict.get(name)
      if isinstance(logger, logging.Logger):
        _restore_logger_state(logger, state)


def test_setup_logging_is_idempotent_for_root_stream_handlers() -> None:
  stderr = io.StringIO()
  root_logger = logging.getLogger()

  with redirect_stderr(stderr):
    baseline_handler_count = len(root_logger.handlers)
    setup_logging()
    first_handler_count = len(root_logger.handlers)

    setup_logging()
    second_handler_count = len(root_logger.handlers)

    logging.getLogger("tests.idempotent").info("idempotent-sentinel")

  assert first_handler_count == baseline_handler_count + 1
  assert second_handler_count == baseline_handler_count + 1
  assert len([line for line in stderr.getvalue().splitlines() if line.strip()]) == 1


def test_setup_logging_json_output_formats_structlog_and_stdlib() -> None:
  stderr = io.StringIO()

  with redirect_stderr(stderr):
    setup_logging(json_output=True)
    get_logger("tests.json.struct").info("struct-event", answer=42)
    logging.getLogger("tests.json.stdlib").info("stdlib-event")

  records = _parse_json_lines(stderr.getvalue())

  assert len(records) == 2
  assert {record["event"] for record in records} == {"struct-event", "stdlib-event"}
  assert next(record for record in records if record["event"] == "struct-event")["answer"] == 42


def test_filter_to_logger_keeps_matching_records_and_drops_others() -> None:
  stderr = io.StringIO()

  with redirect_stderr(stderr):
    setup_logging(json_output=True, filter_to_logger="tests.allowed")
    get_logger("tests.allowed").info("keep-struct")
    logging.getLogger("tests.allowed.child").info("keep-stdlib-child")
    get_logger("tests.blocked").info("drop-struct")
    logging.getLogger("tests.other").info("drop-stdlib")

  records = _parse_json_lines(stderr.getvalue())

  assert {record["event"] for record in records} == {"keep-struct", "keep-stdlib-child"}


def test_setup_logging_from_env_honors_level_json_and_correlation_id(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setenv("LOG_LEVEL", "error")
  monkeypatch.setenv("JSON_LOGS", "yes")
  monkeypatch.setenv("CORRELATION_ID", "corr-123")

  stderr = io.StringIO()

  with redirect_stderr(stderr):
    setup_logging_from_env()
    get_logger("tests.env").info("info-should-be-dropped")
    get_logger("tests.env").error("env-event")

  records = _parse_json_lines(stderr.getvalue())

  assert logging.getLogger().getEffectiveLevel() == logging.ERROR
  assert len(records) == 1
  assert records[0]["event"] == "env-event"
  assert records[0]["correlation_id"] == "corr-123"
def _parse_json_lines(output: str) -> list[dict[str, object]]:
  return [json.loads(line) for line in output.splitlines() if line.strip()]


def _snapshot_logger_state(logger: logging.Logger) -> LoggerState:
  state: LoggerState = {
    "handlers": list(logger.handlers),
    "level": logger.level,
    "disabled": logger.disabled,
    "propagate": logger.propagate,
  }
  return state


def _restore_logger_state(logger: logging.Logger, state: LoggerState) -> None:
  logger.handlers[:] = state["handlers"]
  logger.setLevel(state["level"])
  logger.disabled = state["disabled"]
  logger.propagate = state["propagate"]
