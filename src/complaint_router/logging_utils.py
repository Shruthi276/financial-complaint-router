"""Uniform logging setup shared by pipeline stages and services."""

from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to stdout (picked up by ``docker logs``).

    The level comes from the ``LOG_LEVEL`` environment variable (default INFO).
    """
    root = logging.getLogger()
    if not getattr(root, "_complaint_router_configured", False):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
        root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
        root._complaint_router_configured = True  # type: ignore[attr-defined]
    return logging.getLogger(name)
