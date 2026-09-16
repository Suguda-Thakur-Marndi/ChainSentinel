"""Central application logging configuration for RiskWise API.

Supports:
- Structured JSON logging in production environments (CloudWatch compatible)
- Standard readable logging in development/test
- Contextual correlation: request_id, trace_id, organization_id
- Sensitive data scrubbing filter (prevents credential/token leaks)
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any, Dict

from app.core.config import settings

# Patterns of sensitive keywords to scrub from log messages
SENSITIVE_PATTERNS = [
    re.compile(r'(?i)(password|secret|token|api[_-]?key|bearer)\s*[:=]\s*["\']?([^"\'\s,]+)["\']?'),
    re.compile(r'(?i)(authorization\s*:\s*bearer)\s+([^\s,]+)'),
    re.compile(r'(AKIA[0-9A-Z]{16})'),
]


class SecretScrubbingFilter(logging.Filter):
    """Filters log records to mask credentials, API keys, and sensitive tokens."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            for pattern in SENSITIVE_PATTERNS:
                msg = pattern.sub(r"\1: [REDACTED]", msg)
            record.msg = msg
        return True


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON for CloudWatch/production ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "riskwise-api",
            "environment": settings.APP_ENV,
        }

        # Include contextual attributes if attached to record
        for attr in ("request_id", "trace_id", "organization_id", "operation", "latency_ms"):
            if hasattr(record, attr):
                log_entry[attr] = getattr(record, attr)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging() -> None:
    """Configure standardized application logging based on environment."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SecretScrubbingFilter())

    if settings.APP_ENV.lower() == "production":
        formatter = JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    """Return a scoped logger under the 'riskwise' namespace."""
    return logging.getLogger(f"riskwise.{name}")
