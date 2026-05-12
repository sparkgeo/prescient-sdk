import os
import datetime
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockType, MockerFixture
import boto3
from botocore.stub import Stubber

from prescient_sdk.client import PrescientClient
from prescient_sdk.config import Settings


@pytest.fixture
def clear_prescient_env(monkeypatch: pytest.MonkeyPatch):
    """Remove every PRESCIENT_* env var so tests aren't polluted by the host shell."""
    for key in list(os.environ):
        if key.startswith("PRESCIENT_"):
            monkeypatch.delenv(key)


@pytest.fixture
def set_env_vars(monkeypatch: pytest.MonkeyPatch, clear_prescient_env):
    """fixture to set the config settings as env variables"""
    monkeypatch.setenv("PRESCIENT_ENDPOINT_URL", "https://example.server.prescient.earth")
    monkeypatch.setenv("PRESCIENT_AWS_REGION", "some-aws-region")
    monkeypatch.setenv("PRESCIENT_AWS_ROLE", "arn:aws:iam::something")
    monkeypatch.setenv("PRESCIENT_TENANT_ID", "some-tenant-id")
    monkeypatch.setenv("PRESCIENT_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("PRESCIENT_AUTH_URL", "https://login.somewhere.com/")
    monkeypatch.setenv("PRESCIENT_AUTH_TOKEN_PATH", "/oauth2/v2.0/token")


@pytest.fixture
def mock_creds(mocker: MockerFixture, set_env_vars):
    """fixture to mock the auth credentials property"""
    mock = mocker.patch(
        "prescient_sdk.client.PrescientClient.auth_credentials",
        new_callable=mocker.PropertyMock,
        return_value={"id_token": "mock_token"},
    )
    return mock


@pytest.fixture
def auth_client_mock(mocker: MockerFixture):
    """Fixture for mocking msal library"""

    class MockApp:
        def __init__(self, client_id=None, authority=None):
            pass

        def acquire_token_by_refresh_token(self, refresh_token, scopes):
            return {
                "expires_in": 5021,
                "id_token": "refreshed_token",
            }

        def acquire_token_interactive(self, scopes):
            raise ValueError("This should not be called")

    return MockApp()

@pytest.fixture
def aws_stubber(mocker: MockerFixture):
    dummy_creds = {
        "Credentials": {
            "AccessKeyId": "12345678910111213141516",
            "SecretAccessKey": "",
            "SessionToken": "",
            "Expiration": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=1),
        }
    }
    client = boto3.client("sts")
    stubber = Stubber(client)
    stubber.add_response(
        "assume_role_with_web_identity",
        dummy_creds,
    )
    mocker.patch("boto3.client", return_value=client)
    return stubber


@pytest.fixture
def expired_auth_credentials_mock():
    return {
        "id_token": "expired_token",
        "expiration": datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=1),
        "refresh_token": "refresh",
    }


@pytest.fixture
def unexpired_auth_credentials_mock():
    return {
        "id_token": "cached_token",
        "expiration": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
        "refresh_token": "refresh"
    }


def test_prescient_client_initialization(set_env_vars):
    """Test that the client is initialized correctly"""
    client = PrescientClient()
    assert client.settings.prescient_endpoint_url is not None


def test_env_file_init(clear_prescient_env, tmp_path):
    """Test that the env file is loaded correctly"""

    env_file = tmp_path / "config.env"
    env_file.write_text(
        "PRESCIENT_ENDPOINT_URL=https://some-test\n"
        "PRESCIENT_AWS_REGION=some-aws-region\n"
        "PRESCIENT_AWS_ROLE=arn:aws:iam::something\n"
        "PRESCIENT_TENANT_ID=some-tenant-id\n"
        "PRESCIENT_CLIENT_ID=some-client-id\n"
        "PRESCIENT_AUTH_URL=https://login.somewhere.com/\n"
        "PRESCIENT_AUTH_TOKEN_PATH=/oauth2/v2.0/token\n"
        "PRESCIENT_UPLOAD_ROLE=arn:aws:iam::abc/def\n"
        "PRESCIENT_UPLOAD_BUCKET=bucket"
    )

    client = PrescientClient(env_file=str(env_file))
    assert client.settings.prescient_endpoint_url == "https://some-test"


def test_fail_when_passing_both_env_file_and_settings(set_env_vars):
    """Test that an error is raised when both env file and settings are passed"""
    with pytest.raises(ValueError):
        PrescientClient(env_file="some-file.env", settings=Settings())  # type: ignore


def test_settings_loaded_explicitly():
    """Test that settings are loaded correctly"""
    settings = Settings(
        prescient_endpoint_url="https://example.server.prescient.earth",
        prescient_aws_region="some-aws-region",
        prescient_aws_role="arn:aws:iam::something",
        prescient_tenant_id="some-tenant-id",
        prescient_client_id="some-client-id",
        prescient_auth_url="https://login.somewhere.com/",
        prescient_auth_token_path="/oauth2/v2.0/token",
        prescient_upload_bucket="test-bucket",
        prescient_upload_role="arn:aws:iam::upload-role",
    )
    client = PrescientClient(settings=settings)
    assert client.settings.prescient_endpoint_url is not None


def test_prescient_client_custom_url(set_env_vars):
    """Test that the stac url is returned correctly"""
    custom_url = "https://custom.url/"
    settings = Settings(prescient_endpoint_url=custom_url)  # type: ignore
    client = PrescientClient(settings=settings)
    assert client.settings.prescient_endpoint_url == custom_url
    assert client.stac_catalog_url == custom_url + "stac"


def test_custom_url_formatting(set_env_vars):
    """Test that the custom url is formatted correctly"""
    custom_url = "https://custom.url"
    settings = Settings(prescient_endpoint_url=custom_url)  # type: ignore
    client = PrescientClient(settings=settings)
    assert client.stac_catalog_url == custom_url + "/stac"


def test_prescient_client_headers(monkeypatch: pytest.MonkeyPatch, set_env_vars):
    """Test that the headers are set correctly"""
    # Mock the auth_credentials property
    monkeypatch.setattr(
        PrescientClient,
        "auth_credentials",
        {"id_token": "mock_token"},
        raising=True,
    )

    client = PrescientClient()

    headers = client.headers
    assert headers["Authorization"] == "Bearer mock_token"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_credentials_expired(
    set_env_vars, expired_auth_credentials_mock, unexpired_auth_credentials_mock
):
    """Test the credentials_expired property"""
    client_expired = PrescientClient()
    client_expired._auth_credentials = expired_auth_credentials_mock
    assert client_expired.credentials_expired

    client_unexpired = PrescientClient()
    client_unexpired._auth_credentials = unexpired_auth_credentials_mock
    assert not client_unexpired.credentials_expired


def test_prescient_client_cached_auth_credentials(
    set_env_vars, unexpired_auth_credentials_mock
):
    """test that cached credentials are used"""
    client = PrescientClient()
    client._auth_credentials = unexpired_auth_credentials_mock

    headers = client.headers
    assert headers["Authorization"] == "Bearer cached_token"


def test_prescient_client_cached_aws_credentials(
    mocker: MockerFixture, set_env_vars, unexpired_auth_credentials_mock
):
    """test that cached aws credentials are used"""
    # ensure that the boto3 client is not called because it should use cached credentials
    Stubber(mocker.patch("boto3.client")).add_client_error(
        method="assume_role_with_web_identity"
    )

    client = PrescientClient()
    client._auth_credentials = unexpired_auth_credentials_mock
    client._bucket_credentials = {
        "AccessKeyId": "cached_id",
        "Expiration": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    }

    aws_credentials = client.bucket_credentials
    assert aws_credentials["AccessKeyId"] == "cached_id"


def test_prescient_client_succesful_aws_credentials(
    mocker: MockerFixture, mock_creds: MockType, set_env_vars
):
    """Test that aws_credentials are passed through correctly"""
    dummy_creds = {
        "Credentials": {
            "AccessKeyId": "12345678910111213141516",
            "SecretAccessKey": "",
            "SessionToken": "",
            "Expiration": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=1),
        }
    }

    client = boto3.client("sts")
    stubber = Stubber(client)
    stubber.add_response(
        "assume_role_with_web_identity",
        dummy_creds,
    )
    mocker.patch("boto3.client", return_value=client)

    with stubber:
        client = PrescientClient()

        assert client.bucket_credentials == dummy_creds["Credentials"]


def test_creds_refreshed(
    mocker: MockerFixture, set_env_vars, auth_client_mock, expired_auth_credentials_mock
):
    """Test that auth credentials are refreshed when expired"""

    mocker.patch(
        "msal.PublicClientApplication",
        return_value=auth_client_mock,
    )

    client = PrescientClient()

    # initialize creds as expired
    client._auth_credentials = expired_auth_credentials_mock

    # check that when the auth_creds are used they get refreshed from the mock fixture
    assert client.auth_credentials["id_token"] == "refreshed_token"
    assert client.auth_credentials["expiration"] > datetime.datetime.now(
        datetime.timezone.utc
    )


def test_refresh_creds_func_unexpired(
    mocker: MockerFixture,
    set_env_vars,
    auth_client_mock,
    unexpired_auth_credentials_mock,
    aws_stubber,
):
    """Test that refresh_credentials() is a no-op when credentials are unexpired"""

    # mocker.patch("boto3.client", return_value=client)
    mocker.patch(
        "msal.PublicClientApplication",
        return_value=auth_client_mock,
    )

    client = PrescientClient()

    client._auth_credentials = unexpired_auth_credentials_mock

    # check that when the auth_creds are used they get refreshed from the mock fixture
    assert client.auth_credentials["id_token"] == "cached_token"

    assert not client.credentials_expired

    with aws_stubber:
        client.refresh_credentials()

    assert client.auth_credentials["id_token"] == "cached_token"
    assert not client.credentials_expired


def test_refresh_creds_func_expired(
    mocker: MockerFixture,
    set_env_vars,
    auth_client_mock,
    expired_auth_credentials_mock,
    aws_stubber,
):
    """Test that auth credentials are refreshed when expired"""

    # mocker.patch("boto3.client", return_value=client)
    mocker.patch(
        "msal.PublicClientApplication",
        return_value=auth_client_mock,
    )

    client = PrescientClient()

    client._auth_credentials = expired_auth_credentials_mock

    assert client.credentials_expired

    with aws_stubber:
        client.refresh_credentials()

    assert not client.credentials_expired

    assert client.auth_credentials["id_token"] == "refreshed_token"


def test_force_creds_refreshed(
    mocker: MockerFixture,
    set_env_vars,
    auth_client_mock,
    unexpired_auth_credentials_mock,
    aws_stubber,
):
    """Test that refresh_credentials(force=True) refreshes even when credentials are unexpired"""

    # mocker.patch("boto3.client", return_value=client)
    mocker.patch(
        "msal.PublicClientApplication",
        return_value=auth_client_mock,
    )

    client = PrescientClient()

    client._auth_credentials = unexpired_auth_credentials_mock

    # check that when the auth_creds are used they get refreshed from the mock fixture
    assert client.auth_credentials["id_token"] == "cached_token"

    assert not client.credentials_expired

    with aws_stubber:
        client.refresh_credentials(force=True)

    assert not client.credentials_expired

    assert client.auth_credentials["id_token"] == "refreshed_token"


def test_aws_creds_refresh(
    mocker: MockerFixture,
    auth_client_mock,
    set_env_vars,
    expired_auth_credentials_mock,
    aws_stubber,
):
    """Test that aws credentials are refreshed when expired"""
    # mock the assume_role_with_web_identity response with a not expired token

    # mocker.patch("boto3.client", return_value=client)
    mocker.patch(
        "msal.PublicClientApplication",
        return_value=auth_client_mock,
    )

    with aws_stubber:
        # initialize the client with expired creds
        client = PrescientClient()
        client._auth_credentials = expired_auth_credentials_mock

        # check that when the aws_creds are used they get refreshed from the dummy response
        assert client.bucket_credentials["AccessKeyId"] == "12345678910111213141516"
        assert client.bucket_credentials["Expiration"] > datetime.datetime.now(
            datetime.timezone.utc
        )


# ---------------------------------------------------------------------------
# Google auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def set_env_vars_google(monkeypatch: pytest.MonkeyPatch, clear_prescient_env):
    """Fixture to set config env vars for Google auth provider."""
    monkeypatch.setenv("PRESCIENT_ENDPOINT_URL", "https://example.server.prescient.earth")
    monkeypatch.setenv("PRESCIENT_AWS_REGION", "some-aws-region")
    monkeypatch.setenv("PRESCIENT_AWS_ROLE", "arn:aws:iam::something")
    monkeypatch.setenv("PRESCIENT_AUTH_PROVIDER", "google")
    monkeypatch.setenv("PRESCIENT_CLIENT_ID", "some-google-client-id")
    monkeypatch.setenv("PRESCIENT_AUTH_URL", "https://accounts.google.com")
    monkeypatch.setenv("PRESCIENT_AUTH_TOKEN_PATH", "/o/oauth2/token")
    monkeypatch.setenv("PRESCIENT_GOOGLE_CLIENT_SECRET", "some-google-client-secret")
    monkeypatch.setenv("PRESCIENT_GOOGLE_REDIRECT_PORT", "9876")


def _make_google_credentials_mock(id_token: str, refresh_token: str = "google_refresh"):
    """Build a mock object shaped like google.oauth2.credentials.Credentials."""
    mock = MagicMock()
    mock.id_token = id_token
    mock.refresh_token = refresh_token
    mock.token = "google_access_token"
    return mock


@pytest.fixture
def google_flow_mock(mocker: MockerFixture):
    """Mock InstalledAppFlow so run_local_server returns a fake Credentials object."""
    creds = _make_google_credentials_mock("interactive_google_token")
    mock_flow = MagicMock()
    mock_flow.run_local_server.return_value = creds
    mocker.patch(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        return_value=mock_flow,
    )
    return mock_flow


@pytest.fixture
def google_refresh_mock(mocker: MockerFixture):
    """Mock google.oauth2.credentials.Credentials so .refresh() populates id_token."""
    creds = _make_google_credentials_mock("refreshed_google_token")
    mocker.patch(
        "google.oauth2.credentials.Credentials",
        return_value=creds,
    )
    mocker.patch("google.auth.transport.requests.Request", return_value=MagicMock())
    return creds


@pytest.fixture
def expired_google_credentials_mock():
    return {
        "id_token": "expired_google_token",
        "expiration": datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=1),
        "refresh_token": "google_refresh",
        "access_token": "google_access",
    }


@pytest.fixture
def unexpired_google_credentials_mock():
    return {
        "id_token": "cached_google_token",
        "expiration": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
        "refresh_token": "google_refresh",
        "access_token": "google_access",
    }


# ---------------------------------------------------------------------------
# Google auth tests
# ---------------------------------------------------------------------------


def test_google_config_initialization(set_env_vars_google):
    """Test that a Google-provider client initializes correctly from env vars."""
    client = PrescientClient()
    assert client.settings.prescient_auth_provider == "google"
    assert client.settings.prescient_google_client_secret == "some-google-client-secret"


def test_config_validator_microsoft_missing_tenant(clear_prescient_env):
    """Settings should raise when provider is microsoft but tenant_id is absent."""
    with pytest.raises(ValueError, match="prescient_tenant_id"):
        Settings(
            prescient_endpoint_url="https://example.com",
            prescient_aws_region="us-west-2",
            prescient_aws_role="arn:aws:iam::something",
            prescient_auth_provider="microsoft",
            prescient_client_id="some-client",
            prescient_auth_url="https://login.microsoft.com",
            prescient_auth_token_path="/oauth2/v2.0/token",
            # prescient_tenant_id intentionally omitted
        )


def test_config_validator_google_missing_secret(clear_prescient_env):
    """Settings should raise when provider is google but client_secret is absent."""
    with pytest.raises(ValueError, match="prescient_google_client_secret"):
        Settings(
            prescient_endpoint_url="https://example.com",
            prescient_aws_region="us-west-2",
            prescient_aws_role="arn:aws:iam::something",
            prescient_auth_provider="google",
            prescient_client_id="some-client",
            prescient_auth_url="https://accounts.google.com",
            prescient_auth_token_path="/o/oauth2/token",
            # prescient_google_client_secret intentionally omitted
        )


def test_google_creds_interactive(set_env_vars_google, google_flow_mock):
    """First-login path: InstalledAppFlow.run_local_server is called and id_token stored."""
    client = PrescientClient()
    # No prior credentials — should trigger interactive flow
    creds = client.auth_credentials
    assert creds["id_token"] == "interactive_google_token"
    google_flow_mock.run_local_server.assert_called_once_with(port=9876)


def test_google_creds_refreshed(
    set_env_vars_google,
    google_refresh_mock,
    expired_google_credentials_mock,
):
    """Expired Google creds should trigger a silent refresh via Credentials.refresh()."""
    client = PrescientClient()
    client._auth_credentials = expired_google_credentials_mock

    creds = client.auth_credentials
    assert creds["id_token"] == "refreshed_google_token"
    google_refresh_mock.refresh.assert_called_once()


def test_google_cached_credentials(set_env_vars_google, unexpired_google_credentials_mock):
    """Unexpired Google creds should be returned from cache without any provider call."""
    client = PrescientClient()
    client._auth_credentials = unexpired_google_credentials_mock

    creds = client.auth_credentials
    assert creds["id_token"] == "cached_google_token"


def test_google_headers(set_env_vars_google, unexpired_google_credentials_mock):
    """Headers should use the Google id_token as the Bearer token."""
    client = PrescientClient()
    client._auth_credentials = unexpired_google_credentials_mock

    assert client.headers["Authorization"] == "Bearer cached_google_token"


def test_google_aws_creds_refresh(
    mocker: MockerFixture,
    set_env_vars_google,
    google_refresh_mock,
    expired_google_credentials_mock,
    aws_stubber,
):
    """End-to-end: expired Google auth → refresh → new STS credentials."""
    with aws_stubber:
        client = PrescientClient()
        client._auth_credentials = expired_google_credentials_mock

        bucket_creds = client.bucket_credentials
        assert bucket_creds["AccessKeyId"] == "12345678910111213141516"
        assert bucket_creds["Expiration"] > datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Fileproxy credentials (no aws_role) tests
# ---------------------------------------------------------------------------


@pytest.fixture
def set_env_vars_no_role(monkeypatch: pytest.MonkeyPatch, clear_prescient_env):
    """Same as set_env_vars but without PRESCIENT_AWS_ROLE or PRESCIENT_AWS_REGION."""
    monkeypatch.setenv("PRESCIENT_ENDPOINT_URL", "https://example.server.prescient.earth/")
    monkeypatch.setenv("PRESCIENT_TENANT_ID", "some-tenant-id")
    monkeypatch.setenv("PRESCIENT_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("PRESCIENT_AUTH_URL", "https://login.somewhere.com/")
    monkeypatch.setenv("PRESCIENT_AUTH_TOKEN_PATH", "/oauth2/v2.0/token")


def test_aws_role_and_region_optional(set_env_vars_no_role):
    """Client should initialize without PRESCIENT_AWS_ROLE or PRESCIENT_AWS_REGION set."""
    client = PrescientClient()
    assert client.settings.prescient_aws_role is None
    assert client.settings.prescient_aws_region is None


def test_fileproxy_credentials_fetch(
    mocker: MockerFixture, set_env_vars_no_role, unexpired_auth_credentials_mock
):
    """When aws_role is unset, bucket_credentials hits /fileproxy/credentials."""
    expiration_iso = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    ).isoformat()
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "access_key_id": "proxy_key",
        "secret_access_key": "proxy_secret",
        "session_token": "proxy_session",
        "expiration": expiration_iso,
    }
    fake_response.raise_for_status = MagicMock()
    get_mock = mocker.patch("prescient_sdk.client.requests.get", return_value=fake_response)
    boto_mock = mocker.patch("boto3.client")

    client = PrescientClient()
    client._auth_credentials = unexpired_auth_credentials_mock

    creds = client.bucket_credentials
    assert creds["AccessKeyId"] == "proxy_key"
    assert creds["SecretAccessKey"] == "proxy_secret"
    assert creds["SessionToken"] == "proxy_session"
    assert creds["Expiration"] > datetime.datetime.now(datetime.timezone.utc)
    assert creds["Expiration"].tzinfo is datetime.timezone.utc

    # STS should never be called when fetching from fileproxy
    boto_mock.assert_not_called()

    # GET called against the fileproxy endpoint with the bearer token
    get_mock.assert_called_once()
    called_url, called_kwargs = get_mock.call_args[0][0], get_mock.call_args.kwargs
    assert called_url == "https://example.server.prescient.earth/fileproxy/credentials"
    assert called_kwargs["headers"]["Authorization"] == "Bearer cached_token"


def test_fileproxy_credentials_cached(
    mocker: MockerFixture, set_env_vars_no_role, unexpired_auth_credentials_mock
):
    """Cached bucket creds short-circuit the HTTP call."""
    get_mock = mocker.patch("prescient_sdk.client.requests.get")

    client = PrescientClient()
    client._auth_credentials = unexpired_auth_credentials_mock
    client._bucket_credentials = {
        "AccessKeyId": "cached_proxy_key",
        "Expiration": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    }

    assert client.bucket_credentials["AccessKeyId"] == "cached_proxy_key"
    get_mock.assert_not_called()
