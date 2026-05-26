import time
from typing import Any, Final, Protocol, runtime_checkable

import numpy as np
import structlog
from structlog import DropEvent
from structlog.typing import EventDict, WrappedLogger

from .render import hex_to_ansi_fg

_PROGRAM_START_TIME = time.time()
_LEVEL_STYLES: Final = {
  "debug": (0x908CAA, 0x827E99, "dbug"),
  "info": (0x9CCFD8, 0x8CBAC2, "info"),
  "warning": (0xF6C177, 0xDDAE6B, "warn"),
  "error": (0xEB6F92, 0xD46483, "eror"),
  "exception": (0xEB6F92, 0xD46483, "exc!"),
}

__all__ = [
  "FloatPrecisionProcessor",
  "LoggerFilterProcessor",
  "compact_level_processor",
  "debug_event_colorer",
  "relative_time_processor",
  "relative_time_processor_plain",
]


class FloatPrecisionProcessor:
  digits: int
  np_array_to_list: bool
  only_fields: set[str]
  not_fields: set[str]

  def __init__(
    self,
    digits: int = 3,
    only_fields: set[str] | None = None,
    not_fields: set[str] | None = None,
    np_array_to_list: bool = True,
  ):
    self.digits = digits
    self.np_array_to_list = np_array_to_list
    self.only_fields = set[str]() if only_fields is None else only_fields
    self.not_fields = set[str]() if not_fields is None else not_fields

  def _round(self, value: Any) -> Any:
    if isinstance(value, float):
      return round(value, self.digits)
    if self.np_array_to_list and isinstance(value, np.ndarray):
      return self._round(list(value))
    if isinstance(value, list):
      for idx, item in enumerate(value):
        value[idx] = self._round(item)
      return value
    if isinstance(value, dict):
      for key, nested_value in value.items():
        value[key] = self._round(nested_value)
      return value
    return value

  def __call__(self, _logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    for key, value in event_dict.items():
      if self.only_fields and key not in self.only_fields:
        continue
      if self.not_fields and key in self.not_fields:
        continue
      if isinstance(value, bool):
        continue
      event_dict[key] = self._round(value)
    return event_dict


@runtime_checkable
class NamedLogger(Protocol):
  name: str


def _logger_name_from_event(logger: object, event_dict: EventDict) -> str:
  if isinstance(logger, NamedLogger):
    return logger.name

  record = event_dict.get("_record")
  if isinstance(record, NamedLogger):
    return record.name

  event_logger_name = event_dict.get("logger_name") or event_dict.get("logger")
  return event_logger_name if isinstance(event_logger_name, str) else ""


class LoggerFilterProcessor:
  logger_name: str
  _child_logger_prefix: str

  def __init__(self, logger_name: str):
    self.logger_name = logger_name
    self._child_logger_prefix = f"{logger_name}."

  def __call__(self, logger: object, _method_name: str, event_dict: EventDict) -> EventDict:
    logger_name = _logger_name_from_event(logger, event_dict)
    if logger_name == self.logger_name or logger_name.startswith(self._child_logger_prefix):
      return event_dict
    raise DropEvent


def relative_time_processor(
  _logger: structlog.stdlib.BoundLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
  """Add relative timestamp since program start with hours:minutes:seconds.milliseconds format."""
  hours, minutes, seconds = _relative_time_parts()

  gray = "\x1b[2m"
  dark_gray = "\x1b[90m"
  reset = "\x1b[0m"

  separator = f"{gray}:{reset}"
  hours_str = f"{gray}{hours:02d}{reset}{separator}" if hours != 0 else ""
  minutes_str = f"{gray}{minutes:02d}{reset}{separator}" if minutes != 0 and hours != 0 else ""
  seconds_str = f"{gray}{seconds:06.3f}{reset}"

  event_dict["timestamp"] = f"{dark_gray}+{reset}{hours_str}{minutes_str}{seconds_str}"
  return event_dict


def relative_time_processor_plain(
  _logger: structlog.stdlib.BoundLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
  """Add relative timestamp without ANSI styling for machine-consumable outputs."""
  hours, minutes, seconds = _relative_time_parts()

  separator = ":"
  hours_str = f"{hours:02d}{separator}" if hours != 0 else ""
  minutes_str = f"{minutes:02d}{separator}" if minutes != 0 and hours != 0 else ""
  seconds_str = f"{seconds:06.3f}"

  event_dict["timestamp"] = f"+{hours_str}{minutes_str}{seconds_str}"
  return event_dict


def compact_level_processor(
  _logger: structlog.stdlib.BoundLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
  """Convert log levels to compact 4-character format with 24-bit colors and darker brackets."""
  reset = "\x1b[0m"

  original_level = event_dict.get("level")
  if not isinstance(original_level, str):
    return event_dict

  if original_level == "critical":
    event_dict["level"] = (
      f"{hex_to_ansi_fg(0xD46483)}[{reset}"
      f"\x1b[48;2;235;111;146;38;2;33;32;46mcrit{reset}"
      f"{hex_to_ansi_fg(0xD46483)}]{reset}"
    )
    return event_dict

  style = _LEVEL_STYLES.get(original_level)
  if style is None:
    return event_dict

  text_color, bracket_color, text = style
  event_dict["level"] = (
    f"{hex_to_ansi_fg(bracket_color)}[{reset}"
    f"{hex_to_ansi_fg(text_color)}{text}{reset}"
    f"{hex_to_ansi_fg(bracket_color)}]{reset}"
  )
  return event_dict


def debug_event_colorer(
  _logger: structlog.stdlib.BoundLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
  """Color the event text purple for debug level messages."""
  level = event_dict.get("level")
  if isinstance(level, str) and "debug" in level.lower() and "event" in event_dict:
    debug_color = hex_to_ansi_fg(0x908CAA)
    event = event_dict.get("event")
    event_dict["event"] = f"{debug_color}{event}\x1b[0m"

  return event_dict


def _relative_time_parts() -> tuple[int, int, float]:
  """Return elapsed (hours, minutes, seconds) since program start."""
  elapsed = time.time() - _PROGRAM_START_TIME
  hours = int(elapsed // 3600)
  minutes = int((elapsed % 3600) // 60)
  seconds = elapsed % 60
  return hours, minutes, seconds
