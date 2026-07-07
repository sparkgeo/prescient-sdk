"""Tests for the IngestSpec value object."""

import io
import textwrap
from types import SimpleNamespace

import pytest
import yaml
from rich.console import Console

from prescient_sdk.client import PrescientClient
from prescient_sdk.ingest_client import IngestClient
from prescient_sdk.ingest_spec import IngestSpec


SPEC = {
    "user": "tester",
    "locations": {
        "source_location": {"path": "s3://source-bucket/data"},
        "target_location": {"path": "s3://target-bucket"},
    },
    "source_files": {
        "enhanced": {"location": "source_location", "pattern": r".*\.tif$"},
    },
}


LOCAL_SPEC = {
    "user": "tester",
    "locations": {
        "source_location": {"path": "/data/scenes"},
        "props_location": {"path": "file:///data/props"},
        "target_location": {"path": "s3://target-bucket"},
    },
    "source_files": {
        "images": {"location": "source_location", "pattern": r".*\.tif$"},
        "thumbs": {"location": "source_location", "pattern": r".*\.png$"},
        "props": {"location": "props_location", "pattern": r".*\.csv$"},
        "already_remote": {"location": "target_location", "pattern": r".*"},
        "dangling": {"location": "missing_location", "pattern": r".*"},
    },
}


@pytest.fixture
def quiet_console():
    return Console(file=io.StringIO(), force_terminal=False)


@pytest.fixture
def prescient_client(mocker):
    """A mock PrescientClient with upload bucket configured and an STS session."""
    client = mocker.MagicMock(spec=PrescientClient)
    client.settings = SimpleNamespace(
        prescient_upload_bucket="upload-bucket",
        prescient_upload_prefix=None,
    )
    client.upload_session = mocker.sentinel.session
    return client


@pytest.fixture
def upload_mock(mocker):
    return mocker.patch("prescient_sdk.ingest_spec.upload_source_files")


@pytest.fixture
def uuid_mock(mocker):
    return mocker.patch(
        "prescient_sdk.ingest_spec.uuid4",
        side_effect=["uuid-1", "uuid-2", "uuid-3"],
    )


def test_from_dict_copies_input():
    original = {"locations": {"a": {"path": "s3://b/x"}}}
    spec = IngestSpec.from_dict(original)
    original["locations"]["a"]["path"] = "mutated"
    assert spec.spec["locations"]["a"]["path"] == "s3://b/x"


def test_from_dict_rejects_non_mapping():
    with pytest.raises(ValueError):
        IngestSpec.from_dict(["not", "a", "mapping"])


def test_from_file_parses_yaml(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text(
        textwrap.dedent(
            """
            user: tester
            locations:
              source_location:
                path: s3://source-bucket/data
            """
        )
    )
    spec = IngestSpec.from_file(path)
    assert spec.spec["user"] == "tester"
    assert (
        spec.spec["locations"]["source_location"]["path"] == "s3://source-bucket/data"
    )


def test_from_file_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        IngestSpec.from_file(tmp_path / "nope.yaml")


def test_from_file_non_mapping_raises(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError):
        IngestSpec.from_file(path)


def test_spec_accessor_returns_copy():
    spec = IngestSpec.from_dict(SPEC)
    spec.spec["user"] = "mutated"
    assert spec.spec["user"] == "tester"


def test_to_bytes_round_trips_and_preserves_order():
    spec = IngestSpec.from_dict(SPEC)
    reparsed = yaml.safe_load(spec.to_bytes())
    assert reparsed == SPEC
    # user was authored first; sort_keys=False must preserve that
    assert list(reparsed.keys())[0] == "user"


def test_local_locations_flags_non_s3():
    spec = IngestSpec.from_dict(
        {
            "locations": {
                "remote": {"path": "s3://bucket/data"},
                "local_dir": {"path": "/mnt/data/scenes"},
                "file_uri": {"path": "file:///mnt/data"},
                "missing_path": {},
            }
        }
    )
    assert spec.local_locations() == ["local_dir", "file_uri", "missing_path"]


def test_local_locations_empty_when_all_s3():
    assert IngestSpec.from_dict(SPEC).local_locations() == []


def test_local_locations_no_locations_key():
    assert IngestSpec.from_dict({"user": "tester"}).local_locations() == []


def test_with_uploaded_sources_stages_set(
    prescient_client, upload_mock, uuid_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = spec.with_uploaded_sources(
        prescient_client, ["images"], console=quiet_console
    )

    upload_mock.assert_called_once()
    args, kwargs = upload_mock.call_args
    local_dir, dest_prefix, pattern, session = args
    assert local_dir == "/data/scenes"
    assert dest_prefix == "s3://upload-bucket/uuid-1/"
    assert pattern == r".*\.tif$"
    assert session is prescient_client.upload_session
    assert callable(kwargs["on_file"])

    assert (
        staged.spec["locations"]["source_location"]["path"]
        == "s3://upload-bucket/uuid-1/"
    )
    assert staged.local_locations() == ["props_location"]


def test_with_uploaded_sources_shared_location_one_prefix(
    prescient_client, upload_mock, uuid_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = spec.with_uploaded_sources(
        prescient_client, ["images", "thumbs"], console=quiet_console
    )

    # Both sets reference source_location: one uuid, one rewrite, two uploads.
    assert uuid_mock.call_count == 1
    assert upload_mock.call_count == 2
    dests = {call.args[1] for call in upload_mock.call_args_list}
    assert dests == {"s3://upload-bucket/uuid-1/"}
    assert (
        staged.spec["locations"]["source_location"]["path"]
        == "s3://upload-bucket/uuid-1/"
    )


def test_with_uploaded_sources_distinct_locations_distinct_prefixes(
    prescient_client, upload_mock, uuid_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = spec.with_uploaded_sources(
        prescient_client, ["images", "props"], console=quiet_console
    )

    assert uuid_mock.call_count == 2
    assert (
        staged.spec["locations"]["source_location"]["path"]
        == "s3://upload-bucket/uuid-1/"
    )
    # file:// scheme is stripped before upload.
    props_call = next(
        c for c in upload_mock.call_args_list if c.args[0] == "/data/props"
    )
    assert props_call.args[1] == "s3://upload-bucket/uuid-2/"
    assert (
        staged.spec["locations"]["props_location"]["path"]
        == "s3://upload-bucket/uuid-2/"
    )
    assert staged.local_locations() == []


def test_with_uploaded_sources_honors_upload_prefix(
    prescient_client, upload_mock, uuid_mock, quiet_console
):
    prescient_client.settings.prescient_upload_prefix = "user-uploads"
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = spec.with_uploaded_sources(
        prescient_client, ["images"], console=quiet_console
    )
    assert upload_mock.call_args.args[1] == "s3://upload-bucket/user-uploads/uuid-1/"
    assert (
        staged.spec["locations"]["source_location"]["path"]
        == "s3://upload-bucket/user-uploads/uuid-1/"
    )


def test_with_uploaded_sources_is_immutable(
    prescient_client, upload_mock, uuid_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = spec.with_uploaded_sources(
        prescient_client, ["images"], console=quiet_console
    )

    assert staged is not spec
    # Original is untouched: source_location still local.
    assert spec.spec["locations"]["source_location"]["path"] == "/data/scenes"
    assert "source_location" in spec.local_locations()


def test_with_uploaded_sources_accepts_ingest_client(
    mocker, prescient_client, upload_mock, uuid_mock, quiet_console
):
    ingest_client = mocker.MagicMock(spec=IngestClient)
    ingest_client.client = prescient_client
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    spec.with_uploaded_sources(ingest_client, ["images"], console=quiet_console)
    assert upload_mock.call_args.args[3] is prescient_client.upload_session


def test_with_uploaded_sources_rejects_bad_client_type(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(TypeError):
        spec.with_uploaded_sources(object(), ["images"], console=quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_missing_set_raises(
    prescient_client, upload_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="nope"):
        spec.with_uploaded_sources(prescient_client, ["nope"], console=quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_missing_location_raises(
    prescient_client, upload_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="missing_location"):
        spec.with_uploaded_sources(
            prescient_client, ["dangling"], console=quiet_console
        )
    upload_mock.assert_not_called()


def test_with_uploaded_sources_already_s3_raises(
    prescient_client, upload_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="already an s3://"):
        spec.with_uploaded_sources(
            prescient_client, ["already_remote"], console=quiet_console
        )
    upload_mock.assert_not_called()


def test_with_uploaded_sources_requires_upload_bucket(
    prescient_client, upload_mock, quiet_console
):
    prescient_client.settings.prescient_upload_bucket = None
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="prescient_upload_bucket"):
        spec.with_uploaded_sources(prescient_client, ["images"], console=quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_validates_before_uploading(
    prescient_client, upload_mock, uuid_mock, quiet_console
):
    # A bad name after a good one must not leave a partial upload.
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError):
        spec.with_uploaded_sources(
            prescient_client, ["images", "nope"], console=quiet_console
        )
    upload_mock.assert_not_called()


def test_with_uploaded_sources_end_to_end(
    mocker, tmp_path, s3, uuid_mock, quiet_console
):
    """from_file -> with_uploaded_sources -> create against a real (moto) bucket."""
    import boto3

    from prescient_sdk.ingest_resources import IngestResource

    s3.create_bucket(Bucket="upload-bucket")
    scenes = tmp_path / "scenes"
    (scenes / "nested").mkdir(parents=True)
    (scenes / "a.tif").write_bytes(b"x")
    (scenes / "nested" / "b.tif").write_bytes(b"y")
    (scenes / "skip.txt").write_bytes(b"z")

    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(
        textwrap.dedent(
            f"""
            user: tester
            locations:
              source_location:
                path: {scenes}
              target_location:
                path: s3://target-bucket/out
            source_files:
              images:
                location: source_location
                pattern: ".*\\\\.tif$"
            """
        )
    )

    client = mocker.MagicMock(spec=PrescientClient)
    client.settings = SimpleNamespace(
        prescient_upload_bucket="upload-bucket", prescient_upload_prefix=None
    )
    client.upload_session = boto3.Session(region_name="us-east-1")

    spec = IngestSpec.from_file(spec_file)
    ready = spec.with_uploaded_sources(client, ["images"], console=quiet_console)

    # Pattern-matched files uploaded under the uuid prefix, relative paths kept.
    keys = sorted(
        o["Key"] for o in s3.list_objects_v2(Bucket="upload-bucket")["Contents"]
    )
    assert keys == ["uuid-1/a.tif", "uuid-1/nested/b.tif"]
    assert (
        ready.spec["locations"]["source_location"]["path"]
        == "s3://upload-bucket/uuid-1/"
    )
    assert ready.local_locations() == []

    # The now-s3-only spec passes the create() guardrail and is submitted as YAML.
    create_client = mocker.MagicMock()
    create_client.create_ingestion.return_value = SimpleNamespace(id=42)
    resource = IngestResource.create(create_client, ready)
    assert resource.id == 42
    assert isinstance(create_client.create_ingestion.call_args.args[0], bytes)
