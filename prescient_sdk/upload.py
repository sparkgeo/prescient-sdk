"""Select local files for upload and hand each one to a caller-supplied uploader.

The SDK does not ship an uploader. The caller passes an :data:`Uploader` that
writes one file to one destination, so the transport (for example a fileproxy
upload) can change without changing file selection.
"""

import logging
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path, PurePath

logger = logging.getLogger(__name__)

Uploader = Callable[[Path, str], None]
"""Upload one local file to one destination.

Called as ``uploader(local_file, destination)``. ``local_file`` is the path of
an existing local file. ``destination`` is the full destination string: the
caller's destination prefix followed by the file's forward-slash path relative
to the source directory (for example ``"<prefix>/<uuid>/nested/a.tif"``). The
uploader decides how to write it, and whether to skip or overwrite a file that
already exists. It raises to stop the upload.
"""


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

    ``as_posix`` normalizes separators so destinations and pattern matching are
    identical on Windows and POSIX — e.g. a Windows ``nested\\image.tif``
    becomes ``nested/image.tif``. The local OS separator must never leak into a
    destination.

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
    uploader: Uploader,
    on_file: Callable[[int, int, Path], None] | None = None,
) -> None:
    """Upload the files under ``local_dir`` that a source file set's pattern selects.

    Only files whose path *relative to* ``local_dir`` matches ``pattern`` are
    uploaded, and each is sent to ``dest_prefix`` + that same relative path —
    verbatim, with no directory-name segment injected. This preserves every
    file's path relative to its location, so the spec's ``pattern`` still matches
    after the files move (the Ingest API strips the location prefix and applies
    ``re.match`` to the remaining relative path).

    ``pattern`` is applied with ``re.match`` (anchored at the start of the
    relative path), matching the Ingest API's own file selection.

    Example::

        upload_source_files("/data/scenes", "<prefix>/3f9.../", r".*\\.tif$", uploader)

    Args:
        local_dir (str | os.PathLike): Local directory to scan recursively.
        dest_prefix (str): Destination prefix. Each destination is
            ``dest_prefix`` joined with a file's relative path; a ``/`` is
            added to the prefix if it does not end with one.
        pattern (str): Regex applied (``re.match``) to each file's posix path
            relative to ``local_dir``.
        uploader (Uploader): Called once per selected file with
            ``(local_file, destination)``.
        on_file (Callable[[int, int, Path], None], optional): Called after each
            upload with ``(index, total, path)`` where ``index`` is 1-based.
            Useful for progress display. Defaults to None.

    Raises:
        FileNotFoundError: If ``local_dir`` does not exist.
    """
    local_path = Path(local_dir)
    if not local_path.exists():
        raise FileNotFoundError(local_dir)

    if dest_prefix and not dest_prefix.endswith("/"):
        dest_prefix += "/"
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
        destination = dest_prefix + _relative_posix(file, local_path)
        logger.info("uploading file %s to %s", file, destination)
        uploader(file, destination)
        if on_file is not None:
            on_file(index, total, file)
