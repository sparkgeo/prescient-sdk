"""Upload local files to an Upload location in the Organization bucket.

:func:`upload` asks the platform file proxy for temporary S3 credentials that
can only write under ``uploads/<location>/``, then writes each file with boto3.
An Ingestion spec reads the files with the returned location as a location
``path``.

Without ``overwrite``, every write is conditional (``If-None-Match: *``), so a
file that already exists is refused and counted as skipped. Running the same
upload again therefore resumes it at file level. A large file is sent as a
multipart upload and is refused only at the end, after its parts are sent again.
"""

import logging
import os
import re
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePath
from typing import Any

import botocore.session
from botocore.credentials import RefreshableCredentials
from botocore.exceptions import ClientError

from prescient_sdk.client import PrescientClient

logger = logging.getLogger(__name__)

# Files up to this size are sent with one PutObject; larger ones as multipart
# uploads with parts of this size, grown so a file never needs more than
# _MAX_PARTS parts.
_PART_SIZE = 64 * 1024 * 1024
_MAX_PARTS = 10_000
_PART_WORKERS = 4
_REQUEST_TIMEOUT = 30


def iter_files(input_dir: Path, exclude: list[str] | None = None) -> Iterator[Path]:
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


def _relative_posix(file: PurePath, root: PurePath) -> str:
    """Return ``file``'s path relative to ``root`` using forward slashes.

    ``as_posix`` normalizes separators so keys and pattern matching are
    identical on Windows and POSIX — e.g. a Windows ``nested\\image.tif``
    becomes ``nested/image.tif``. The local OS separator must never leak into a
    key.

    Args:
        file (PurePath): The file path, under ``root``.
        root (PurePath): The directory ``file`` is relative to.

    Returns:
        str: The forward-slash relative path.
    """
    return file.relative_to(root).as_posix()


def upload(
    client: PrescientClient,
    local_dir: str | os.PathLike,
    location: str | None = None,
    *,
    pattern: str | None = None,
    overwrite: bool = False,
    on_file: Callable[[int, int, Path], None] | None = None,
) -> str:
    """Upload the files under ``local_dir`` to an Upload location.

    Each file is written to ``uploads/<location>/`` followed by its path
    relative to ``local_dir``, so a spec ``pattern`` that selects the local
    files selects the uploaded ones too.

    Without ``overwrite``, a file that already exists in the location is
    skipped, so you can run an interrupted upload again to finish it. The
    credentials last at most one hour; the SDK asks for new ones before they
    expire, so a long upload keeps working.

    Example::

        location = upload(client, "/data/scenes", pattern=r".*\\.tif$")
        # Use ``location`` as a location ``path`` in an Ingestion spec.

    Args:
        client (PrescientClient): The signed-in client. The caller needs the
            ingest permission in their Organization.
        local_dir (str | os.PathLike): Local directory to scan recursively.
        location (str, optional): The Upload location to write to: 1 to 4
            ``/``-separated segments of lower-case letters, digits, ``.``,
            ``_`` and ``-``. When omitted, the platform creates a new one.
        pattern (str, optional): Regex applied with ``re.match`` to each file's
            forward-slash path relative to ``local_dir``, as the Ingest API
            selects source files. When omitted, every file is uploaded.
        overwrite (bool): Replace files that already exist. Defaults to False.
        on_file (Callable[[int, int, Path], None], optional): Called after each
            file with ``(index, total, path)`` where ``index`` is 1-based.
            Useful for progress display.

    Returns:
        str: The Upload location, for a location ``path`` in an Ingestion spec.

    Raises:
        FileNotFoundError: If ``local_dir`` does not exist.
        requests.HTTPError: If the file proxy refuses to issue credentials,
            for example 403 without the ingest permission or 422 for an
            invalid ``location``.
        botocore.exceptions.ClientError: If S3 refuses a write for any reason
            other than an existing file.
    """
    local_path = Path(local_dir)
    if not local_path.exists():
        raise FileNotFoundError(local_dir)
    regex = re.compile(pattern or "")
    files = [
        f for f in iter_files(local_path) if regex.match(_relative_posix(f, local_path))
    ]

    body: dict[str, Any] = {"overwrite": overwrite}
    if location is not None:
        body["location"] = location
    issued = _issue_credentials(client, body)
    # Refresh with the issued location, which the platform created if omitted.
    body["location"] = issued["location"]
    s3 = _s3_client(client, issued, body)
    # Logged before the first write, so an interrupted upload can be resumed.
    logger.info(
        "uploading %s file(s) from %s to location %s",
        len(files),
        local_path,
        issued["location"],
    )

    uploaded = skipped = 0
    for index, file in enumerate(files, start=1):
        key = issued["prefix"] + _relative_posix(file, local_path)
        if _upload_file(s3, file, issued["bucket"], key, overwrite):
            uploaded += 1
        else:
            logger.debug("skipped %s: %s already exists", file, key)
            skipped += 1
        if on_file is not None:
            on_file(index, len(files), file)
    logger.info(
        "uploaded %s and skipped %s existing file(s) from %s to location %s",
        uploaded,
        skipped,
        local_path,
        issued["location"],
    )
    return issued["location"]


def _issue_credentials(client: PrescientClient, body: dict[str, Any]) -> dict:
    url = client.settings.prescient_endpoint_url.rstrip("/") + "/fileproxy/uploads"
    response = client.session.post(url, json=body, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _s3_client(client: PrescientClient, issued: dict, body: dict[str, Any]):
    """An S3 client whose credentials are issued again by the file proxy before
    they expire."""

    def metadata(credentials: dict) -> dict:
        return {
            "access_key": credentials["access_key_id"],
            "secret_key": credentials["secret_access_key"],
            "token": credentials["session_token"],
            "expiry_time": credentials["expiration"],
        }

    session = botocore.session.get_session()
    # botocore has no public setter for a session's credentials.
    session._credentials = RefreshableCredentials.create_from_metadata(
        metadata=metadata(issued),
        refresh_using=lambda: metadata(_issue_credentials(client, body)),
        method="prescient-fileproxy",
    )
    # The credentials cannot call HeadBucket, so botocore cannot find the
    # bucket's region by itself.
    return session.create_client("s3", region_name=issued["region"])


def _upload_file(s3, file: Path, bucket: str, key: str, overwrite: bool) -> bool:
    """Write one file. Returns False when it exists and ``overwrite`` is off."""
    condition = {} if overwrite else {"IfNoneMatch": "*"}
    size = file.stat().st_size
    try:
        if size <= _PART_SIZE:
            with open(file, "rb") as fh:
                s3.put_object(Bucket=bucket, Key=key, Body=fh, **condition)
        else:
            _upload_multipart(s3, file, size, bucket, key, condition)
    except ClientError as error:
        if not overwrite and error.response["Error"]["Code"] == "PreconditionFailed":
            return False
        raise
    return True


def _upload_multipart(s3, file: Path, size: int, bucket: str, key: str, condition):
    # The transfer manager cannot send If-None-Match on CompleteMultipartUpload,
    # so the parts are sent here.
    part_size = max(_PART_SIZE, -(-size // _MAX_PARTS))
    upload_id = s3.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]

    def send_part(number: int) -> dict:
        with open(file, "rb") as fh:
            fh.seek((number - 1) * part_size)
            data = fh.read(part_size)
        response = s3.upload_part(
            Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=number, Body=data
        )
        return {"ETag": response["ETag"], "PartNumber": number}

    with ThreadPoolExecutor(_PART_WORKERS) as pool:
        try:
            parts = list(pool.map(send_part, range(1, -(-size // part_size) + 1)))
            s3.complete_multipart_upload(
                Bucket=bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
                **condition,
            )
        except BaseException:
            # Don't send the parts still queued; S3 bills stored parts until aborted.
            pool.shutdown(cancel_futures=True)
            try:
                s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
            except ClientError as error:
                # Already gone: keep the original error, which may be a 412 skip.
                if error.response["Error"]["Code"] != "NoSuchUpload":
                    raise
            raise
