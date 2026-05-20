"""Structured JSON logging for uvicorn + the app.

Wires python-json-logger into the root logger and the two uvicorn loggers so
every line in stdout is a single JSON object suitable for ingestion.
"""

from __future__ import annotations

import logging
import sys


def configure_json_logging(level: int = logging.INFO) -> None:
    try:
        from pythonjsonlogger import jsonlogger
    except ImportError:  # pragma: no cover — package optional in tests
        logging.basicConfig(level=level)
        return

    handler = logging.StreamHandler(sys.stdout)
    fmt = jsonlogger.JsonFormatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "ts", "levelname": "level"},
    )
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
        lg.setLevel(level)
