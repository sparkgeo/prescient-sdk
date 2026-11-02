import pytest

from prescient_sdk.config import MIGRATION_URL, Settings


def make_settings(**kwargs) -> Settings:
    kwargs.setdefault("prescient_api_key", "pk_secret_value")
    return Settings(**kwargs)


def test_realm_is_first_dns_label(clear_prescient_env):
    settings = make_settings(
        prescient_endpoint_url="https://spk-sandbox.staging.prescient.earth"
    )
    assert settings.realm == "spk-sandbox"


@pytest.mark.parametrize(
    ("endpoint", "auth_url", "expected"),
    [
        (
            "https://spk-sandbox.staging.prescient.earth",
            None,
            "https://keycloak.staging.prescient.earth",
        ),
        ("https://acme.prescient.earth", None, "https://keycloak.prescient.earth"),
        (
            "https://acme.prescient.earth",
            "https://auth.example.com/",
            "https://auth.example.com",
        ),
    ],
)
def test_keycloak_url(clear_prescient_env, endpoint, auth_url, expected):
    settings = make_settings(
        prescient_endpoint_url=endpoint, prescient_auth_url=auth_url
    )
    assert settings.keycloak_url == expected


def test_removed_setting_in_env_var_raises(
    monkeypatch: pytest.MonkeyPatch, set_env_vars
):
    monkeypatch.setenv("Prescient_Client_Id", "some-client-id")
    with pytest.raises(ValueError, match="prescient_client_id") as excinfo:
        Settings()  # type: ignore[call-arg]
    assert MIGRATION_URL in str(excinfo.value)


def test_removed_setting_in_env_file_raises(clear_prescient_env, tmp_path):
    env_file = tmp_path / "config.env"
    env_file.write_text(
        "PRESCIENT_ENDPOINT_URL=https://spk-sandbox.staging.prescient.earth\n"
        "PRESCIENT_API_KEY=pk_secret_value\n"
        "PRESCIENT_AWS_ROLE=arn:aws:iam::123:role/x\n"
        "PRESCIENT_UPLOAD_BUCKET=bucket\n"
    )
    with pytest.raises(ValueError) as excinfo:
        Settings(_env_file=env_file)  # type: ignore[call-arg]
    message = str(excinfo.value)
    assert "prescient_aws_role" in message
    assert "prescient_upload_bucket" in message
    assert MIGRATION_URL in message
    assert "pk_secret_value" not in message


def test_api_key_not_in_repr(clear_prescient_env):
    settings = make_settings(
        prescient_endpoint_url="https://spk-sandbox.staging.prescient.earth"
    )
    assert "pk_secret_value" not in repr(settings)
    assert "pk_secret_value" not in str(settings)
    assert settings.prescient_api_key.get_secret_value() == "pk_secret_value"


def test_api_key_required(monkeypatch: pytest.MonkeyPatch, clear_prescient_env):
    monkeypatch.setenv(
        "PRESCIENT_ENDPOINT_URL", "https://spk-sandbox.staging.prescient.earth"
    )
    with pytest.raises(ValueError, match="prescient_api_key"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_endpoint_without_scheme_is_rejected(clear_prescient_env):
    with pytest.raises(ValueError, match="full URL with a host"):
        Settings(
            prescient_endpoint_url="spk-sandbox.staging.prescient.earth",
            prescient_api_key="pk_test",
        )
