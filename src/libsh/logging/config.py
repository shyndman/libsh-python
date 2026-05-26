import logging
import os
from typing import Final, cast

import structlog
from structlog.typing import Processor

from .processors import (
  FloatPrecisionProcessor,
  LoggerFilterProcessor,
  compact_level_processor,
  debug_event_colorer,
  relative_time_processor,
  relative_time_processor_plain,
)
from .render import build_console_renderer

_MANAGED_ROOT_HANDLER_ATTR: Final = "_libsh_managed_root_handler"
_JSON_ENV_TRUTHY: Final = frozenset({"true", "1", "yes", "on"})
_PROPAGATING_LIBRARY_LOGGERS: Final = ("websockets",)


def setup_logging(
  level: str = "INFO",
  json_output: bool = False,
  correlation_id: str | None = None,
  filter_to_logger: str | None = None,
) -> None:
  """Configure structured logging for the application."""
  processors: list[Processor] = []
  _ = structlog.contextvars.unbind_contextvars("correlation_id")
  if correlation_id:
    processors.append(structlog.contextvars.merge_contextvars)
    _ = structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

  processors.append(structlog.stdlib.filter_by_level)
  if filter_to_logger:
    processors.append(LoggerFilterProcessor(filter_to_logger))

  processors.extend(
    [
      structlog.stdlib.add_logger_name,
      structlog.stdlib.add_log_level,
    ]
  )

  if json_output:
    processors.extend(
      [
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        FloatPrecisionProcessor(digits=3),
        relative_time_processor_plain,
        structlog.processors.StackInfoRenderer(),
      ]
    )
  else:
    processors.extend(
      [
        debug_event_colorer,
        compact_level_processor,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        FloatPrecisionProcessor(digits=3),
        relative_time_processor,
        structlog.processors.StackInfoRenderer(),
      ]
    )

  log_renderer: Processor
  if json_output:
    log_renderer = structlog.processors.JSONRenderer()
  else:
    log_renderer = build_console_renderer()

  formatter_pre_chain: list[Processor] = [
    proc
    for proc in processors
    if proc is not structlog.stdlib.filter_by_level and not isinstance(proc, LoggerFilterProcessor)
  ]

  structlog.configure(
    processors=processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
  )

  formatter = structlog.stdlib.ProcessorFormatter(
    foreign_pre_chain=formatter_pre_chain,
    processors=[
      structlog.stdlib.ProcessorFormatter.remove_processors_meta,
      log_renderer,
    ],
  )

  root_logger = logging.getLogger()
  _replace_managed_root_handler(root_logger, formatter, level, filter_to_logger)
  _configure_library_loggers()


def get_logger(
  name: str | None = None, *args: object, **initial_values: object
) -> structlog.stdlib.BoundLogger:
  """Get a structured logger instance."""
  if name is None:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(*args, **initial_values))

  return cast(
    structlog.stdlib.BoundLogger,
    structlog.get_logger(name, *args, **initial_values),
  )


def setup_logging_from_env() -> None:
  """Setup logging using environment variables."""
  log_level = os.getenv("LOG_LEVEL", "INFO").upper()
  json_output = os.getenv("JSON_LOGS", "false").lower() in _JSON_ENV_TRUTHY
  correlation_id = os.getenv("CORRELATION_ID")

  setup_logging(level=log_level, json_output=json_output, correlation_id=correlation_id)


def _replace_managed_root_handler(
  root_logger: logging.Logger,
  formatter: logging.Formatter,
  level: str,
  filter_to_logger: str | None,
) -> None:
  managed_handlers = [
    handler
    for handler in root_logger.handlers
    if getattr(handler, _MANAGED_ROOT_HANDLER_ATTR, False)
  ]
  for handler in managed_handlers:
    root_logger.removeHandler(handler)
    handler.close()

  handler = logging.StreamHandler()
  handler.setFormatter(formatter)
  if filter_to_logger:
    handler.addFilter(logging.Filter(filter_to_logger))
  setattr(handler, _MANAGED_ROOT_HANDLER_ATTR, True)
  root_logger.addHandler(handler)
  root_logger.setLevel(level)


def _configure_library_loggers() -> None:
  for liblog_name in _PROPAGATING_LIBRARY_LOGGERS:
    liblog = logging.getLogger(liblog_name)
    liblog.handlers.clear()
    liblog.setLevel(logging.WARNING)
    liblog.propagate = True
