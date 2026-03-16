"""Production logging with simple colored default and OLTP/OTLP-friendly mode."""

import json
import logging
import logging.config
import os
import sys
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


class LogfmtFormatter(logging.Formatter):
    """Readable and machine-parseable formatter for Loki/Grafana pipelines."""

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
    _colors = {
        "DEBUG": "\x1b[36m",
        "INFO": "\x1b[32m",
        "WARNING": "\x1b[33m",
        "ERROR": "\x1b[31m",
        "CRITICAL": "\x1b[35m",
    }
    _reset = "\x1b[0m"

    def __init__(self, *, enable_color: bool):
        super().__init__()
        self.enable_color = enable_color

    @staticmethod
    def _quote(value: Any) -> str:
        text = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'

    def format(self, record: logging.LogRecord) -> str:
        level_value: str = record.levelname.lower()
        if self.enable_color:
            color = self._colors.get(record.levelname, "")
            if color:
                level_value = f"{color}{level_value}{self._reset}"

        fields: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": level_value,
            "logger": record.name,
            "msg": record.getMessage(),
            "req_id": getattr(record, "request_id", "-"),
            "pid": record.process,
        }

        for key, value in record.__dict__.items():
            if key not in self._reserved and key not in fields:
                fields[key] = value

        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)

        parts = []
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                parts.append(f"{key}={value}")
            else:
                parts.append(f"{key}={self._quote(value)}")
        return " ".join(parts)


class ColorTextFormatter(logging.Formatter):
    """Human-friendly colored formatter for interactive debugging."""

    _colors = {
        "DEBUG": "\x1b[36m",
        "INFO": "\x1b[32m",
        "WARNING": "\x1b[33m",
        "ERROR": "\x1b[31m",
        "CRITICAL": "\x1b[35m",
    }
    _reset = "\x1b[0m"

    def __init__(self, *, enable_color: bool):
        super().__init__()
        self.enable_color = enable_color

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        if self.enable_color:
            color = self._colors.get(level, "")
            level = f"{color}{level}{self._reset}" if color else level

        base = (
            f"{ts} {level:<18} {record.name} "
            f"[pid={record.process} req_id={getattr(record, 'request_id', '-')}] {record.getMessage()}"
        )
        if record.exc_info:
            return f"{base}\n{self.formatException(record.exc_info)}"
        return base


def configure_logging() -> None:
    """Configure root/app/server loggers for production-friendly output."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "").strip().lower()
    if not log_format:
        log_format = "json" if os.getenv("LOG_JSON", "0") == "1" else "simple"

    if log_format in {"otlp", "oltp"}:
        log_format = "logfmt"
    if log_format == "color":
        log_format = "simple"

    color_mode = os.getenv("LOG_COLOR", "1").lower()
    enable_color = (
        color_mode == "1" or (color_mode == "auto" and hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
    )

    if log_format not in {"simple", "text", "logfmt", "json"}:
        log_format = "simple"

    server_access_logs = os.getenv("ENABLE_SERVER_ACCESS_LOGS", "0") == "1"
    server_access_level = log_level if server_access_logs else "WARNING"

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
                "text": {
                    "format": "%(asctime)s %(levelname)s %(name)s [pid=%(process)d req_id=%(request_id)s] %(message)s"
                },
                "simple": {
                    "()": "logging_config.ColorTextFormatter",
                    "enable_color": enable_color,
                },
                "logfmt": {
                    "()": "logging_config.LogfmtFormatter",
                    "enable_color": enable_color,
                },
                "json": {"()": "logging_config.JsonFormatter"},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "level": log_level,
                    "formatter": log_format,
                    "filters": ["request_id"],
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {
                "level": log_level,
                "handlers": ["default"],
            },
            "loggers": {
                # Keep framework logs routed through the same formatter.
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
