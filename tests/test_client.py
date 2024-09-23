import datetime
import os

import pytest
from pytest_mock import MockerFixture, MockType
import boto3
from botocore.stub import Stubber

from prescient_sdk.client import PrescientClient
from prescient_sdk.config import Settings

@pytest.fixture(autouse=True)
def set_env_vars():
    """fixture to set the config settings as env variables"""
    os.environ["ENDPOINT_URL"] = "https://example.server.prescient.earth"
    os.environ["AWS_REGION"] = "some-aws-region"
    os.environ["AWS_ROLE"] = "arn:aws:iam::something"
    os.environ["TENANT_ID"] = "some-tenant-id"
    os.environ["CLIENT_ID"] = "some-client-id"
    os.environ["AUTH_URL"] = "https://login.somewhere.com/"
    os.environ["AUTH_TOKEN_PATH"] = "/oauth2/v2.0/token"

    yield

    del os.environ["ENDPOINT_URL"]
    del os.environ["AWS_REGION"]
    del os.environ["AWS_ROLE"]
    del os.environ["TENANT_ID"]
    del os.environ["CLIENT_ID"]
    del os.environ["AUTH_URL"]
    del os.environ["AUTH_TOKEN_PATH"]


@pytest.fixture
def mock_creds(mocker: MockerFixture):
    """fixture to mock the auth credentials property"""
    mock = mocker.patch(
        "prescient_sdk.client.PrescientClient.auth_credentials",
        new_callable=mocker.PropertyMock,
        return_value={"id_token": "mock_token"},
    )
    return mock


def test_prescient_client_initialization():
    """Test that the client is initialized correctly"""
    client = PrescientClient()
    assert client.settings.endpoint_url is not None


def test_prescient_client_custom_url():
    """Test that the stac url is returned correctly"""
    custom_url = "https://custom.url/"
    settings = Settings(endpoint_url=custom_url)  # type: ignore
    client = PrescientClient(settings=settings)
    assert client.settings.endpoint_url == custom_url
    assert client.stac_catalog_url == custom_url + "stac"

def test_custom_url_formatting():
    """Test that the custom url is formatted correctly"""
    custom_url = "https://custom.url"
    settings = Settings(endpoint_url=custom_url)  # type: ignore
    client = PrescientClient(settings=settings)
    assert client.stac_catalog_url == custom_url + "/stac"


def test_prescient_client_headers(monkeypatch: pytest.MonkeyPatch):
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


def test_prescient_client_cached_auth_credentials():
    """test that cached credentials are used"""
    client = PrescientClient()
    client._auth_credentials = {
        "id_token": "cached_token",
        "expiration": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    }

    headers = client.headers
    assert headers["Authorization"] == "Bearer cached_token"


def test_prescient_client_cached_aws_credentials(mocker: MockerFixture):
    """test that cached aws credentials are used"""
    # ensure that the boto3 client is not called because it should use cached credentials
    Stubber(mocker.patch("boto3.client")).add_client_error(
        method="assume_role_with_web_identity"
    )

    client = PrescientClient()
    client._bucket_credentials = {
        "AccessKeyId": "cached_id",
        "Expiration": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    }

    aws_credentials = client.bucket_credentials
    assert aws_credentials["AccessKeyId"] == "cached_id"

def test_prescient_client_succesful_aws_credentials(
    mocker: MockerFixture, mock_creds: MockType
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


def test_creds_refreshed(mocker: MockerFixture):
    """Test that auth credentials are refreshed when expired"""

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

    mocker.patch(
        "msal.PublicClientApplication",
        return_value=MockApp(),
    )

    client = PrescientClient()

    # initialize creds as expired
    client._auth_credentials = {
        "id_token": "expired_token",
        "expiration": datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=1),
        "refresh_token": "refresh",
    }

    # check that when the auth_creds are used they get refreshed from the mock fixture
    assert client.auth_credentials["id_token"] == "refreshed_token"
    assert client.auth_credentials["expiration"] > datetime.datetime.now(
        datetime.timezone.utc
    )


def test_aws_creds_refresh(mocker: MockerFixture, mock_creds: MockType):
    """Test that aws credentials are refreshed when expired"""
    # mock the assume_role_with_web_identity response with a not expired token
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
        # initialize the client with expired AWS creds
        client = PrescientClient()
        client._bucket_credentials = {
            "AccessKeyId": "expired_id",
            "Expiration": datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1),
        }

        # check that when the aws_creds are used they get refreshed from the dummy response
        assert client.bucket_credentials["AccessKeyId"] == "12345678910111213141516"
        assert client.bucket_credentials["Expiration"] > datetime.datetime.now(
            datetime.timezone.utc
        )