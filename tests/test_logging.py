import logging
from pathlib import Path

import pytest

from prescient_sdk import _logging
from prescient_sdk.client import PrescientClient
from prescient_sdk.ingest_client import IngestClient


@pytest.fixture(autouse=True)
def reset_sdk_logger():
    """Strip handlers/level off the prescient_sdk logger between tests."""
    logger = logging.getLogger("prescient_sdk")
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    saved_propagate = logger.propagate
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    yield
    logger.handlers.clear()
    for handler in saved_handlers:
        logger.addHandler(handler)
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate


def _managed_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if getattr(h, "_prescient_sdk_managed", False)]


def test_default_warning_to_stdout(set_env_vars, capsys):
    PrescientClient()

    logger = logging.getLogger("prescient_sdk")
    assert logger.level == logging.WARNING

    logger.info("info-msg")
    logger.warning("warn-msg")

    out = capsys.readouterr().out
    assert "warn-msg" in out
    assert "info-msg" not in out


def test_debug_to_stdout(set_env_vars, capsys):
    PrescientClient(debug=True)

    logger = logging.getLogger("prescient_sdk")
    assert logger.level == logging.DEBUG

    logger.debug("debug-msg")
    logger.info("info-msg")

    out = capsys.readouterr().out
    assert "debug-msg" in out
    assert "info-msg" in out


def test_warning_to_file(set_env_vars, tmp_path: Path):
    log_file = tmp_path / "a.log"
    PrescientClient(log_file=log_file)

    logger = logging.getLogger("prescient_sdk")
    logger.info("info-msg")
    logger.warning("warn-msg")

    for h in _managed_handlers(logger):
        h.flush()

    contents = log_file.read_text()
    assert "warn-msg" in contents
    assert "info-msg" not in contents


def test_debug_to_file(set_env_vars, tmp_path: Path):
    log_file = tmp_path / "b.log"
    PrescientClient(debug=True, log_file=log_file)

    logger = logging.getLogger("prescient_sdk")
    logger.debug("debug-msg")
    logger.info("info-msg")

    for h in _managed_handlers(logger):
        h.flush()

    contents = log_file.read_text()
    assert "debug-msg" in contents
    assert "info-msg" in contents


def test_idempotent_single_handler():
    _logging.configure(True, None)
    _logging.configure(True, None)

    logger = logging.getLogger("prescient_sdk")
    assert len(_managed_handlers(logger)) == 1


def test_last_call_wins(tmp_path: Path):
    log_file = tmp_path / "first.log"
    _logging.configure(False, log_file)
    _logging.configure(False, None)

    logger = logging.getLogger("prescient_sdk")
    managed = _managed_handlers(logger)
    assert len(managed) == 1
    assert isinstance(managed[0], logging.StreamHandler)
    assert not isinstance(managed[0], logging.FileHandler)


def test_preserves_host_handlers():
    logger = logging.getLogger("prescient_sdk")
    host_handler = logging.StreamHandler()
    logger.addHandler(host_handler)

    _logging.configure(True, None)

    assert host_handler in logger.handlers
    assert len(_managed_handlers(logger)) == 1


def test_ingest_client_configures_same_logger(set_env_vars):
    IngestClient(debug=True)

    logger = logging.getLogger("prescient_sdk")
    assert logger.level == logging.DEBUG
    assert len(_managed_handlers(logger)) == 1
