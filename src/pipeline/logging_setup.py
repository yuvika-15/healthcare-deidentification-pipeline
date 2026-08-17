import json
import logging
import sys
import time
from typing import Any

# Standard LogRecord attributes to ignore when extracting custom extra fields
STANDARD_LOG_ATTRS = {
    "args", "msg", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno",
    "funcName", "created", "msecs", "relativeCreated", "thread",
    "threadName", "processName", "process", "name",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 1. Capture stack traces and exception data if present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exception"] = record.exc_text

        if record.stack_info:
            payload["stack_trace"] = self.formatStack(record.stack_info)

        # 2. Dynamically attach extra context 
        for key, value in record.__dict__.items():
            if key not in STANDARD_LOG_ATTRS and key not in payload:
                payload[key] = value

        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configures structured JSON logging on the root logger for stdout output."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())