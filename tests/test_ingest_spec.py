"""Tests for the IngestSpec value object."""

import io
import textwrap
from types import SimpleNamespace

import pytest
import yaml
from rich.console import Console

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


DEST = "dest://uploads"


def fake_uploader(local_file, destination):
    raise AssertionError("upload_source_files is patched; uploader must not run")


def stage(spec, sets, console, **kwargs):
    kwargs.setdefault("uploader", fake_uploader)
    kwargs.setdefault("dest_prefix", DEST)
    return spec.with_uploaded_sources(sets, console=console, **kwargs)


def test_with_uploaded_sources_stages_set(upload_mock, uuid_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(spec, ["images"], quiet_console)

    upload_mock.assert_called_once()
    args, kwargs = upload_mock.call_args
    local_dir, dest_prefix, pattern, uploader = args
    assert local_dir == "/data/scenes"
    assert dest_prefix == "dest://uploads/uuid-1/"
    assert pattern == r".*\.tif$"
    assert uploader is fake_uploader
    assert callable(kwargs["on_file"])

    assert (
        staged.spec["locations"]["source_location"]["path"] == "dest://uploads/uuid-1/"
    )


def test_with_uploaded_sources_shared_location_one_prefix(
    upload_mock, uuid_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(spec, ["images", "thumbs"], quiet_console)

    # Both sets reference source_location: one uuid, one rewrite, two uploads.
    assert uuid_mock.call_count == 1
    assert upload_mock.call_count == 2
    dests = {call.args[1] for call in upload_mock.call_args_list}
    assert dests == {"dest://uploads/uuid-1/"}
    assert (
        staged.spec["locations"]["source_location"]["path"] == "dest://uploads/uuid-1/"
    )


def test_with_uploaded_sources_distinct_locations_distinct_prefixes(
    upload_mock, uuid_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(spec, ["images", "props"], quiet_console)

    assert uuid_mock.call_count == 2
    assert (
        staged.spec["locations"]["source_location"]["path"] == "dest://uploads/uuid-1/"
    )
    # file:// scheme is stripped before upload.
    props_call = next(
        c for c in upload_mock.call_args_list if c.args[0] == "/data/props"
    )
    assert props_call.args[1] == "dest://uploads/uuid-2/"
    assert (
        staged.spec["locations"]["props_location"]["path"] == "dest://uploads/uuid-2/"
    )


def test_with_uploaded_sources_trailing_slash_in_prefix(
    upload_mock, uuid_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(spec, ["images"], quiet_console, dest_prefix="s3://b/user-uploads/")
    assert upload_mock.call_args.args[1] == "s3://b/user-uploads/uuid-1/"
    assert (
        staged.spec["locations"]["source_location"]["path"]
        == "s3://b/user-uploads/uuid-1/"
    )
    assert staged.local_locations() == ["props_location"]


def test_with_uploaded_sources_is_immutable(upload_mock, uuid_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(spec, ["images"], quiet_console)

    assert staged is not spec
    # Original is untouched: source_location still local.
    assert spec.spec["locations"]["source_location"]["path"] == "/data/scenes"
    assert "source_location" in spec.local_locations()


def test_with_uploaded_sources_missing_set_raises(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="nope"):
        stage(spec, ["nope"], quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_missing_location_raises(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="missing_location"):
        stage(spec, ["dangling"], quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_already_s3_raises(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="already an s3://"):
        stage(spec, ["already_remote"], quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_requires_dest_prefix(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="dest_prefix"):
        stage(spec, ["images"], quiet_console, dest_prefix="")
    upload_mock.assert_not_called()


def test_with_uploaded_sources_validates_before_uploading(
    upload_mock, uuid_mock, quiet_console
):
    # A bad name after a good one must not leave a partial upload.
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError):
        stage(spec, ["images", "nope"], quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_calls_uploader_per_file(
    mocker, tmp_path, uuid_mock, quiet_console
):
    """from_file -> with_uploaded_sources -> create, with a fake uploader."""
    from prescient_sdk.ingest_resources import IngestResource

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

    uploaded: list[tuple] = []

    def uploader(local_file, destination):
        uploaded.append((local_file, destination))

    spec = IngestSpec.from_file(spec_file)
    ready = spec.with_uploaded_sources(
        ["images"],
        uploader=uploader,
        dest_prefix="s3://upload-bucket/uploads",
        console=quiet_console,
    )

    # One call per pattern-matched file, relative paths kept under the uuid prefix.
    assert sorted(uploaded) == [
        (scenes / "a.tif", "s3://upload-bucket/uploads/uuid-1/a.tif"),
        (scenes / "nested" / "b.tif", "s3://upload-bucket/uploads/uuid-1/nested/b.tif"),
    ]
    assert (
        ready.spec["locations"]["source_location"]["path"]
        == "s3://upload-bucket/uploads/uuid-1/"
    )
    assert ready.local_locations() == []
    # The original spec still points at the local directory.
    assert spec.spec["locations"]["source_location"]["path"] == str(scenes)

    # The rewritten spec passes the create() guardrail and is submitted as YAML.
    create_client = mocker.MagicMock()
    create_client.create_ingestion.return_value = SimpleNamespace(id=42)
    resource = IngestResource.create(create_client, ready)
    assert resource.id == 42
    assert isinstance(create_client.create_ingestion.call_args.args[0], bytes)
