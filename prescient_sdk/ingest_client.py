"""Client for the Prescient Ingest API."""

import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any

import requests

from prescient_sdk.client import PrescientClient
from prescient_sdk.ingest_models import (
    Batch,
    Error,
    Ingestion,
    InputFile,
    OutputFile,
    StacItem,
)

logger = logging.getLogger("prescient_sdk")

# Seconds to wait for the Ingest API; pass timeout= to a call to override it.
_REQUEST_TIMEOUT = 30


class IngestAPIError(requests.HTTPError):
    """The Ingest API answered with an error status.

    A subclass of ``requests.HTTPError``, so code that catches ``HTTPError``
    still catches it.

    Args:
        response (requests.Response): The error response.

    Attributes:
        status_code (int): The HTTP status code.
        detail (str): The server's error message, from the ``detail`` field of
            the JSON body, or the raw body when it is not JSON.
    """

    def __init__(self, response: requests.Response):
        self.status_code = response.status_code
        self.detail = _error_detail(response)
        method = response.request.method if response.request is not None else ""
        super().__init__(
            f"{response.status_code} {response.reason} for {method} {response.url}: "
            f"{self.detail}",
            response=response,
        )


class IngestSpecError(IngestAPIError):
    """The Ingest API rejected an ingestion spec (400 on create).

    Raised when the spec is invalid (for example a ``version`` that does not
    start with ``2.``, or a ``user`` field), or when an External bucket that a
    task writes to is not publicly readable. ``detail`` holds the server's
    reason.
    """


class CollectionOwnershipError(IngestAPIError):
    """The spec's STAC collection belongs to another Organization (409 on create)."""


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return detail if isinstance(detail, str) else json.dumps(detail)


class IngestClient:
    """Client for the Prescient Ingest API.

    Wraps the REST endpoints of the multi-tenant ingestion service and returns
    typed pydantic models. Every request goes through ``client.session``, which
    sends a fresh bearer token and retries once after a 401.

    The base URL is ``<prescient_endpoint_url>/ingest/``.

    Args:
        client (PrescientClient, optional): The client to send requests with.
            When None, a ``PrescientClient()`` is built from the default
            settings (environment variables and ``config.env``). Build a
            ``PrescientClient`` yourself to use other settings. Defaults to None.
        organization (str, optional): The Organization to act in. Only a super
            admin, whose token belongs to no Organization, needs it; it is sent
            as the ``organization`` query parameter on every request. Anyone
            else may only name their own Organization. Defaults to None.
    """

    def __init__(
        self,
        client: PrescientClient | None = None,
        organization: str | None = None,
    ):
        self._client = client if client is not None else PrescientClient()
        self.organization = organization

    @property
    def client(self) -> PrescientClient:
        """The :class:`PrescientClient` that requests are sent with.

        Returns:
            PrescientClient: The wrapped client instance.
        """
        return self._client

    @property
    def base_url(self) -> str:
        """Base URL for the Ingest API, with a trailing slash.

        Returns:
            str: ``<prescient_endpoint_url>/ingest/``.
        """
        return self._client.settings.prescient_endpoint_url.rstrip("/") + "/ingest/"

    def _url(self, path: str) -> str:
        return urllib.parse.urljoin(self.base_url, path.lstrip("/"))

    def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None, **kwargs
    ) -> requests.Response:
        # No Content-Type: requests sets multipart/form-data with its boundary
        # itself when create_ingestion passes files=.
        headers = {"Accept": "application/json", **kwargs.pop("headers", {})}
        kwargs.setdefault("timeout", _REQUEST_TIMEOUT)
        params = dict(params or {})
        if self.organization is not None:
            params["organization"] = self.organization
        url = self._url(path)
        logger.debug("_request method=%s path=%s", method, url)
        response = self._client.session.request(
            method, url, params=params or None, headers=headers, **kwargs
        )
        logger.debug(
            "_response method=%s path=%s status=%s", method, url, response.status_code
        )
        if response.status_code >= 400:
            raise IngestAPIError(response)
        return response

    # /v1/ingestion/

    def create_ingestion(self, spec_file: Path | str | bytes) -> Ingestion:
        """Create a new ingestion from a version 2 ingestion spec YAML.

        Args:
            spec_file (Path | str | bytes): The YAML spec. A ``Path`` or ``str``
                is a file path. ``bytes`` is sent as the file content; encode an
                in-memory string with ``.encode("utf-8")`` first.

        Returns:
            Ingestion: The new ingestion.

        Raises:
            IngestSpecError: If the API rejects the spec (400), for example a
                wrong ``version``, a ``user`` field, or an External destination
                that is not publicly readable.
            CollectionOwnershipError: If the spec's collection belongs to
                another Organization (409).
            IngestAPIError: For any other error response, for example 403 when
                the caller is not an admin of the Organization.
        """
        try:
            if isinstance(spec_file, bytes):
                files = {"spec_file": ("spec.yaml", spec_file, "application/yaml")}
                response = self._request("POST", "v1/ingestion/", files=files)
            else:
                path = Path(spec_file)
                with open(path, "rb") as fh:
                    files = {"spec_file": (path.name, fh, "application/yaml")}
                    response = self._request("POST", "v1/ingestion/", files=files)
        except IngestAPIError as e:
            if e.status_code == 400:
                raise IngestSpecError(e.response) from None
            if e.status_code == 409:
                raise CollectionOwnershipError(e.response) from None
            raise
        ingestion = Ingestion.model_validate(response.json())
        logger.info("Created ingestion id=%s", ingestion.id)
        return ingestion

    def list_ingestions(self, limit: int = 100, offset: int = 0) -> list[Ingestion]:
        """List the Organization's ingestions, newest first.

        Each ingestion's status is its latest batch's status as last recorded.
        Get the ingestion to bring a running batch's status up to date.

        Args:
            limit (int, optional): Most ingestions to return, 1 to 1000.
                Defaults to 100.
            offset (int, optional): Number of ingestions to skip. Defaults to 0.

        Returns:
            list[Ingestion]: One page of ingestions.
        """
        response = self._request(
            "GET", "v1/ingestion/", params={"limit": limit, "offset": offset}
        )
        return [Ingestion.model_validate(item) for item in response.json()]

    def get_ingestion(self, ingestion_id: int) -> Ingestion:
        """Get an ingestion by ID.

        Args:
            ingestion_id (int): The ingestion's server-assigned ID.

        Returns:
            Ingestion: The ingestion.
        """
        response = self._request("GET", f"v1/ingestion/{ingestion_id}")
        return Ingestion.model_validate(response.json())

    def start_ingestion(self, ingestion_id: int) -> Ingestion:
        """Start ingesting files for the latest batch, which must be ``READY``.

        If the launch takes longer than the server waits, the ingestion comes
        back still ``PLANNING``; poll it for the outcome.

        Args:
            ingestion_id (int): The ingestion to start.

        Returns:
            Ingestion: The ingestion after starting.
        """
        logger.info("Starting ingestion id=%s", ingestion_id)
        response = self._request("POST", f"v1/ingestion/{ingestion_id}/start")
        return Ingestion.model_validate(response.json())

    def get_ingestion_input_files(self, ingestion_id: int) -> list[InputFile]:
        """List the input files of an ingestion, across all batches.

        Args:
            ingestion_id (int): The ingestion to query.

        Returns:
            list[InputFile]: Input files across every batch.
        """
        response = self._request("GET", f"v1/ingestion/{ingestion_id}/input_files")
        return [InputFile.model_validate(item) for item in response.json()]

    def get_ingestion_output_files(self, ingestion_id: int) -> list[OutputFile]:
        """List the output files of an ingestion, across all batches.

        Args:
            ingestion_id (int): The ingestion to query.

        Returns:
            list[OutputFile]: Output files across every batch.
        """
        response = self._request("GET", f"v1/ingestion/{ingestion_id}/output_files")
        return [OutputFile.model_validate(item) for item in response.json()]

    def get_ingestion_stac_items(self, ingestion_id: int) -> list[StacItem]:
        """List the STAC items of an ingestion, across all batches.

        Args:
            ingestion_id (int): The ingestion to query.

        Returns:
            list[StacItem]: STAC items across every batch.
        """
        response = self._request("GET", f"v1/ingestion/{ingestion_id}/stac_items")
        return [StacItem.model_validate(item) for item in response.json()]

    def get_ingestion_errors(self, ingestion_id: int) -> list[Error]:
        """List the errors of an ingestion, across all batches.

        Args:
            ingestion_id (int): The ingestion to query.

        Returns:
            list[Error]: Errors recorded against this ingestion.
        """
        response = self._request("GET", f"v1/ingestion/{ingestion_id}/errors")
        return [Error.model_validate(item) for item in response.json()]

    # /v1/ingestion/{ingestion_id}/batches/...

    def list_batches(
        self, ingestion_id: int, limit: int = 100, offset: int = 0
    ) -> list[Batch]:
        """List the batches of an ingestion, newest first.

        Args:
            ingestion_id (int): The parent ingestion ID.
            limit (int, optional): Most batches to return, 1 to 1000.
                Defaults to 100.
            offset (int, optional): Number of batches to skip. Defaults to 0.

        Returns:
            list[Batch]: One page of batches.
        """
        response = self._request(
            "GET",
            f"v1/ingestion/{ingestion_id}/batches",
            params={"limit": limit, "offset": offset},
        )
        return [Batch.model_validate(item) for item in response.json()]

    def create_batch(self, ingestion_id: int) -> Batch:
        """Create a new batch and start scanning for input files.

        Args:
            ingestion_id (int): The parent ingestion ID.

        Returns:
            Batch: The new batch.
        """
        response = self._request("POST", f"v1/ingestion/{ingestion_id}/batches")
        batch = Batch.model_validate(response.json())
        logger.info(
            "Created batch ingestion=%s batch=%s", ingestion_id, batch.batch_number
        )
        return batch

    def get_batch(self, ingestion_id: int, batch_number: int) -> Batch:
        """Get one batch by its 1-based batch number.

        Args:
            ingestion_id (int): The parent ingestion ID.
            batch_number (int): 1-based batch number within the ingestion.

        Returns:
            Batch: The batch.
        """
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}"
        )
        return Batch.model_validate(response.json())

    def start_batch(self, ingestion_id: int, batch_number: int) -> Batch:
        """Start ingesting files for a batch, which must be ``READY``.

        If the launch takes longer than the server waits, the batch comes back
        still ``PLANNING``; poll it for the outcome.

        Args:
            ingestion_id (int): The parent ingestion ID.
            batch_number (int): 1-based batch number within the ingestion.

        Returns:
            Batch: The batch after starting.
        """
        logger.info("Starting batch ingestion=%s batch=%s", ingestion_id, batch_number)
        response = self._request(
            "POST", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/start"
        )
        return Batch.model_validate(response.json())

    def get_batch_input_files(
        self, ingestion_id: int, batch_number: int
    ) -> list[InputFile]:
        """List the input files of a batch.

        Args:
            ingestion_id (int): The parent ingestion ID.
            batch_number (int): 1-based batch number within the ingestion.

        Returns:
            list[InputFile]: Input files of this batch.
        """
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/input_files"
        )
        return [InputFile.model_validate(item) for item in response.json()]

    def get_batch_output_files(
        self, ingestion_id: int, batch_number: int
    ) -> list[OutputFile]:
        """List the output files of a batch.

        Args:
            ingestion_id (int): The parent ingestion ID.
            batch_number (int): 1-based batch number within the ingestion.

        Returns:
            list[OutputFile]: Output files of this batch.
        """
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/output_files"
        )
        return [OutputFile.model_validate(item) for item in response.json()]

    def get_batch_stac_items(
        self, ingestion_id: int, batch_number: int
    ) -> list[StacItem]:
        """List the STAC items of a batch.

        Args:
            ingestion_id (int): The parent ingestion ID.
            batch_number (int): 1-based batch number within the ingestion.

        Returns:
            list[StacItem]: STAC items of this batch.
        """
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/stac_items"
        )
        return [StacItem.model_validate(item) for item in response.json()]

    def get_batch_errors(self, ingestion_id: int, batch_number: int) -> list[Error]:
        """List the errors of a batch.

        Args:
            ingestion_id (int): The parent ingestion ID.
            batch_number (int): 1-based batch number within the ingestion.

        Returns:
            list[Error]: Errors recorded against this batch.
        """
        response = self._request(
            "GET", f"v1/ingestion/{ingestion_id}/batches/{batch_number}/errors"
        )
        return [Error.model_validate(item) for item in response.json()]

    # /healthz

    def check(self) -> bool:
        """Return ``True`` when the Ingest API answers 204 to ``/healthz``.

        Returns:
            bool: True if the health endpoint returned 204, False otherwise.
        """
        url = self._url("healthz")
        response = self._client.session.get(url, timeout=10)
        logger.debug("Health check %s -> %s", url, response.status_code)
        return response.status_code == 204
