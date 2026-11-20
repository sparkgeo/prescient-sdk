"""Tests for the IngestSpec value object."""

import copy
import io
import textwrap
from types import SimpleNamespace

import pytest
import yaml
from rich.console import Console

from prescient_sdk.ingest_spec import IngestSpec


SPEC = {
    "version": "2.0.0",
    "locations": {
        "source_location": {"path": "s3://source-bucket/data"},
        "target_location": {"path": "s3://target-bucket"},
    },
    "source_files": {
        "enhanced": {"location": "source_location", "pattern": r".*\.tif$"},
    },
}


LOCAL_SPEC = {
    "version": "2.0.0",
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
    return mocker.patch(
        "prescient_sdk.ingest_spec.upload", return_value="01jz-generated"
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
            version: "2.0.0"
            locations:
              source_location:
                path: s3://source-bucket/data
            """
        )
    )
    spec = IngestSpec.from_file(path)
    assert spec.spec["version"] == "2.0.0"
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


@pytest.mark.parametrize("content", [b"", b"- a\n- list\n"])
def test_from_bytes_non_mapping_raises(content):
    with pytest.raises(ValueError, match="mapping"):
        IngestSpec.from_bytes(content)


def test_spec_accessor_returns_copy():
    spec = IngestSpec.from_dict(SPEC)
    spec.spec["version"] = "mutated"
    assert spec.spec["version"] == "2.0.0"


def test_to_bytes_round_trips_and_preserves_order():
    spec = IngestSpec.from_dict(SPEC)
    reparsed = yaml.safe_load(spec.to_bytes())
    assert reparsed == SPEC
    # version was authored first; sort_keys=False must preserve that
    assert list(reparsed.keys())[0] == "version"
    # and it stays a string, not the YAML float 2.0
    assert reparsed["version"] == "2.0.0"


def test_local_locations_flags_local_directories():
    spec = IngestSpec.from_dict(
        {
            "locations": {
                "external": {"path": "s3://bucket/data"},
                "public": {"path": "https://b.s3.eu-west-1.amazonaws.com/x"},
                "org_bucket": {"path": "lidar/2026"},
                "org_bucket_dot": {"path": "./lidar/"},
                "local_dir": {"path": "/mnt/data/scenes"},
                "file_uri": {"path": "file:///mnt/data"},
                "home": {"path": "~/data"},
                "parent": {"path": "../data"},
                "windows": {"path": "C:\\data\\scenes"},
                "missing_path": {},
            }
        }
    )
    assert spec.local_locations() == [
        "local_dir",
        "file_uri",
        "home",
        "parent",
        "windows",
        "missing_path",
    ]


def test_local_locations_empty_when_all_remote():
    assert IngestSpec.from_dict(SPEC).local_locations() == []


def test_local_locations_no_locations_key():
    assert IngestSpec.from_dict({"version": "2.0.0"}).local_locations() == []


def test_problems_empty_for_v2_spec():
    spec = IngestSpec.from_dict(
        {
            "version": "2.1",
            "locations": {
                "raw": {"path": "lidar/2026"},
                "partner": {"path": "s3://partner-data/2026", "credentials": True},
            },
        }
    )
    assert spec.problems() == []


@pytest.mark.parametrize(
    "spec,expected",
    [
        ({**SPEC, "user": "tester"}, '"user" is not allowed'),
        ({**SPEC, "version": "1.0"}, '"version" must be a string that starts with'),
        ({**SPEC, "version": 2.0}, '"version" must be a string'),
        ({"locations": SPEC["locations"]}, '"version"'),
        (
            {"version": "2.0.0", "locations": {"src": {"path": "/data"}}},
            "local directories and must be uploaded first: ['src']",
        ),
        (
            {
                "version": "2.0.0",
                "locations": {"raw": {"path": "lidar", "credentials": True}},
            },
            "location 'raw': \"credentials\" is only for an External bucket",
        ),
    ],
    ids=["user", "v1", "float", "missing-version", "local", "org-credentials"],
)
def test_problems_reports_what_the_api_rejects(spec, expected):
    problems = IngestSpec.from_dict(spec).problems()
    assert len(problems) == 1
    assert expected in problems[0]


CLIENT = object()


def stage(spec, sets, console, **kwargs):
    return spec.with_uploaded_sources(sets, client=CLIENT, console=console, **kwargs)


def test_with_uploaded_sources_stages_set(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(spec, ["images"], quiet_console)

    upload_mock.assert_called_once()
    args, kwargs = upload_mock.call_args
    assert args == (CLIENT, "/data/scenes", None)
    assert kwargs["pattern"] == r".*\.tif$"
    assert kwargs["overwrite"] is False
    assert callable(kwargs["on_file"])

    # A path with no scheme: the Ingest API reads it under uploads/.
    assert staged.spec["locations"]["source_location"]["path"] == "01jz-generated"


def test_with_uploaded_sources_passes_location_and_overwrite(
    upload_mock, quiet_console
):
    upload_mock.return_value = "scenes/2026"
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(
        spec, ["images"], quiet_console, location="scenes/2026", overwrite=True
    )

    assert upload_mock.call_args.args[2] == "scenes/2026"
    assert upload_mock.call_args.kwargs["overwrite"] is True
    assert staged.spec["locations"]["source_location"]["path"] == "scenes/2026"


def test_with_uploaded_sources_shared_location_one_upload_location(
    upload_mock, quiet_console
):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(spec, ["images", "thumbs"], quiet_console)

    # Both sets reference source_location: the second set writes to the
    # location the first one returned.
    first, second = upload_mock.call_args_list
    assert first.args[2] is None
    assert second.args[2] == "01jz-generated"
    assert {first.kwargs["pattern"], second.kwargs["pattern"]} == {
        r".*\.tif$",
        r".*\.png$",
    }
    assert staged.spec["locations"]["source_location"]["path"] == "01jz-generated"


def test_with_uploaded_sources_strips_file_scheme(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    staged = stage(spec, ["props"], quiet_console)

    assert upload_mock.call_args.args[1] == "/data/props"
    assert staged.spec["locations"]["props_location"]["path"] == "01jz-generated"
    assert staged.local_locations() == ["source_location"]


def test_with_uploaded_sources_multiple_locations_raises(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="separate call"):
        stage(spec, ["images", "props"], quiet_console)
    upload_mock.assert_not_called()


@pytest.mark.parametrize("path", ["", "file://"])
def test_with_uploaded_sources_empty_path_raises(upload_mock, quiet_console, path):
    spec_dict = copy.deepcopy(LOCAL_SPEC)
    spec_dict["locations"]["source_location"]["path"] = path
    with pytest.raises(ValueError, match="has no path"):
        stage(IngestSpec.from_dict(spec_dict), ["images"], quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_is_immutable(upload_mock, quiet_console):
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


def test_with_uploaded_sources_already_external_raises(upload_mock, quiet_console):
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError, match="already an External bucket URL"):
        stage(spec, ["already_remote"], quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_validates_before_uploading(upload_mock, quiet_console):
    # A bad name after a good one must not leave a partial upload.
    spec = IngestSpec.from_dict(LOCAL_SPEC)
    with pytest.raises(ValueError):
        stage(spec, ["images", "nope"], quiet_console)
    upload_mock.assert_not_called()


def test_with_uploaded_sources_uploads_each_file(mocker, tmp_path, quiet_console):
    """from_file -> with_uploaded_sources -> create, with fileproxy and S3 mocked."""
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
            version: "2.0.0"
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

    mocker.patch(
        "prescient_sdk.uploads._issue_credentials",
        return_value={
            "location": "01jz-generated",
            "bucket": "org-bucket",
            "prefix": "uploads/01jz-generated/",
        },
    )
    s3 = mocker.Mock()
    mocker.patch("prescient_sdk.uploads._s3_client", return_value=s3)

    spec = IngestSpec.from_file(spec_file)
    ready = spec.with_uploaded_sources(
        ["images"], client=mocker.Mock(), console=quiet_console
    )

    # One write per pattern-matched file, relative paths kept under the prefix.
    assert sorted(c.kwargs["Key"] for c in s3.put_object.call_args_list) == [
        "uploads/01jz-generated/a.tif",
        "uploads/01jz-generated/nested/b.tif",
    ]
    assert ready.spec["locations"]["source_location"]["path"] == "01jz-generated"
    assert ready.local_locations() == []
    assert ready.problems() == []
    # The original spec still points at the local directory.
    assert spec.spec["locations"]["source_location"]["path"] == str(scenes)

    # The rewritten spec passes the create() guardrail and is submitted as YAML.
    create_client = mocker.MagicMock()
    create_client.create_ingestion.return_value = SimpleNamespace(id=42)
    resource = IngestResource.create(create_client, ready)
    assert resource.id == 42
    assert isinstance(create_client.create_ingestion.call_args.args[0], bytes)
