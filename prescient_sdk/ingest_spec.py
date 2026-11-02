"""The :class:`IngestSpec` value object.

An :class:`IngestSpec` is a parsed version 2 ingestion spec (the YAML document
describing an ingestion's ``locations``, ``source_files``, ``tasks`` and STAC
metadata). It is the typed entry point for building an ingestion from Python.

A version 2 spec has ``version: "2.x"`` and no ``user`` field: the Organization
comes from the request. A location ``path`` is either a path in the
Organization bucket (no scheme, for example ``lidar/2026``) or the URL of an
External bucket (``s3://...``, or a public bucket's regional ``https://`` URL).

A spec authored locally may also point a location at a local directory, given
as a ``file://`` URL or an absolute path. Uploading those sources and rewriting
their paths (staging) is a separate step. This class carries the parsed spec,
serializes it for submission, and checks it for the problems the Ingest API
would reject, so callers can refuse to submit it.

`IngestSpec` is immutable: there are no methods that change a spec in place.
"""

import copy
import logging
import posixpath
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from prescient_sdk.upload import Uploader, upload_source_files

logger = logging.getLogger("prescient_sdk")

SPEC_VERSION_PREFIX = "2."

_URL_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_REGIONAL_HTTPS_URL = re.compile(
    r"https://[a-z0-9.-]+\.s3\.[a-z0-9-]+\.amazonaws\.com(/.*)?"
)
_WINDOWS_DRIVE = re.compile(r"[A-Za-z]:[\\/]")
# The Ingest API adds these areas to an Organization bucket path itself.
_ORGANIZATION_BUCKET_AREAS = ("uploads", "assets")


def _is_external(path: str) -> bool:
    """Whether ``path`` is an External bucket URL the Ingest API accepts."""
    return path.startswith("s3://") or _REGIONAL_HTTPS_URL.fullmatch(path) is not None


def _is_local(path: str) -> bool:
    """Whether ``path`` names a local directory rather than a bucket location.

    A ``file://`` URL, an absolute path, a home-relative path or a path with a
    ``..`` segment is local. The Ingest API rejects all of them. A relative
    path without a scheme is an Organization bucket path, so it is not local.
    """
    return (
        not path
        or path.startswith(("file://", "/", "\\", "~"))
        or _WINDOWS_DRIVE.match(path) is not None
        or ".." in path.replace("\\", "/").split("/")
    )


def _organization_bucket_path_problem(path: str) -> str | None:
    """Why the Ingest API would reject ``path`` as an Organization bucket path.

    Mirrors the service's checks: no leading ``/``, no ``..`` segment, and no
    leading ``uploads/`` or ``assets/``, which the platform adds itself.

    Returns:
        str | None: The reason, or None when the path is acceptable.
    """
    if path.startswith("/"):
        return "must not start with /"
    if ".." in path.split("/"):
        return 'must not contain a ".." segment'
    if posixpath.normpath(path).split("/")[0] in _ORGANIZATION_BUCKET_AREAS:
        return 'must not start with "uploads/" or "assets/": the platform adds them'
    return None


class IngestSpec:
    """A parsed version 2 ingestion spec.

    Construct via :meth:`from_file` or :meth:`from_dict` so the parse step is
    visible at the call site. Use :meth:`to_bytes` to serialize the spec for
    submission, :meth:`local_locations` to check whether any location still
    points at a local directory, and :meth:`problems` for every problem the SDK
    can find before submitting.

    Example::

        spec = IngestSpec.from_file("spec.yaml")
        if spec.problems():
            raise RuntimeError(spec.problems())
        ing = IngestResource.create(client, spec)
    """

    def __init__(self, spec: dict[str, Any]):
        self._spec = spec

    @classmethod
    def from_file(cls, path: Path | str) -> "IngestSpec":
        """Parse an ingestion specification from a YAML file.

        Args:
            path (Path | str): Path to the spec YAML file.

        Returns:
            IngestSpec: The parsed spec.

        Raises:
            FileNotFoundError: If ``path`` does not exist.
            ValueError: If the file does not contain a YAML mapping.
        """
        path = Path(path)
        with open(path) as fh:
            parsed = yaml.safe_load(fh)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Ingestion spec at {path} must be a YAML mapping, got {type(parsed).__name__}"
            )
        logger.debug("Parsed ingestion spec from %s", path)
        return cls(parsed)

    @classmethod
    def from_dict(cls, spec: dict[str, Any]) -> "IngestSpec":
        """Wrap an already-parsed spec dict.

        The dict is copied, so later mutations of the caller's dict do not affect
        this spec.

        Args:
            spec (dict[str, Any]): The ingestion specification.

        Returns:
            IngestSpec: The wrapped spec.

        Raises:
            ValueError: If ``spec`` is not a mapping.
        """
        if not isinstance(spec, dict):
            raise ValueError(
                f"Ingestion spec must be a mapping, got {type(spec).__name__}"
            )
        return cls(copy.deepcopy(spec))

    @classmethod
    def from_bytes(cls, spec: bytes) -> "IngestSpec":
        """Parse an ingestion spec from YAML bytes.

        Args:
            spec (bytes): The UTF-8 encoded YAML document.

        Returns:
            IngestSpec: The parsed spec.

        Raises:
            ValueError: If ``spec`` is not bytes or not a YAML mapping.
        """
        if not isinstance(spec, bytes):
            raise ValueError(f"Ingestion spec must be bytes, got {type(spec).__name__}")
        parsed = yaml.safe_load(spec)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Ingestion spec must be a YAML mapping, got {type(parsed).__name__}"
            )
        return cls(parsed)

    @property
    def spec(self) -> dict[str, Any]:
        """A deep copy of the parsed spec.

        A copy is returned so callers cannot mutate the spec through this
        accessor; :class:`IngestSpec` is immutable.

        Returns:
            dict[str, Any]: A copy of the spec.
        """
        return copy.deepcopy(self._spec)

    def to_bytes(self) -> bytes:
        """Serialize the spec back to YAML bytes for submission.

        Key order is preserved so the serialized form matches the authored spec.

        Returns:
            bytes: The UTF-8 encoded YAML document, suitable for
            :meth:`prescient_sdk.ingest_client.IngestClient.create_ingestion`.
        """
        return yaml.safe_dump(self._spec, sort_keys=False).encode("utf-8")

    def local_locations(self) -> list[str]:
        """Return the names of locations whose path is a local directory.

        A ``file://`` URL, an absolute path, a home-relative path, a path with
        a ``..`` segment, or a missing ``path`` is local. The Ingest API cannot
        read any of them, so a non-empty result means the spec is not ready to
        submit: upload those sources and rewrite their paths first (see
        :meth:`with_uploaded_sources`).

        A relative path without a scheme (for example ``lidar/2026``) is a path
        in the Organization bucket, not a local directory.

        Returns:
            list[str]: Names of local locations, in spec order.
        """
        locations = self._spec.get("locations") or {}
        return [
            name
            for name, location in locations.items()
            if _is_local(str((location or {}).get("path", "")))
        ]

    def problems(self) -> list[str]:
        """Return the reasons the Ingest API would reject this spec as version 2.

        Checks only what the SDK can check without the server: ``version`` is a
        string that starts with ``2.``, there is no ``user`` field, no location
        is a local directory, and ``credentials: true`` is set only on External
        bucket locations. The server validates the rest.

        Returns:
            list[str]: One message per problem; empty when none were found.
        """
        problems = []
        version = self._spec.get("version")
        if not isinstance(version, str) or not version.startswith(SPEC_VERSION_PREFIX):
            problems.append(
                f'"version" must be a string that starts with "{SPEC_VERSION_PREFIX}", '
                f'for example "2.0.0" (quote it in YAML); got {version!r}'
            )
        if "user" in self._spec:
            problems.append(
                '"user" is not allowed in a version 2 spec: the Organization comes '
                "from the request"
            )
        local = self.local_locations()
        if local:
            problems.append(
                f"these locations are local directories and must be uploaded first: "
                f"{local}"
            )
        for name, location in (self._spec.get("locations") or {}).items():
            location = location or {}
            if location.get("credentials") is True and not _is_external(
                str(location.get("path", ""))
            ):
                problems.append(
                    f'location {name!r}: "credentials" is only for an External bucket '
                    "(s3:// path)"
                )
        return problems

    def with_uploaded_sources(
        self,
        source_file_sets: list[str],
        *,
        uploader: Uploader,
        dest_prefix: str,
        console: Any = None,
    ) -> "IngestSpec":
        """Upload local sources and return a new :class:`IngestSpec` that points at them.

        For each named source file set, this sends the local files its
        ``pattern`` selects to ``uploader`` (via
        :func:`prescient_sdk.upload.upload_source_files`) and rewrites that
        set's location ``path`` to the destination prefix the files were
        uploaded under.

        A single ``uuid4`` destination is computed per *distinct* location
        (``{dest_prefix}/{uuid4}/``), so several sets that reference the same
        location share one destination and that location's ``path`` is
        rewritten exactly once. A file matched by two staged sets sharing a
        location is uploaded once per set.

        The original :class:`IngestSpec` is left untouched — staging returns a
        new instance.

        The SDK does not ship an uploader. The caller supplies one, and the
        destination prefix it writes under. ``dest_prefix`` is usually a path in
        the Organization bucket, such as ``sdk-uploads``. The Ingest API reads
        an Organization bucket source location under ``uploads/``, so the
        uploader must write each ``destination`` under ``uploads/`` in the
        Organization bucket. An ``s3://`` prefix names an External bucket, which
        the uploader writes to directly.

        Example::

            spec = IngestSpec.from_file("spec.yaml")
            ready = spec.with_uploaded_sources(
                ["image_files", "thumbnail_files"],
                uploader=my_uploader,
                dest_prefix="sdk-uploads",
            )
            ing = IngestResource.create(client, ready)

        Args:
            source_file_sets (list[str]): Names of the ``source_files`` entries
                to stage.
            uploader (Uploader): Called as ``uploader(local_file, destination)``
                for each selected file. See :data:`prescient_sdk.upload.Uploader`.
            dest_prefix (str): Prefix that staged locations are rewritten to,
                with one ``uuid4`` segment per location appended: an
                Organization bucket path (no scheme, not starting with ``/``,
                ``uploads/`` or ``assets/``) or an ``s3://`` URL.
            console: Optional Rich ``Console`` to render upload progress to;
                defaults to Rich's standard console.

        Returns:
            IngestSpec: A new spec whose staged locations point at
            ``{dest_prefix}/{uuid4}/``.

        Raises:
            ValueError: If ``dest_prefix`` is empty or not a valid location
                path, a named set or its location is missing, or a referenced
                location is already an External bucket URL.
        """
        if not dest_prefix:
            raise ValueError("dest_prefix must not be empty")
        if not dest_prefix.startswith("s3://"):
            if _URL_SCHEME.match(dest_prefix):
                raise ValueError(
                    f"dest_prefix {dest_prefix!r} must be an Organization bucket "
                    "path or an s3:// URL"
                )
            problem = _organization_bucket_path_problem(dest_prefix)
            if problem:
                raise ValueError(f"dest_prefix {dest_prefix!r} {problem}")
        dest_root = dest_prefix.rstrip("/")

        spec = copy.deepcopy(self._spec)
        locations = spec.get("locations", {})
        file_sets = spec.get("source_files", {})

        # Resolve and validate every named set up front so a bad name fails
        # before any files are uploaded, and compute one destination prefix per
        # distinct location.
        location_dest: dict[str, str] = {}
        resolved: list[tuple[str, str, str, str]] = []
        for set_name in source_file_sets:
            if set_name not in file_sets:
                raise ValueError(f"source file set {set_name!r} not found in spec")
            location_name = (file_sets[set_name] or {}).get("location")
            if location_name not in locations:
                raise ValueError(
                    f"location {location_name!r} referenced by source file set "
                    f"{set_name!r} not found in spec"
                )
            raw_path = str((locations[location_name] or {}).get("path", ""))
            if _is_external(raw_path):
                raise ValueError(
                    f"location {location_name!r} is already an External bucket "
                    f"URL ({raw_path!r}); nothing to stage"
                )
            local_path = (
                raw_path[len("file://") :]
                if raw_path.startswith("file://")
                else raw_path
            )

            if location_name not in location_dest:
                location_dest[location_name] = f"{dest_root}/{uuid4()}/"

            pattern = (file_sets[set_name] or {}).get("pattern", ".*")
            resolved.append((set_name, location_name, local_path, pattern))

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            for set_name, location_name, local_path, pattern in resolved:
                dest_prefix = location_dest[location_name]
                task_id = progress.add_task(f"staging {set_name}", total=None)

                def on_file(index, total, path, task_id=task_id):
                    progress.update(task_id, total=total, completed=index)

                upload_source_files(
                    local_path, dest_prefix, pattern, uploader, on_file=on_file
                )

        for location_name, dest_prefix in location_dest.items():
            if locations[location_name] is None:
                locations[location_name] = {}
            locations[location_name]["path"] = dest_prefix

        return IngestSpec(spec)
