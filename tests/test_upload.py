from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from prescient_sdk.upload import (
    _relative_posix,
    iter_files,
    upload_source_files,
)


def _make_tree(root: Path, rel_paths: list[str]) -> None:
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


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


class FakeUploader:
    """Records ``(local_file, destination)`` for each call."""

    def __init__(self):
        self.calls: list[tuple[Path, str]] = []

    def __call__(self, local_file: Path, destination: str) -> None:
        self.calls.append((local_file, destination))

    @property
    def destinations(self) -> list[str]:
        return sorted(d for _, d in self.calls)


def test_upload_source_files_filters_and_preserves_relative_paths(tmp_path):
    _make_tree(tmp_path, ["a.tif", "sub/b.tif", "note.txt"])
    calls = []
    uploader = FakeUploader()

    upload_source_files(
        tmp_path,
        "s3://test-bucket/user-uploads/uid/",
        r".*\.tif$",
        uploader,
        on_file=lambda index, total, path: calls.append((index, total, path)),
    )

    # only .tif files, sent to dest_prefix + relative path (no dir-name segment)
    assert sorted(uploader.calls) == [
        (tmp_path / "a.tif", "s3://test-bucket/user-uploads/uid/a.tif"),
        (tmp_path / "sub" / "b.tif", "s3://test-bucket/user-uploads/uid/sub/b.tif"),
    ]
    assert all(tmp_path.name not in d for d in uploader.destinations)
    # on_file fired once per uploaded file with a 1-based index and the total
    assert [(index, total) for index, total, _ in calls] == [(1, 2), (2, 2)]
    assert {path for _, _, path in calls} == {
        tmp_path / "a.tif",
        tmp_path / "sub" / "b.tif",
    }


def test_upload_source_files_uses_anchored_match(tmp_path):
    # re.match anchors at the start: "scene.tif" matches at the root but not
    # under a subdirectory, so only the root file is selected.
    _make_tree(tmp_path, ["scene.tif", "sub/scene.tif"])

    uploader = FakeUploader()

    upload_source_files(tmp_path, "s3://test-bucket/p/", r"scene\.tif$", uploader)

    assert uploader.destinations == ["s3://test-bucket/p/scene.tif"]


def test_upload_source_files_adds_slash_to_prefix(tmp_path):
    _make_tree(tmp_path, ["a.tif"])
    uploader = FakeUploader()

    upload_source_files(tmp_path, "s3://test-bucket/p", r".*", uploader)

    assert uploader.destinations == ["s3://test-bucket/p/a.tif"]


def test_upload_source_files_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        upload_source_files(
            tmp_path / "nope", "s3://test-bucket/p/", ".*", FakeUploader()
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


def test_upload_source_files_windows_pattern_matches_relative_posix(tmp_path):
    # A pattern written with a forward-slash subdirectory (as authored in a spec)
    # must match nested files regardless of the local OS separator, because
    # matching runs on the posix relative path.
    _make_tree(tmp_path, ["a/scene.tif", "b/scene.tif", "a/note.txt"])

    uploader = FakeUploader()

    upload_source_files(tmp_path, "s3://test-bucket/p/", r"a/.*\.tif$", uploader)

    assert uploader.destinations == ["s3://test-bucket/p/a/scene.tif"]
