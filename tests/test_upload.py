"""Tests for upload to an Upload location.

Fileproxy requests go through the real ``client.session``; only the HTTP
adapter's ``send`` is replaced. S3 is a botocore ``Stubber`` or a mock client.
No test reaches the network.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

import botocore.session
import pytest
import requests
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber

from prescient_sdk.client import PrescientClient
from prescient_sdk.uploads import (
    _relative_posix,
    _s3_client,
    _upload_file,
    iter_files,
    upload,
)

ENDPOINT = "https://spk-sandbox.staging.prescient.earth"
BUCKET = "org-spk-sandbox"


def _make_tree(root: Path, rel_paths: list[str]) -> None:
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"data")


def _issued(location: str, n: int = 1, expires_in: timedelta = timedelta(hours=1)):
    return {
        "location": location,
        "bucket": BUCKET,
        "region": "us-west-2",
        "prefix": f"uploads/{location}/",
        "access_key_id": f"AK{n}",
        "secret_access_key": f"SK{n}",
        "session_token": f"TOKEN{n}",
        "expiration": (datetime.now(UTC) + expires_in).isoformat(),
    }


class FakeFileproxy:
    """Stands in for ``HTTPAdapter.send``: answers ``POST /fileproxy/uploads``."""

    def __init__(self):
        self.requests: list[requests.PreparedRequest] = []

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(r.body) for r in self.requests]

    def send(self, adapter, request, **kwargs) -> requests.Response:
        self.requests.append(request)
        body = json.loads(request.body)
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        issued = _issued(body.get("location", "generated"), len(self.requests))
        response._content = json.dumps(issued).encode()
        return response


@pytest.fixture
def prescient_client(mocker, set_env_vars) -> PrescientClient:
    mocker.patch(
        "prescient_sdk.client.PrescientClient._access_token", return_value="tok"
    )
    return PrescientClient()


@pytest.fixture
def fileproxy(mocker) -> FakeFileproxy:
    fake = FakeFileproxy()
    mocker.patch(
        "requests.adapters.HTTPAdapter.send", autospec=True, side_effect=fake.send
    )
    return fake


@pytest.fixture
def s3():
    """A real botocore S3 client, so request parameters are validated."""
    return botocore.session.get_session().create_client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="a",
        aws_secret_access_key="b",
    )


@pytest.fixture
def s3_mock(mocker):
    """An S3 client mock that records every PutObject, patched into upload()."""
    mock = mocker.Mock()
    mocker.patch("prescient_sdk.uploads._s3_client", return_value=mock)
    return mock


def _put_keys(s3_mock) -> list[str]:
    return sorted(c.kwargs["Key"] for c in s3_mock.put_object.call_args_list)


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


# ---------------------------------------------------------------------------
# upload()
# ---------------------------------------------------------------------------


def test_upload_asks_fileproxy_and_returns_location(
    tmp_path, prescient_client, fileproxy, s3_mock
):
    _make_tree(tmp_path, ["a.tif"])

    location = upload(prescient_client, tmp_path, "scenes/2026")

    assert location == "scenes/2026"
    request = fileproxy.requests[0]
    assert request.method == "POST"
    assert request.url == f"{ENDPOINT}/fileproxy/uploads"
    assert request.headers["Authorization"] == "Bearer tok"
    assert fileproxy.bodies == [{"overwrite": False, "location": "scenes/2026"}]


def test_upload_without_location_returns_generated_one(
    mocker, tmp_path, prescient_client, fileproxy, s3_mock
):
    _make_tree(tmp_path, ["a.tif"])
    s3_client = mocker.patch("prescient_sdk.uploads._s3_client", return_value=s3_mock)

    location = upload(prescient_client, tmp_path, overwrite=True)

    assert location == "generated"
    assert fileproxy.bodies == [{"overwrite": True}]
    # Refreshes ask for the generated location, not a new one.
    assert s3_client.call_args.args[2] == {"overwrite": True, "location": "generated"}
    assert _put_keys(s3_mock) == ["uploads/generated/a.tif"]


def test_upload_filters_and_preserves_relative_paths(
    tmp_path, prescient_client, fileproxy, s3_mock
):
    _make_tree(tmp_path, ["a.tif", "sub/b.tif", "note.txt"])
    calls = []

    upload(
        prescient_client,
        tmp_path,
        "scenes",
        pattern=r".*\.tif$",
        on_file=lambda index, total, path: calls.append((index, total, path)),
    )

    # only .tif files, at prefix + relative path (no dir-name segment)
    assert _put_keys(s3_mock) == ["uploads/scenes/a.tif", "uploads/scenes/sub/b.tif"]
    assert {c.kwargs["Bucket"] for c in s3_mock.put_object.call_args_list} == {BUCKET}
    # on_file fired once per file with a 1-based index and the total
    assert [(index, total) for index, total, _ in calls] == [(1, 2), (2, 2)]
    assert {path for _, _, path in calls} == {
        tmp_path / "a.tif",
        tmp_path / "sub" / "b.tif",
    }


def test_upload_without_pattern_uploads_every_file(
    tmp_path, prescient_client, fileproxy, s3_mock
):
    _make_tree(tmp_path, ["a.tif", "sub/note.txt"])

    upload(prescient_client, tmp_path, "scenes")

    assert _put_keys(s3_mock) == ["uploads/scenes/a.tif", "uploads/scenes/sub/note.txt"]


def test_upload_uses_anchored_match(tmp_path, prescient_client, fileproxy, s3_mock):
    # re.match anchors at the start: "scene.tif" matches at the root but not
    # under a subdirectory, so only the root file is selected.
    _make_tree(tmp_path, ["scene.tif", "sub/scene.tif"])

    upload(prescient_client, tmp_path, "p", pattern=r"scene\.tif$")

    assert _put_keys(s3_mock) == ["uploads/p/scene.tif"]


def test_upload_pattern_matches_relative_posix(
    tmp_path, prescient_client, fileproxy, s3_mock
):
    # A pattern written with a forward-slash subdirectory (as authored in a spec)
    # must match nested files regardless of the local OS separator.
    _make_tree(tmp_path, ["a/scene.tif", "b/scene.tif", "a/note.txt"])

    upload(prescient_client, tmp_path, "p", pattern=r"a/.*\.tif$")

    assert _put_keys(s3_mock) == ["uploads/p/a/scene.tif"]


def test_upload_missing_dir(tmp_path, prescient_client, fileproxy):
    with pytest.raises(FileNotFoundError):
        upload(prescient_client, tmp_path / "nope")
    assert fileproxy.requests == []


def test_upload_counts_skipped_files(
    caplog, mocker, tmp_path, prescient_client, fileproxy, s3_mock
):
    _make_tree(tmp_path, ["a.tif", "b.tif", "c.tif"])
    mocker.patch("prescient_sdk.uploads._upload_file", side_effect=[True, False, False])

    with caplog.at_level("INFO", logger="prescient_sdk.uploads"):
        upload(prescient_client, tmp_path, "scenes")

    assert "uploaded 1 and skipped 2 existing file(s)" in caplog.text


def test_upload_fileproxy_error_raises(mocker, tmp_path, prescient_client):
    _make_tree(tmp_path, ["a.tif"])
    response = requests.Response()
    response.status_code = 422
    mocker.patch.object(prescient_client.session, "post", return_value=response)

    with pytest.raises(requests.HTTPError):
        upload(prescient_client, tmp_path, "Bad Location")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_credentials_refresh_asks_fileproxy_again_with_same_body(
    prescient_client, fileproxy
):
    body = {"overwrite": False, "location": "scenes"}
    # Already inside botocore's mandatory refresh window.
    issued = _issued("scenes", n=0, expires_in=timedelta(minutes=5))

    client = _s3_client(prescient_client, issued, body)
    frozen = client._request_signer._credentials.get_frozen_credentials()

    assert fileproxy.bodies == [body]
    assert fileproxy.requests[0].headers["Authorization"] == "Bearer tok"
    assert (frozen.access_key, frozen.secret_key, frozen.token) == (
        "AK1",
        "SK1",
        "TOKEN1",
    )


def test_credentials_are_not_refreshed_before_they_expire(prescient_client, fileproxy):
    client = _s3_client(prescient_client, _issued("scenes", n=0), {"overwrite": False})
    frozen = client._request_signer._credentials.get_frozen_credentials()

    assert fileproxy.requests == []
    assert frozen.access_key == "AK0"


def test_the_s3_client_signs_for_the_bucket_region(prescient_client, fileproxy):
    client = _s3_client(prescient_client, _issued("scenes"), {"overwrite": False})

    assert client.meta.region_name == "us-west-2"


# ---------------------------------------------------------------------------
# One file
# ---------------------------------------------------------------------------


@pytest.fixture
def small_file(tmp_path) -> Path:
    path = tmp_path / "a.tif"
    path.write_bytes(b"0123456789")
    return path


def test_small_file_put_sends_if_none_match(s3, small_file):
    with Stubber(s3) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": BUCKET,
                "Key": "uploads/p/a.tif",
                "Body": ANY,
                "IfNoneMatch": "*",
            },
        )
        assert _upload_file(s3, small_file, BUCKET, "uploads/p/a.tif", False) is True
        stub.assert_no_pending_responses()


def test_small_file_put_with_overwrite_is_unconditional(s3, small_file):
    with Stubber(s3) as stub:
        stub.add_response(
            "put_object", {}, {"Bucket": BUCKET, "Key": "uploads/p/a.tif", "Body": ANY}
        )
        assert _upload_file(s3, small_file, BUCKET, "uploads/p/a.tif", True) is True
        stub.assert_no_pending_responses()


def test_existing_file_412_is_skipped(s3, small_file):
    with Stubber(s3) as stub:
        stub.add_client_error(
            "put_object", service_error_code="PreconditionFailed", http_status_code=412
        )
        assert _upload_file(s3, small_file, BUCKET, "uploads/p/a.tif", False) is False


def test_other_s3_error_raises(s3, small_file):
    with Stubber(s3) as stub:
        stub.add_client_error(
            "put_object", service_error_code="AccessDenied", http_status_code=403
        )
        with pytest.raises(ClientError):
            _upload_file(s3, small_file, BUCKET, "uploads/p/a.tif", False)


@pytest.fixture
def multipart_s3(mocker):
    mocker.patch("prescient_sdk.uploads._PART_SIZE", 4)
    s3 = mocker.Mock()
    s3.create_multipart_upload.return_value = {"UploadId": "up-1"}
    s3.upload_part.side_effect = lambda **kw: {"ETag": f"e{kw['PartNumber']}"}
    return s3


def test_large_file_multipart_sends_if_none_match_on_complete(multipart_s3, small_file):
    assert _upload_file(multipart_s3, small_file, BUCKET, "k", False) is True

    multipart_s3.put_object.assert_not_called()
    multipart_s3.create_multipart_upload.assert_called_once_with(Bucket=BUCKET, Key="k")
    parts = sorted(
        (c.kwargs["PartNumber"], c.kwargs["Body"])
        for c in multipart_s3.upload_part.call_args_list
    )
    assert parts == [(1, b"0123"), (2, b"4567"), (3, b"89")]
    multipart_s3.complete_multipart_upload.assert_called_once_with(
        Bucket=BUCKET,
        Key="k",
        UploadId="up-1",
        MultipartUpload={
            "Parts": [
                {"ETag": "e1", "PartNumber": 1},
                {"ETag": "e2", "PartNumber": 2},
                {"ETag": "e3", "PartNumber": 3},
            ]
        },
        IfNoneMatch="*",
    )
    multipart_s3.abort_multipart_upload.assert_not_called()


def test_large_file_multipart_with_overwrite_is_unconditional(multipart_s3, small_file):
    _upload_file(multipart_s3, small_file, BUCKET, "k", True)

    assert "IfNoneMatch" not in multipart_s3.complete_multipart_upload.call_args.kwargs


def test_large_file_grows_part_size_to_stay_under_part_limit(
    mocker, multipart_s3, small_file
):
    mocker.patch("prescient_sdk.uploads._MAX_PARTS", 2)

    _upload_file(multipart_s3, small_file, BUCKET, "k", False)

    bodies = sorted(c.kwargs["Body"] for c in multipart_s3.upload_part.call_args_list)
    assert bodies == [b"01234", b"56789"]


def test_large_file_part_failure_aborts(multipart_s3, small_file):
    error = ClientError({"Error": {"Code": "InternalError"}}, "UploadPart")
    multipart_s3.upload_part.side_effect = error

    with pytest.raises(ClientError):
        _upload_file(multipart_s3, small_file, BUCKET, "k", False)

    multipart_s3.complete_multipart_upload.assert_not_called()
    multipart_s3.abort_multipart_upload.assert_called_once_with(
        Bucket=BUCKET, Key="k", UploadId="up-1"
    )


def test_large_existing_file_412_on_complete_is_skipped_and_aborted(
    multipart_s3, small_file
):
    multipart_s3.complete_multipart_upload.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed"}}, "CompleteMultipartUpload"
    )

    assert _upload_file(multipart_s3, small_file, BUCKET, "k", False) is False
    multipart_s3.abort_multipart_upload.assert_called_once_with(
        Bucket=BUCKET, Key="k", UploadId="up-1"
    )


def test_large_file_412_is_still_skipped_when_the_upload_is_already_gone(
    multipart_s3, small_file
):
    multipart_s3.complete_multipart_upload.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed"}}, "CompleteMultipartUpload"
    )
    multipart_s3.abort_multipart_upload.side_effect = ClientError(
        {"Error": {"Code": "NoSuchUpload"}}, "AbortMultipartUpload"
    )

    assert _upload_file(multipart_s3, small_file, BUCKET, "k", False) is False


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def test_relative_posix_windows_style():
    root = PureWindowsPath(r"C:\data\scenes")
    file = PureWindowsPath(r"C:\data\scenes\nested\image.tif")
    assert _relative_posix(file, root) == "nested/image.tif"


def test_relative_posix_posix_style():
    root = PurePosixPath("/data/scenes")
    file = PurePosixPath("/data/scenes/nested/image.tif")
    assert _relative_posix(file, root) == "nested/image.tif"


def test_key_from_windows_path_uses_forward_slashes():
    # The S3 key is prefix + relative posix path; a Windows source tree must
    # still produce forward-slash keys (S3 keys never use backslashes).
    root = PureWindowsPath(r"C:\data\scenes")
    file = PureWindowsPath(r"C:\data\scenes\a\b\image.tif")

    key = "uploads/scenes/" + _relative_posix(file, root)

    assert key == "uploads/scenes/a/b/image.tif"
    assert "\\" not in key
