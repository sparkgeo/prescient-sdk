import time
from pathlib import Path, PurePosixPath, PureWindowsPath

import boto3
import pytest
from moto import mock_aws

from prescient_sdk.client import PrescientClient
from prescient_sdk.upload import (
    _make_s3_key,
    _relative_posix,
    _split_s3_uri,
    iter_files,
    upload,
    upload_source_files,
)


def _make_tree(root: Path, rel_paths: list[str]) -> None:
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


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

    expected = f"{root.name}/a/b.txt"
    assert _make_s3_key(file, root) == expected


def test_make_s3_key_posix_relative(tmp_path):
    root = tmp_path
    file = tmp_path / "c.txt"
    file.touch()

    expected = f"{root.name}/c.txt"
    assert _make_s3_key(file, root) == expected


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


@pytest.mark.parametrize(
    "uri, expected",
    [
        ("s3://bucket/a/b/", ("bucket", "a/b/")),
        ("s3://bucket/a/b", ("bucket", "a/b/")),
        ("s3://bucket/", ("bucket", "")),
        ("s3://bucket", ("bucket", "")),
    ],
)
def test_split_s3_uri(uri, expected):
    assert _split_s3_uri(uri) == expected


@pytest.mark.parametrize("uri", ["http://bucket/x", "bucket/x", "s3://", "s3:///key"])
def test_split_s3_uri_invalid(uri):
    with pytest.raises(ValueError):
        _split_s3_uri(uri)


def test_upload_source_files_filters_and_preserves_relative_paths(
    tmp_path, s3, create_test_bucket
):
    _make_tree(tmp_path, ["a.tif", "sub/b.tif", "note.txt"])
    calls = []

    upload_source_files(
        tmp_path,
        "s3://test-bucket/user-uploads/uid/",
        r".*\.tif$",
        boto3.Session(),
        on_file=lambda index, total, path: calls.append((index, total, path)),
    )

    keys = sorted(
        o["Key"] for o in s3.list_objects_v2(Bucket="test-bucket")["Contents"]
    )
    # only .tif files, keyed as dest_prefix + relative path (no dir-name segment)
    assert keys == ["user-uploads/uid/a.tif", "user-uploads/uid/sub/b.tif"]
    assert all(tmp_path.name not in key for key in keys)
    # on_file fired once per uploaded file with a 1-based index and the total
    assert [(index, total) for index, total, _ in calls] == [(1, 2), (2, 2)]
    assert {path for _, _, path in calls} == {
        tmp_path / "a.tif",
        tmp_path / "sub" / "b.tif",
    }


def test_upload_source_files_uses_anchored_match(tmp_path, s3, create_test_bucket):
    # re.match anchors at the start: "scene.tif" matches at the root but not
    # under a subdirectory, so only the root file is selected.
    _make_tree(tmp_path, ["scene.tif", "sub/scene.tif"])

    upload_source_files(
        tmp_path, "s3://test-bucket/p/", r"scene\.tif$", boto3.Session()
    )

    keys = sorted(
        o["Key"] for o in s3.list_objects_v2(Bucket="test-bucket")["Contents"]
    )
    assert keys == ["p/scene.tif"]


def test_upload_source_files_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        upload_source_files(
            tmp_path / "nope", "s3://test-bucket/p/", ".*", boto3.Session()
        )


def test_relative_posix_windows_style():
    root = PureWindowsPath(r"C:\data\scenes")
    file = PureWindowsPath(r"C:\data\scenes\nested\image.tif")
    assert _relative_posix(file, root) == "nested/image.tif"


def test_relative_posix_posix_style():
    root = PurePosixPath("/data/scenes")
    file = PurePosixPath("/data/scenes/nested/image.tif")
    assert _relative_posix(file, root) == "nested/image.tif"


def test_staged_key_from_windows_path_uses_forward_slashes():
    # The staged S3 key is key_prefix + relative posix path; a Windows source
    # tree must still produce forward-slash keys (S3 keys never use backslashes).
    root = PureWindowsPath(r"C:\data\scenes")
    file = PureWindowsPath(r"C:\data\scenes\a\b\image.tif")

    key = "user-uploads/uid/" + _relative_posix(file, root)

    assert key == "user-uploads/uid/a/b/image.tif"
    assert "\\" not in key


def test_upload_source_files_windows_pattern_matches_relative_posix(
    tmp_path, s3, create_test_bucket
):
    # A pattern written with a forward-slash subdirectory (as authored in a spec)
    # must match nested files regardless of the local OS separator, because
    # matching runs on the posix relative path.
    _make_tree(tmp_path, ["a/scene.tif", "b/scene.tif", "a/note.txt"])

    upload_source_files(tmp_path, "s3://test-bucket/p/", r"a/.*\.tif$", boto3.Session())

    keys = sorted(
        o["Key"] for o in s3.list_objects_v2(Bucket="test-bucket")["Contents"]
    )
    assert keys == ["p/a/scene.tif"]
