"""Upload files to bucket."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from pathlib import Path, PurePath
from typing import Callable, Optional

import boto3
import botocore.exceptions

from prescient_sdk.client import PrescientClient

FileList = list[PurePath]

logger = logging.getLogger(__name__)


def iter_files(input_dir: Path, exclude: Optional[list[str]] = None) -> Iterator[Path]:
    """Recursively yield files under ``input_dir``, skipping directories.

    Args:
        input_dir: Directory to walk recursively.
        exclude: Optional list of glob patterns; any file whose path matches a
            pattern is skipped.

    Yields:
        Each file path that survives the ``exclude`` filter.
    """
    glob_pattern = "**/*"

    for path in input_dir.glob(glob_pattern):
        if path.is_dir():
            continue
        if exclude:
            matched = next((e for e in exclude if path.match(e)), None)
            if matched is not None:
                logger.debug("Excluded %s (matched %s)", path, matched)
                continue

        yield path


def _upload(
    file: str, bucket: str, key: str, session: boto3.Session, overwrite: bool = True
) -> None:
    s3 = session.client("s3")

    if not overwrite:
        logger.debug("Pre-flight head_object on s3://%s/%s", bucket, key)
        try:
            _ = s3.head_object(Bucket=bucket, Key=key)
            logger.info(
                "skipping file %s as it already exists at s3://%s/%s", file, bucket, key
            )
            return
        except botocore.exceptions.ClientError as e:
            if "Not Found" in e.args[0]:
                pass
            else:
                raise e

    logger.info("uploading file %s to s3://%s/%s", file, bucket, key)
    s3.upload_file(Filename=file, Bucket=bucket, Key=key)


def _make_s3_key(file: Path, root: Path) -> str:
    """
    Compute an S3 key for `file` relative to the `root` directory, including
    the root directory name itself as the top-level folder.

    Args:
        file (Path): The full path to the file being uploaded.
        root (Path): The root input directory passed to `upload`.

    Returns:
        str: The normalized S3 key.
    """
    root_name = root.name or root.resolve().name
    relative_part = file.relative_to(root).as_posix()
    return f"{root_name}/{relative_part}"


def _split_s3_uri(uri: str) -> tuple[str, str]:
    """Split an ``s3://bucket/key/prefix`` URI into ``(bucket, key_prefix)``.

    The returned key prefix is normalized to end with ``/`` (unless empty) so
    it can be concatenated directly with a relative path to form an object key.

    Args:
        uri (str): An ``s3://`` URI.

    Returns:
        tuple[str, str]: The bucket name and the (possibly empty) key prefix.

    Raises:
        ValueError: If ``uri`` is not an ``s3://`` URI or has no bucket.
    """
    if not uri.startswith("s3://"):
        raise ValueError(f"Destination must be an s3:// URI, got {uri!r}")
    bucket, _, key_prefix = uri[len("s3://") :].partition("/")
    if not bucket:
        raise ValueError(f"Destination s3:// URI is missing a bucket: {uri!r}")
    if key_prefix and not key_prefix.endswith("/"):
        key_prefix += "/"
    return bucket, key_prefix


def _relative_posix(file: PurePath, root: PurePath) -> str:
    """Return ``file``'s path relative to ``root`` using forward slashes.

    ``as_posix`` normalizes separators so S3 keys and pattern matching are
    identical on Windows and POSIX — e.g. a Windows ``nested\\image.tif``
    becomes ``nested/image.tif``. S3 keys always use ``/``, so the local OS
    separator must never leak into a key.

    Args:
        file (PurePath): The file path, under ``root``.
        root (PurePath): The directory ``file`` is relative to.

    Returns:
        str: The forward-slash relative path.
    """
    return file.relative_to(root).as_posix()


def upload_source_files(
    local_dir: str | os.PathLike,
    dest_prefix: str,
    pattern: str,
    session: boto3.Session,
    on_file: Optional[Callable[[int, int, Path], None]] = None,
    overwrite: bool = True,
) -> None:
    """Upload the files under ``local_dir`` that a source file set's pattern selects.

    Only files whose path *relative to* ``local_dir`` matches ``pattern`` are
    uploaded, and each is written to ``dest_prefix`` + that same relative path —
    verbatim, with no directory-name segment injected. This preserves every
    file's path relative to its location, so the spec's ``pattern`` still matches
    after the files move to S3 (the Ingest API strips the location prefix and
    applies ``re.match`` to the remaining relative path).

    ``pattern`` is applied with ``re.match`` (anchored at the start of the
    relative path), matching the Ingest API's own file selection.

    Example::

        session = prescient_client.upload_session
        upload_source_files(
            "/data/scenes",
            "s3://uploads/user-uploads/3f9.../",
            r".*\\.tif$",
            session,
        )

    Args:
        local_dir (str | os.PathLike): Local directory to scan recursively.
        dest_prefix (str): Destination ``s3://bucket/key/prefix/`` URI. Uploaded
            keys are ``dest_prefix`` joined with each file's relative path.
        pattern (str): Regex applied (``re.match``) to each file's posix path
            relative to ``local_dir``.
        session (boto3.Session): AWS session authorized to write to the bucket
            (typically ``PrescientClient.upload_session``).
        on_file (Callable[[int, int, Path], None], optional): Called after each
            upload with ``(index, total, path)`` where ``index`` is 1-based.
            Useful for progress display. Defaults to None.
        overwrite (bool, optional): When False, skip files that already exist at
            the destination key. Defaults to True.

    Raises:
        FileNotFoundError: If ``local_dir`` does not exist.
        ValueError: If ``dest_prefix`` is not a valid ``s3://`` URI.
    """
    local_path = Path(local_dir)
    if not local_path.exists():
        raise FileNotFoundError(local_dir)

    bucket, key_prefix = _split_s3_uri(dest_prefix)
    regex = re.compile(pattern)
    matched = [
        file
        for file in iter_files(local_path)
        if regex.match(_relative_posix(file, local_path))
    ]
    total = len(matched)
    logger.info(
        "staging %s file(s) matching %r from %s to %s",
        total,
        pattern,
        local_path,
        dest_prefix,
    )
    for index, file in enumerate(matched, start=1):
        _upload(
            file=str(file),
            bucket=bucket,
            key=key_prefix + _relative_posix(file, local_path),
            session=session,
            overwrite=overwrite,
        )
        if on_file is not None:
            on_file(index, total, file)


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
            By default will upload all files contained in input directory. This can be an
            absolute or relative path, the final path component will be included as part
            of the object key e.g. /path/to/data_dir -> s3://bucket/data_dir/file.txt.
            When input_dir is a relative path, this should be relative to the current working
            directory used to execute this function.
        exclude (Optional[list[str]]): A list of glob patterns to exclude from uploading.
            For example ``exclude=["*.txt", "*.csv"]`` would skip any matched files that end
            with a ``.txt`` or ``.csv`` suffix. If not provided, by default all files will
            be uploaded.
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

    if prescient_client is None:
        logger.debug(
            "No prescient_client provided; constructing default PrescientClient"
        )
        prescient_client = PrescientClient()

    bucket = prescient_client.settings.prescient_upload_bucket
    if not bucket:
        raise ValueError(
            "prescient_upload_bucket is not configured; set PRESCIENT_UPLOAD_BUCKET "
            "to upload files."
        )

    files = list(iter_files(input_path, exclude=exclude))
    logger.info("found %s files to upload", len(files))
    for file in files:
        relative_key = _make_s3_key(file, input_path)

        _upload(
            file=str(file),
            bucket=bucket,
            key=relative_key,
            session=prescient_client.upload_session,
            overwrite=overwrite,
        )
    logger.info("Upload complete: %s files to s3://%s", len(files), bucket)
