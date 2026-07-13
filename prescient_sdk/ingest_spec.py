"""The :class:`IngestSpec` value object.

An :class:`IngestSpec` is a parsed ingestion specification (the YAML document
describing an ingestion's ``locations``, ``source_files``, ``tasks`` and STAC
metadata). It is the typed entry point for building an ingestion from Python.

The Ingest API only accepts ``s3://`` location paths. A spec authored locally may
still point a location at a local directory; uploading those sources and
rewriting their paths (staging) is a separate step. This class carries the parsed
spec, serializes it for submission, and can report which locations are still
local so callers can refuse to submit an unstaged spec.

`IngestSpec` is immutable: there are no methods that change a spec in place.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Union
from uuid import uuid4

import yaml
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from prescient_sdk.client import PrescientClient
from prescient_sdk.ingest_client import IngestClient
from prescient_sdk.upload import upload_source_files

logger = logging.getLogger("prescient_sdk")


class IngestSpec:
    """A parsed ingestion specification.

    Construct via :meth:`from_file` or :meth:`from_dict` so the parse step is
    visible at the call site. Use :meth:`to_bytes` to serialize the spec for
    submission, and :meth:`local_locations` to check whether any location still
    points at a local (non-``s3://``) path.

    Example::

        spec = IngestSpec.from_file("spec.yaml")
        if spec.local_locations():
            raise RuntimeError("upload local sources before ingesting")
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
        """IngestSpec from bytes"""
        if not isinstance(spec, bytes):
            raise ValueError(f"Ingestion spec must be bytes, got{type(spec).__name__}")
        return cls(yaml.safe_load(spec))

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
        """Return the names of locations whose path is not an ``s3://`` URI.

        The Ingest API only reads ``s3://`` locations, so a non-empty result
        means the spec is not ready to submit (its local sources must be uploaded
        and their paths rewritten first). A location with no ``path`` is also
        reported, since it cannot be read either.

        Returns:
            list[str]: Location names with a non-``s3://`` path, in spec order.
        """
        locations = {} if self._spec is None else self._spec.get("locations", {})
        return [
            name
            for name, location in locations.items()
            if not str((location or {}).get("path", "")).startswith("s3://")
        ]

    def with_uploaded_sources(
        self,
        client: Union[PrescientClient, IngestClient],
        source_file_sets: list[str],
        *,
        console: Any = None,
    ) -> "IngestSpec":
        """Stage local sources and return a new, s3-only :class:`IngestSpec`.

        For each named source file set, this uploads the local files its
        ``pattern`` selects (via
        :func:`prescient_sdk.upload.upload_source_files`) to the upload bucket
        and rewrites that set's location ``path`` to the S3 prefix the files
        were uploaded under.

        A single ``uuid4`` destination prefix is computed per *distinct*
        location (``s3://{upload_bucket}/{upload_prefix}/{uuid4}/``), so several
        sets that reference the same location share one destination and that
        location's ``path`` is rewritten exactly once. A file matched by two
        staged sets sharing a location is uploaded once per set (an idempotent
        overwrite).

        The original :class:`IngestSpec` is left untouched — staging returns a
        new instance whose staged locations are now ``s3://`` URIs.

        The upload uses ``client.upload_session``, whose credentials come from
        either STS ``assume_role_with_web_identity`` (when ``prescient_upload_role``
        is set and an api key is not) or the API's ``/fileproxy/credentials``
        endpoint (when an api key is set).

        Example::

            spec = IngestSpec.from_file("spec.yaml")
            ready = spec.with_uploaded_sources(
                client, source_file_sets=["image_files", "thumbnail_files"]
            )
            ing = IngestResource.create(client, ready)

        Args:
            client (PrescientClient | IngestClient): Provides the STS upload
                session and upload-bucket configuration. An ``IngestClient`` is
                normalized to its underlying ``PrescientClient``.
            source_file_sets (list[str]): Names of the ``source_files`` entries
                to stage.
            console: Optional Rich ``Console`` to render upload progress to;
                defaults to Rich's standard console.

        Returns:
            IngestSpec: A new spec whose staged locations point at ``s3://``.

        Raises:
            TypeError: If ``client`` is neither a ``PrescientClient`` nor an
                ``IngestClient``.
            ValueError: If ``prescient_upload_bucket`` is not configured, a named
                set or its location is missing, or a referenced location is
                already an ``s3://`` path.
        """
        if isinstance(client, PrescientClient):
            prescient_client = client
        elif isinstance(client, IngestClient):
            prescient_client = client.client
        else:
            raise TypeError(
                "client must be a PrescientClient or IngestClient, got "
                f"{type(client).__name__}"
            )

        bucket = prescient_client.settings.prescient_upload_bucket
        if not bucket:
            raise ValueError(
                "prescient_upload_bucket is not configured; set "
                "PRESCIENT_UPLOAD_BUCKET to stage source files."
            )
        prefix = prescient_client.settings.prescient_upload_prefix

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
            if raw_path.startswith("s3://"):
                raise ValueError(
                    f"location {location_name!r} is already an s3:// path "
                    f"({raw_path!r}); nothing to stage"
                )
            local_path = (
                raw_path[len("file://") :]
                if raw_path.startswith("file://")
                else raw_path
            )

            if location_name not in location_dest:
                key_prefix = f"{prefix}/{uuid4()}" if prefix else str(uuid4())
                location_dest[location_name] = f"s3://{bucket}/{key_prefix}/"

            pattern = (file_sets[set_name] or {}).get("pattern", ".*")
            resolved.append((set_name, location_name, local_path, pattern))

        session = prescient_client.upload_session
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
                    local_path, dest_prefix, pattern, session, on_file=on_file
                )

        for location_name, dest_prefix in location_dest.items():
            locations[location_name]["path"] = dest_prefix

        return IngestSpec(spec)
