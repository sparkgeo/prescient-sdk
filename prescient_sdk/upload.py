"""Upload files to bucket."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path, PurePath
from typing import Optional

import boto3
import botocore.exceptions

from prescient_sdk.client import PrescientClient

FileList = list[PurePath]

logger = logging.getLogger(__name__)


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


def _upload(
    file: str, bucket: str, key: str, session: boto3.Session, overwrite: bool = True
) -> None:
    s3 = session.client("s3")

    if not overwrite:
        try:
            _ = s3.head_object(Bucket=bucket, Key=key)
            logger.info(
                "skipping file %s as it already exists at s3://%s%s", file, bucket, key
            )
            return
        except botocore.exceptions.ClientError as e:
            if "Not Found" in e.args[0]:
                pass
            else:
                raise e

    logger.info("uploading file %s to s3://%s%s", file, bucket, key)
    s3.upload_file(Filename=file, Bucket=bucket, Key=key)


def upload(
    input_dir: str | os.PathLike,
    exclude: Optional[list[str]] = None,
    prescient_client: Optional[PrescientClient] = None,
    overwrite: bool = True,
) -> None:
    """
    Upload files from input directory to the location defined by PRESCIENT_UPLOAD_BUCKET


    Args:
        input_dir (str | os.PathLike): Input directory containing file(s) to be uploaded.
            By default will upload all files contained in input directory.
        exclude (Optional[list[str]]): A list of glob patterns to exclude from uploading.
            For example `exclude=["*.txt", "*.csv"] would skip any matched files that end with a .txt or
            .csv suffix. If not provided by default all files will be uploaded.
        prescient_client (Optional[PrescientClient]): A PrescientClient instance. If not provided
            a default PrescientClient instance will be created.
        overwrite (bool): Whether to overwrite objects if they already exist. If False, upload
            is skipped. Useful for continuing an upload that was started previously. Defaults to True.
    """
    if overwrite:
        logger.info("overwrite=%s, thus will overwrite any existing objects", overwrite)
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(input_dir)

    prescient_client = prescient_client or PrescientClient()

    files = list(iter_files(input_path, exclude=exclude))
    logger.info("found %s files to upload", len(files))
    for file in files:
        _upload(
            file=str(file),
            bucket=prescient_client.settings.prescient_upload_bucket,
            key=file.as_posix(),
            session=prescient_client.upload_session,
            overwrite=overwrite,
        )
