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
    os.environ["PRESCIENT_ENDPOINT_URL"] = "https://example.server.prescient.earth"
    os.environ["PRESCIENT_AWS_REGION"] = "some-aws-region"
    os.environ["PRESCIENT_AWS_ROLE"] = "arn:aws:iam::something"
    os.environ["PRESCIENT_AZURE_TENANT_ID"] = "some-tenant-id"
    os.environ["PRESCIENT_AZURE_CLIENT_ID"] = "some-client-id"
    os.environ["PRESCIENT_AZURE_AUTH_URL"] = "https://login.somewhere.com/"
    os.environ["PRESCIENT_AZURE_AUTH_TOKEN_PATH"] = "/oauth2/v2.0/token"

    yield

    del os.environ["PRESCIENT_ENDPOINT_URL"]
    del os.environ["PRESCIENT_AWS_REGION"]
    del os.environ["PRESCIENT_AWS_ROLE"]
    del os.environ["PRESCIENT_AZURE_TENANT_ID"]
    del os.environ["PRESCIENT_AZURE_CLIENT_ID"]
    del os.environ["PRESCIENT_AZURE_AUTH_URL"]
    del os.environ["PRESCIENT_AZURE_AUTH_TOKEN_PATH"]


@pytest.fixture
def mock_azure_creds(mocker: MockerFixture):
    """fixture to mock the azure credentials property"""
    mock = mocker.patch(
        "prescient_sdk.client.PrescientClient.azure_credentials",
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
    # Mock the azure_credentials property
    monkeypatch.setattr(
        PrescientClient,
        "azure_credentials",
        {"id_token": "mock_token"},
        raising=True,
    )

    client = PrescientClient()

    headers = client.headers
    assert headers["Authorization"] == "Bearer mock_token"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_prescient_client_cached_azure_credentials():
    """test that cached azure credentials are used"""
    client = PrescientClient()
    client._azure_credentials = {
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
    client._aws_credentials = {
        "AccessKeyId": "cached_id",
        "Expiration": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    }

    aws_credentials = client.aws_credentials
    assert aws_credentials["AccessKeyId"] == "cached_id"

def test_prescient_client_succesful_aws_credentials(
    mocker: MockerFixture, mock_azure_creds: MockType
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

        assert client.aws_credentials == dummy_creds["Credentials"]


def test_azure_creds_refreshed(mocker: MockerFixture):
    """Test that azure credentials are refreshed when expired"""

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

    # initialize azure creds as expired
    client._azure_credentials = {
        "id_token": "expired_token",
        "expiration": datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=1),
        "refresh_token": "refresh",
    }

    # check that when the azure_creds are used they get refreshed from the mock fixture
    assert client.azure_credentials["id_token"] == "refreshed_token"
    assert client.azure_credentials["expiration"] > datetime.datetime.now(
        datetime.timezone.utc
    )


def test_aws_creds_refresh(mocker: MockerFixture, mock_azure_creds: MockType):
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
        client._aws_credentials = {
            "AccessKeyId": "expired_id",
            "Expiration": datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1),
        }

        # check that when the aws_creds are used they get refreshed from the dummy response
        assert client.aws_credentials["AccessKeyId"] == "12345678910111213141516"
        assert client.aws_credentials["Expiration"] > datetime.datetime.now(
            datetime.timezone.utc
        )