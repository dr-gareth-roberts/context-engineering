from __future__ import annotations

import logging
import os
from typing import Literal

import structlog

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def configure_structlog(*, level: LogLevel | None = None) -> None:
    """Configure structlog for JSON logs.

    This keeps configuration centralized so CLI tools and FastAPI share the same
    log shape (helpful for production observability and audit trails).

    Args:
        level: Optional log level override. Defaults to `LOG_LEVEL` env var or INFO.
    """

    resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(level=getattr(logging, resolved_level, logging.INFO))

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, resolved_level, logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
