"""Compatibility wrapper for centralized logging configuration."""

from .logging import get_logger, setup_logging, setup_logging_from_env

__all__ = ["get_logger", "setup_logging", "setup_logging_from_env"]
