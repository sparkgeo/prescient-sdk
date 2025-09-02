from pathlib import Path
import datetime
import boto3
from botocore.stub import Stubber, ANY
from pytest_mock import MockerFixture
from test_client import (
    auth_client_mock,
    aws_stubber,
    set_env_vars,
    unexpired_auth_credentials_mock,
    mock_creds
)

from prescient_sdk.client import PrescientClient
from prescient_sdk.upload import iter_files, upload


def test_iter_files(tmp_path):
    expected_files = ["a.txt", "b.txt", "directory/c.txt"]

    files = ["a.txt", "b.txt", "directory", "directory/c.txt"]
    for f in files:
        p = tmp_path.joinpath(f)
        if not p.suffix:
            p.mkdir()
            continue
        p.touch()

    # no exclude
    result = list(iter_files(tmp_path))

    assert set([tmp_path.joinpath(f) for f in expected_files]) == set(result)

    # exclude all
    result = list(iter_files(tmp_path, exclude=["*"]))

    assert len(result) == 0

    # exclude single file
    result = list(iter_files(tmp_path, exclude=["a.txt"]))
    assert Path(tmp_path.joinpath("a.txt")) not in result
    assert len(result) == 2

    # exclude subdirectory
    result = list(iter_files(tmp_path, exclude=["directory/*"]))
    assert Path(tmp_path.joinpath("directory/c.txt")) not in result
    assert len(result) == 2


def test_upload(tmp_path, mocker: MockerFixture, mock_creds, unexpired_auth_credentials_mock):
    
    
    client = PrescientClient()
    client.upload_session
    client.settings.prescient_upload_bucket = "test-bucket"

    test_path = tmp_path.joinpath("test.txt")
    test_path.touch()
    with test_path.open(mode="rb") as f:
        data = f.read()

    upload(
        tmp_path.as_posix(),
        prescient_client=client
    )

    assert 0
