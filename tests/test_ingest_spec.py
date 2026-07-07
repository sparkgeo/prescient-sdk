"""Tests for the IngestSpec value object."""

import textwrap

import pytest
import yaml

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
