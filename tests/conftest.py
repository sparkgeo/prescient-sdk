import os

import pytest


@pytest.fixture
def clear_prescient_env(monkeypatch: pytest.MonkeyPatch):
    """Remove every PRESCIENT_* env var so tests aren't polluted by the host shell."""
    for key in list(os.environ):
        if key.upper().startswith("PRESCIENT_"):
            monkeypatch.delenv(key)


@pytest.fixture
def set_env_vars(monkeypatch: pytest.MonkeyPatch, clear_prescient_env):
    """fixture to set the config settings as env variables"""
    monkeypatch.setenv(
        "PRESCIENT_ENDPOINT_URL", "https://spk-sandbox.staging.prescient.earth"
    )
    monkeypatch.setenv("PRESCIENT_API_KEY", "pk_test")
