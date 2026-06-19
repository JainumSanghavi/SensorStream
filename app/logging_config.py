"""Structured (JSON-line) request logging + middleware.

Each request emits one structured log line with method, path, status, and
latency. Structured logs are greppable and ship cleanly into log aggregators --
far more useful at scale than free-text lines.
"""
import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any structured extras attached via logger.info(..., extra={"ctx": {...}}).
        if isinstance(getattr(record, "ctx", None), dict):
            payload.update(record.ctx)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


access_logger = logging.getLogger("sensorstream.access")


async def request_logging_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    access_logger.info(
        "request",
        extra={
            "ctx": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": elapsed_ms,
            }
        },
    )
    return response
