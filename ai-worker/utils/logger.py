"""
Centralised logger for the AI worker pipeline.
All modules import from here — never call logging.basicConfig() in a module.
"""

import logging
import os
import sys

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_formatter)

# Root logger for the entire pipeline
_root = logging.getLogger("pipeline")
_root.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))
_root.addHandler(_handler)
_root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a child logger namespaced under 'pipeline.<name>'."""
    return _root.getChild(name)
