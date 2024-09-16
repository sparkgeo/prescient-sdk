import datetime

import pytest
import boto3
from botocore.stub import Stubber

from prescient_sdk.client import PrescientClient


def test_prescient_client_initialization():
    client = PrescientClient()
    assert client._endpoint_url is not None


def test_prescient_client_custom_url():
    custom_url = "https://custom.url/"
    client = PrescientClient(endpoint_url=custom_url)
    assert client._endpoint_url == custom_url


def test_prescient_client_headers(monkeypatch):
    # Mock the azure_credentials property
    monkeypatch.setattr(
        PrescientClient,
        "azure_credentials",
        {"access_token": "mock_token"},
        raising=True,
    )

    client = PrescientClient()

    headers = client.headers
    assert headers["Authorization"] == "Bearer mock_token"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"


def test_prescient_client_cached_azure_credentials():
    client = PrescientClient()
    client._azure_credentials = {
        "access_token": "cached_token",
        "expiration": datetime.datetime.now() + datetime.timedelta(hours=1),
    }

    headers = client.headers
    assert headers["Authorization"] == "Bearer cached_token"


def test_prescient_client_cached_aws_credentials(mocker):
    # Stubber(mocker.patch("boto3.client")).add_response(
    #     "assume_role_with_web_identity",
    #     {
    #         "Credentials": {
    #             "AccessKeyId": "mock_access_key",
    #             "SecretAccessKey": "mock_secret_key",
    #             "SessionToken": "mock_session_token",
    #             "Expiration": datetime.datetime.now() + datetime.timedelta(hours=1),
    #         }
    #     },
    # )

    # ensure that the boto3 client is not called
    Stubber(mocker.patch("boto3.client")).add_client_error(
        method="assume_role_with_web_identity"
    )

    client = PrescientClient()
    client._aws_credentials = {
        "AccessKeyId": "cached_id",
        "Expiration": datetime.datetime.now() + datetime.timedelta(hours=1),
    }

    aws_credentials = client.aws_credentials
    assert aws_credentials["AccessKeyId"] == "cached_id"


def test_prescient_client_raises_on_empty_aws_credentials(mocker):
    Stubber(boto3.client("sts")).add_response(
        "assume_role_with_web_identity",
        {
            "Credentials": {
                "AccessKeyId": "12345678910111213141516",
                "SecretAccessKey": "",
                "SessionToken": "",
                "Expiration": datetime.datetime.now() + datetime.timedelta(hours=1),
            }
        },
    )

    client = PrescientClient()

    with pytest.raises(ValueError):
        client.aws_credentials
