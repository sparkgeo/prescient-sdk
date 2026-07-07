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
from typing import Any

import yaml

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
            raise ValueError(
                    f"Ingestion spec must be bytes, got{type(spec).__name__}"
                    )
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
