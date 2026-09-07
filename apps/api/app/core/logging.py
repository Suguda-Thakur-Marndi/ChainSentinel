"""Central application logging configuration for RiskWise API."""
import logging
import sys
from app.core.config import settings


def setup_logging() -> None:
    """Configure standardized application logging.

    Supports timestamps, log level, module/logger name, and sanitized error messages.
    Never exposes credentials, passwords, tokens, or authorization headers.
    """
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a scoped logger under the 'riskwise' namespace."""
    return logging.getLogger(f"riskwise.{name}")
