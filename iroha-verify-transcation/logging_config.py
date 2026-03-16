"""Production-oriented logging setup with optional JSON output."""

import json
import logging
import logging.config
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    _request_id_ctx.set(request_id)


def clear_request_id() -> None:
    _request_id_ctx.set("-")


def get_request_id() -> str:
    return _request_id_ctx.get()


class RequestIdFilter(logging.Filter):
    """Inject request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JsonFormatter(logging.Formatter):
    """Compact JSON formatter for centralized log systems."""

    _reserved = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "process": record.process,
        }

        for key, value in record.__dict__.items():
            if key not in self._reserved and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True, default=str)


def configure_logging() -> None:
    """Configure root/app/server loggers for production-friendly output."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    use_json_logs = os.getenv("LOG_JSON", "1") == "1"
    server_access_logs = os.getenv("ENABLE_SERVER_ACCESS_LOGS", "0") == "1"
    server_access_level = log_level if server_access_logs else "WARNING"

    formatter_name = "json" if use_json_logs else "text"
    text_format = (
        "%(asctime)s %(levelname)s %(name)s [pid=%(process)d req_id=%(request_id)s] %(message)s"
    )

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {
                    "()": "logging_config.RequestIdFilter",
                }
            },
            "formatters": {
                "text": {"format": text_format},
                "json": {"()": "logging_config.JsonFormatter"},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "level": log_level,
                    "formatter": formatter_name,
                    "filters": ["request_id"],
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {
                "level": log_level,
                "handlers": ["default"],
            },
            "loggers": {
                "uvicorn": {"level": log_level, "handlers": ["default"], "propagate": False},
                "uvicorn.error": {"level": log_level, "handlers": ["default"], "propagate": False},
                "uvicorn.access": {
                    "level": server_access_level,
                    "handlers": ["default"],
                    "propagate": False,
                },
                "gunicorn": {"level": log_level, "handlers": ["default"], "propagate": False},
                "gunicorn.error": {"level": log_level, "handlers": ["default"], "propagate": False},
                "gunicorn.access": {
                    "level": server_access_level,
                    "handlers": ["default"],
                    "propagate": False,
                },
            },
        }
    )
