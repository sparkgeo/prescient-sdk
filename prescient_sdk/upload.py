"""Upload files to bucket."""
from __future__ import annotations
import os
from pathlib import Path, PurePath
from typing import Optional
from collections.abc import Iterator

import boto3

from prescient_sdk.client import PrescientClient


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


def _upload(file: str, bucket: str, key: str, session: boto3.Session, overwrite: bool = True) -> None:
    s3 = session.client("s3")
    
    if not overwrite:
        # TODO: Require HeadObject permission
        raise NotImplementedError
        
    s3.upload_file(Filename=file, Bucket=bucket, Key=key)

def upload(
    input_dir: str | os.PathLike, exclude: Optional[list[str]] = None, prescient_client: Optional[PrescientClient] = None
) -> None:
    prescient_client = prescient_client or PrescientClient()
    input_path = Path(input_dir)
    for file in iter_files(input_path, exclude=exclude):
        _upload(
            file=str(file),
            bucket=prescient_client.settings.prescient_upload_bucket,
            key=file.as_posix(),
            session=prescient_client.upload_session
        )
