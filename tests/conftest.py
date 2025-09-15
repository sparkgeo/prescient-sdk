import os
import datetime
import pytest
from pytest_mock import MockerFixture
import boto3
from botocore.stub import Stubber
from moto import mock_aws


@pytest.fixture
def set_env_vars():
    """fixture to set the config settings as env variables"""
    os.environ["PRESCIENT_ENDPOINT_URL"] = "https://example.server.prescient.earth"
    os.environ["PRESCIENT_AWS_REGION"] = "some-aws-region"
    os.environ["PRESCIENT_AWS_ROLE"] = "arn:aws:iam::something"
    os.environ["PRESCIENT_TENANT_ID"] = "some-tenant-id"
    os.environ["PRESCIENT_CLIENT_ID"] = "some-client-id"
    os.environ["PRESCIENT_AUTH_URL"] = "https://login.somewhere.com/"
    os.environ["PRESCIENT_AUTH_TOKEN_PATH"] = "/oauth2/v2.0/token"
    os.environ["PRESCIENT_UPLOAD_ROLE"] = "arn:aws:iam::test-upload"
    os.environ["PRESCIENT_UPLOAD_BUCKET"] = "test-bucket"

    yield

    del os.environ["PRESCIENT_ENDPOINT_URL"]
    del os.environ["PRESCIENT_AWS_REGION"]
    del os.environ["PRESCIENT_AWS_ROLE"]
    del os.environ["PRESCIENT_TENANT_ID"]
    del os.environ["PRESCIENT_CLIENT_ID"]
    del os.environ["PRESCIENT_AUTH_URL"]
    del os.environ["PRESCIENT_AUTH_TOKEN_PATH"]
    del os.environ["PRESCIENT_UPLOAD_ROLE"]
    del os.environ["PRESCIENT_UPLOAD_BUCKET"]


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
        "refresh_token": "refresh",
    }


@pytest.fixture
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def s3(aws_credentials):
    """
    Return a mocked S3 client
    """
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")
