import re
from collections.abc import Callable
from dataclasses import dataclass, field
from io import StringIO

from structlog.dev import BRIGHT, DIM, RESET_ALL, Column, ConsoleRenderer, KeyValueColumnFormatter


def _write(sio: StringIO, value: str) -> None:
  _ = sio.write(value)


def _pad_value(value: str, width: int) -> str:
  if width <= 0:
    return value

  return value.ljust(width)


def hex_to_ansi_fg(hex_color: int) -> str:
  """Convert hex color (e.g., 0xad8a89) to ANSI 24-bit foreground escape code."""
  r = (hex_color >> 16) & 0xFF
  g = (hex_color >> 8) & 0xFF
  b = hex_color & 0xFF
  return f"\x1b[38;2;{r};{g};{b}m"


@dataclass
class RegexValueColumnFormatter:
  """
  Format a key-value pair with regex-based value styling.

  Like KeyValueColumnFormatter, but allows mapping values to styles based on
  regular expression patterns.

  :param key_style: The style to apply to the key. If None, the key is omitted.
  :param value_style_map: A list of (regex_pattern, style) tuples. The first
      pattern that matches the value will determine its style.
  :param default_value_style: The style to use if no regex patterns match.
  :param reset_style: The style to apply whenever a style is no longer needed.
  :param value_repr: A callable that returns the string representation of the value.
  :param width: The width to pad the value to. If 0, no padding is done.
  :param prefix: A string to prepend to the formatted key-value pair. May contain
      styles.
  :param postfix: A string to append to the formatted key-value pair. May contain
      styles.
  """

  key_style: str | None
  value_style_map: list[tuple[str, str]]
  default_value_style: str
  reset_style: str
  value_repr: Callable[[object], str]
  width: int = 0
  prefix: str = ""
  postfix: str = ""
  _compiled_patterns: list[tuple[re.Pattern[str], str]] = field(init=False, repr=False)

  def __post_init__(self) -> None:
    """Compile regex patterns for efficiency."""
    self._compiled_patterns = [
      (re.compile(pattern), style) for pattern, style in self.value_style_map
    ]

  def __call__(self, key: str, value: object) -> str:
    sio = StringIO()

    if self.prefix:
      _write(sio, self.prefix)
      _write(sio, self.reset_style)

    if self.key_style is not None:
      _write(sio, self.key_style)
      _write(sio, key)
      _write(sio, self.reset_style)
      _write(sio, "=")

    value_str = self.value_repr(value)
    value_style = self.default_value_style

    for pattern, style in self._compiled_patterns:
      if pattern.search(value_str):
        value_style = style
        break

    _write(sio, value_style)
    _write(sio, _pad_value(value_str, self.width))
    _write(sio, self.reset_style)

    if self.postfix:
      _write(sio, self.postfix)
      _write(sio, self.reset_style)

    return sio.getvalue()


def build_console_renderer() -> ConsoleRenderer:
  event_key = "event"
  timestamp_key = "timestamp"
  logger_name_formatter = KeyValueColumnFormatter(
    key_style=None,
    value_style=hex_to_ansi_fg(0x7D6B95),
    reset_style=RESET_ALL,
    value_repr=str,
    prefix="[",
    postfix="]",
  )

  return ConsoleRenderer(
    colors=True,
    columns=[
      Column(
        "",
        RegexValueColumnFormatter(
          key_style=hex_to_ansi_fg(0x6E6A86),
          value_style_map=[
            (r"^(True|False)$", hex_to_ansi_fg(0x6E6A86)),
            (r"^-?\d+$", hex_to_ansi_fg(0xF6C177)),
            (r"^-?\d*\.\d+$", hex_to_ansi_fg(0xF6C177)),
            (r"^-?\d*\.?\d+(?:h|m|s|ms|us|µs)$", hex_to_ansi_fg(0x9CCFD8)),
          ],
          default_value_style="",
          reset_style=RESET_ALL,
          value_repr=str,
        ),
      ),
      Column(
        timestamp_key,
        KeyValueColumnFormatter(
          key_style=None,
          value_style=DIM,
          reset_style=RESET_ALL,
          value_repr=str,
        ),
      ),
      Column(
        "level",
        KeyValueColumnFormatter(
          key_style=None,
          value_style="",
          reset_style=RESET_ALL,
          value_repr=str,
        ),
      ),
      Column("logger_name", logger_name_formatter),
      Column("logger", logger_name_formatter),
      Column(
        event_key,
        KeyValueColumnFormatter(
          key_style=None,
          value_style=BRIGHT,
          reset_style=RESET_ALL,
          value_repr=str,
          width=30,
        ),
      ),
    ],
  )
