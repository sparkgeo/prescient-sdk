from prescient_sdk.client import PrescientClient
from prescient_sdk.upload import iter_files, upload, _make_s3_key
from moto import mock_aws
from pathlib import Path, PureWindowsPath
import time
import pytest


@pytest.fixture
def create_test_bucket(s3):
    s3.create_bucket(Bucket="test-bucket")


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


@mock_aws
def test_upload(
    tmp_path,
    set_env_vars,
    mock_creds,
    unexpired_auth_credentials_mock,
    create_test_bucket,
    aws_credentials,
    s3,
    caplog,
):
    client = PrescientClient()
    client._auth_credentials = unexpired_auth_credentials_mock
    client.settings.prescient_aws_region = "us-east-1"
    test_path = tmp_path.joinpath("test.txt")
    test_path.touch()

    upload(tmp_path.as_posix(), prescient_client=client)

    results = s3.list_objects_v2(Bucket="test-bucket")

    assert "Contents" in results
    assert len(results["Contents"]) == 1
    assert results["Contents"][0]["Key"].endswith("test.txt")
    assert test_path.parent.name in results["Contents"][0]["Key"]
    for record in caplog.records:
        assert "uploading file" in record.message
    caplog.clear()

    # overwrite
    last_modified = results["Contents"][0]["LastModified"]
    time.sleep(1)  # LastModified does not have millisecond precision

    upload(tmp_path.as_posix(), prescient_client=client, overwrite=True)

    results = s3.list_objects_v2(Bucket="test-bucket")
    assert last_modified < results["Contents"][0]["LastModified"]
    for record in caplog.records:
        assert "uploading file" in record.message
    caplog.clear()

    # do not overwrite
    last_modified = results["Contents"][0]["LastModified"]
    etag = results["Contents"][0]["ETag"]
    time.sleep(1)

    upload(tmp_path.as_posix(), prescient_client=client, overwrite=False)

    results = s3.list_objects_v2(Bucket="test-bucket")
    assert last_modified == results["Contents"][0]["LastModified"]
    assert etag == results["Contents"][0]["ETag"]
    for record in caplog.records:
        assert "skipping file" in record.message
    caplog.clear()


def test_make_s3_key_posix_absolute(tmp_path):
    root = tmp_path
    file = tmp_path / "a" / "b.txt"
    file.parent.mkdir()
    file.touch()

    assert _make_s3_key(file, root) == "a/b.txt"


def test_make_s3_key_posix_relative(tmp_path):
    root = tmp_path
    file = tmp_path / "c.txt"
    file.touch()

    # root and file are the same tmp_path base
    assert _make_s3_key(file, root) == "c.txt"


def test_make_s3_key_windows_style():
    root = PureWindowsPath(r"C:\data\project")
    file = PureWindowsPath(r"C:\data\project\nested\file.txt")

    assert file.relative_to(root).as_posix() == "nested/file.txt"

def test_make_s3_key_relative_root(tmp_path):
    root = Path("../data")
    file = root / "a.txt"

    assert _make_s3_key(file, root) == "data/a.txt"

def test_upload_invalid_dir(tmp_path):
    tmp_dir = tmp_path.joinpath("some-dir")
    with pytest.raises(FileNotFoundError):
        upload(str(tmp_dir))
