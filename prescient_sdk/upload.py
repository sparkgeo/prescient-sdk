"""Upload files to bucket."""
from __future__ import annotations
import os
from pathlib import Path, PurePath
from typing import Optional
from collections.abc import Iterator


FileList = list[PurePath]


def iter_files(input_dir: Path, exclude: Optional[list[str]] = None) -> Iterator[Path]:
    """Return an iterator of Path"""
    glob_pattern = "**/*"

    for path in input_dir.glob(glob_pattern):
        if path.is_dir():
            continue
        if exclude:
            if any(path.match(e) for e in exclude):
                continue

        yield path


def upload(
    input_dir: str | os.PathLike, exclude: Optional[list[str]] = None
) -> None:
    pass
