"""Internal logging configuration for the prescient_sdk package."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOGGER_NAME = "prescient_sdk"
_MANAGED_ATTR = "_prescient_sdk_managed"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure(debug: bool, log_file: str | Path | None) -> None:
    """Configure the ``prescient_sdk`` logger.

    Level is ``DEBUG`` when ``debug`` is ``True``, else ``WARNING``. Output
    goes to ``log_file`` when provided, otherwise to ``stdout``.

    The handler installed here is tagged so subsequent calls remove it
    before attaching a fresh one — making the function idempotent and
    letting the last call win. Handlers added by the host application are
    left untouched.
    """
    logger = logging.getLogger(_LOGGER_NAME)

    for handler in list(logger.handlers):
        if getattr(handler, _MANAGED_ATTR, False):
            logger.removeHandler(handler)
            handler.close()

    handler: logging.Handler
    if log_file is not None:
        handler = logging.FileHandler(Path(log_file))
    else:
        handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _MANAGED_ATTR, True)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)

    logger.setLevel(logging.DEBUG if debug else logging.WARNING)
