"""Client for the Prescient Ingest API."""

from __future__ import annotations

import time
import urllib.parse
from pathlib import Path
from typing import Iterable

import requests

from prescient_sdk.client import PrescientClient
from prescient_sdk.config import Settings
from prescient_sdk.ingest_models import (
    TERMINAL_STATUSES,
    Batch,
    Error,
    Ingestion,
    InputFile,
    OutputFile,
    Status,
)


class IngestClient:
    """Client for interacting with the Prescient Ingest API.

    Wraps the REST endpoints described in the Ingest API OpenAPI spec and
    returns typed pydantic models. Auth is delegated to a
    :class:`PrescientClient` (constructed automatically if one is not
    supplied) so the SDK's OAuth2 token handling is reused.

    The base URL is taken from ``Settings.prescient_ingest_endpoint_url``
    when set, otherwise falls back to ``Settings.prescient_endpoint_url``.

    Args:
        prescient_client: An existing PrescientClient to use for auth. When
            provided, ``env_file`` and ``settings`` must be omitted.
        env_file: Optional path to a configuration file. Forwarded to
            ``PrescientClient`` when ``prescient_client`` is not supplied.
        settings: Optional Settings object. Forwarded to ``PrescientClient``
            when ``prescient_client`` is not supplied.

    Raises:
        ValueError: If ``prescient_client`` is provided alongside
            ``env_file`` or ``settings``.
    """

    def __init__(
        self,
        prescient_client: PrescientClient | None = None,
        env_file: str | Path | None = None,
        settings: Settings | None = None,
    ):
        if prescient_client is not None and (env_file or settings):
            raise ValueError(
                "Cannot provide prescient_client alongside env_file or settings"
            )
        if env_file and settings:
            raise ValueError("Cannot provide both env_file and settings")
        if prescient_client is None:
            if env_file:
                prescient_client = PrescientClient(env_file=env_file)
            elif settings:
                prescient_client = PrescientClient(settings=settings)
            else:
                prescient_client = PrescientClient()
        self._client = prescient_client

    @property
    def client(self) -> PrescientClient:
        """The underlying :class:`PrescientClient` used for auth."""
        return self._client

    @property
    def base_url(self) -> str:
        """Base URL for the Ingest API, with a guaranteed trailing slash.

        Uses ``prescient_ingest_endpoint_url`` when set; otherwise falls back
        to ``<prescient_endpoint_url>/ingest/``.
        """
        override = self._client.settings.prescient_ingest_endpoint_url
        if override:
            return override if override.endswith("/") else override + "/"
        base = self._client.settings.prescient_endpoint_url
        if not base.endswith("/"):
            base = base + "/"
        return urllib.parse.urljoin(base, "ingest/")

    @property
    def headers(self) -> dict:
        """Default request headers for the Ingest API.

        Returns ``Accept: application/json`` only. ``Content-Type`` is
        omitted so ``requests`` can set ``multipart/form-data; boundary=...``
        itself on the upload path in ``create_ingestion``.

        Note: this deliberately does NOT delegate to ``PrescientClient.headers``,
        because that would trigger an OAuth sign-in via the
        ``auth_credentials`` property. The Ingest API is reached over a
        port-forward and does not require a bearer token from the SDK.
        """
        return {"Accept": "application/json"}

    def _url(self, path: str) -> str:
        return urllib.parse.urljoin(self.base_url, path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        # Allow callers to override or extend headers via kwargs without
        # colliding with the default headers= passed below.
        headers = {**self.headers, **kwargs.pop("headers", {})}
        print(
            f"_request: method={method} path={self._url(path)} headers={headers} kwargs={kwargs}"
        )
        response = requests.request(method, self._url(path), headers=headers, **kwargs)
        response.raise_for_status()
        return response

    # /v1/ingestion/

    def create_ingestion(self, spec_file: Path | str | bytes) -> Ingestion:
        """Create a new ingestion from an ingestion specification YAML.

        Args:
            spec_file: The YAML specification. A ``Path`` or ``str`` is
                treated as a file path and opened in binary mode. ``bytes``
                is posted directly as the file content. Callers with the
                spec as an in-memory string should ``.encode("utf-8")`` it
                first.
        """
        # Multipart upload: do NOT set Content-Type ourselves — requests
        # sets `multipart/form-data; boundary=...` with the right boundary
        # parameter once `files=` is provided. `self.headers` deliberately
        # omits Content-Type so _request doesn't override that.
        t_start = time.perf_counter()

        if isinstance(spec_file, bytes):
            files = {"spec_file": ("spec.yaml", spec_file, "application/yaml")}
            t_request = time.perf_counter()
            response = self._request("POST", "v1/ingestion/", files=files)
            t_response = time.perf_counter()
            print(
                f"create_ingestion: request={t_response - t_request:.3f}s "
                f"(bytes payload, {len(spec_file)} bytes)"
            )
        else:
            path = Path(spec_file)
            t_open = time.perf_counter()
            with open(path, "rb") as fh:
                files = {"spec_file": (path.name, fh, "application/yaml")}
                t_request = time.perf_counter()
                response = self._request("POST", "v1/ingestion/", files=files)
                t_response = time.perf_counter()
            print(
                f"create_ingestion: open={t_request - t_open:.3f}s "
                f"request={t_response - t_request:.3f}s "
                f"(file={path})"
            )

        t_parse_start = time.perf_counter()
        result = Ingestion.model_validate(response.json())
        t_end = time.perf_counter()
        print(
            f"create_ingestion: parse={t_end - t_parse_start:.3f}s "
            f"total={t_end - t_start:.3f}s"
        )
        return result

    def get_ingestion(self, ingestion_id: int) -> Ingestion:
        """Get ingestion by ID."""
        response = self._request("GET", f"v1/ingestion/{ingestion_id}")
        return Ingestion.model_validate(response.json())

    def start_ingestion(self, ingestion_id: int) -> Ingestion:
        """Start ingesting files for the latest batch (must be ``READY``)."""
        response = self._request("POST", f"v1/ingestion/{ingestion_id}/start")
        return Ingestion.model_validate(response.json())

    def get_ingestion_input_files(self, ingestion_id: int) -> list[InputFile]:
        """List all input files for an ingestion across all batches."""
        response = self._request("GET", f"v1/ingestion/{ingestion_id}/input_files")
        return [InputFile.model_validate(item) for item in response.json()]

    def get_ingestion_output_files(self, ingestion_id: int) -> list[OutputFile]:
        """List all output files for an ingestion across all batches."""
        response = self._request("GET", f"v1/ingestion/{ingestion_id}/output_files")
        return [OutputFile.model_validate(item) for item in response.json()]

    def get_ingestion_errors(self, ingestion_id: int) -> list[Error]:
        """Get all errors associated with an ingestion across all batches."""
        response = self._request("GET", f"v1/ingestion/{ingestion_id}/errors")
        return [Error.model_validate(item) for item in response.json()]

    # /v1/ingestion/{ingestion_id}/batches/...

    def list_batches(self, ingestion_id: int) -> list[Batch]:
        """List all batches for an ingestion."""
        response = self._request("GET", f"v1/ingestion/{ingestion_id}/batches")
        return [Batch.model_validate(item) for item in response.json()]

    def create_batch(self, ingestion_id: int) -> Batch:
        """Create a new ingestion batch and start scanning for input files."""
        response = self._request("POST", f"v1/ingestion/{ingestion_id}/batches")
        return Batch.model_validate(response.json())

    def get_batch(self, ingestion_id: int, batch_number: int) -> Batch:
        """Get information on a single batch by its 1-based batch number."""
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}"
        )
        return Batch.model_validate(response.json())

    def start_batch(self, ingestion_id: int, batch_number: int) -> Batch:
        """Start ingesting files for a specific batch (must be ``READY``)."""
        response = self._request(
            "POST", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/start"
        )
        return Batch.model_validate(response.json())

    def get_batch_input_files(
        self, ingestion_id: int, batch_number: int
    ) -> list[InputFile]:
        """List input files for a specific batch."""
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/input_files"
        )
        return [InputFile.model_validate(item) for item in response.json()]

    def get_batch_output_files(
        self, ingestion_id: int, batch_number: int
    ) -> list[OutputFile]:
        """List output files for a specific batch."""
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/output_files"
        )
        return [OutputFile.model_validate(item) for item in response.json()]

    def get_batch_errors(self, ingestion_id: int, batch_number: int) -> list[Error]:
        """Get all errors associated with a specific batch."""
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/errors"
        )
        return [Error.model_validate(item) for item in response.json()]

    # /healthy

    def check(self) -> bool:
        """Return ``True`` when the Ingest API responds 204 to ``/healthy``."""
        response = requests.get(self._url("healthy"), timeout=10)
        if (
            not self.client.settings.prescient_ingest_endpoint_url
            and response.status_code != 204
        ):
            print("Ingest API not available, or PRESCIENT_INGEST_ENDPOINT_URL not set")
        return response.status_code == 204

    # Workflow helper

    def wait_for_status(
        self,
        ingestion_id: int,
        batch_number: int | None = None,
        target_statuses: Iterable[Status] = TERMINAL_STATUSES,
        poll_interval: float = 5.0,
        timeout: float = 300.0,
    ) -> Ingestion | Batch:
        """Poll until the ingestion or batch reaches one of ``target_statuses``.

        Polls :meth:`get_ingestion` (or :meth:`get_batch` when
        ``batch_number`` is provided) every ``poll_interval`` seconds until
        the returned ``status`` is in ``target_statuses`` or ``timeout``
        seconds have elapsed.

        Args:
            ingestion_id: The ingestion to poll.
            batch_number: If given, poll the specific batch rather than the
                top-level ingestion.
            target_statuses: Statuses that end the wait. Defaults to the
                terminal/decision states ``READY``, ``DONE``, ``FAILED``,
                and ``INCOMPLETE``.
            poll_interval: Seconds between polls.
            timeout: Total seconds to wait before raising.

        Returns:
            The ``Ingestion`` or ``Batch`` once it reaches a target status.

        Raises:
            TimeoutError: If ``timeout`` elapses before reaching a target
                status.
        """
        targets = set(target_statuses)
        deadline = time.monotonic() + timeout
        while True:
            if batch_number is None:
                obj: Ingestion | Batch = self.get_ingestion(ingestion_id)
            else:
                obj = self.get_batch(ingestion_id, batch_number)
            print(obj.status)
            if obj.status in targets:
                return obj
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Status {obj.status.value!r} did not reach "
                    f"{sorted(s.value for s in targets)} within {timeout}s"
                )
            time.sleep(poll_interval)
