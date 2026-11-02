"""Tests for IngestClient against the MT ingestion API.

Requests go through the real ``client.session``; only the HTTP adapter's
``send`` is replaced, so no test reaches the network.
"""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from pytest_mock import MockerFixture

from prescient_sdk.client import PrescientClient
from prescient_sdk.config import Settings
from prescient_sdk.ingest_client import (
    CollectionOwnershipError,
    IngestAPIError,
    IngestClient,
    IngestSpecError,
)
from prescient_sdk.ingest_models import (
    Batch,
    Error,
    ErrorSeverity,
    FileStatus,
    Ingestion,
    InputFile,
    OutputFile,
    StacItem,
    Status,
)

# ---------------------------------------------------------------------------
# Test data, shaped like prescient.ingestion.schemas in the MT service
# ---------------------------------------------------------------------------

BASE = "https://example.server.prescient.earth/ingest/"
NOW_ISO = "2026-01-01T00:00:00Z"
ITEM_ID = "my-item-0001"

INGESTION_PAYLOAD = {
    "id": 42,
    "status": "READY",
    "spec": {"version": "2.0.0", "locations": {"raw": {"path": "lidar/2026"}}},
}

BATCH_PAYLOAD = {
    "id": 1,
    "ingestion_id": 42,
    "batch_number": 1,
    "created": NOW_ISO,
    "started": None,
    "finalized": None,
    "status": "SCANNING",
}

INPUT_FILE_PAYLOAD = {
    "location": "raw",
    "source_file_set": "fileset_a",
    "path": "data/file.tif",
    "last_modified": NOW_ISO,
    "stac_item_id": ITEM_ID,
}

OUTPUT_FILE_PAYLOAD = {
    "stac_item_id": ITEM_ID,
    "task_name": "transform_main",
    "status": "DONE",
    "path": "assets/lidar/2026/file.tif",
}

STAC_ITEM_PAYLOAD = {"stac_item_id": ITEM_ID, "status": "PENDING"}

ERROR_PAYLOAD = {
    "severity": "WARNING",
    "time_occurred": NOW_ISO,
    "description": "minor issue",
    "ingestion_id": 42,
    "location": None,
    "task": None,
    "input_file": None,
    "stack_trace": None,
}

V2_SPEC = b'version: "2.0.0"\nlocations:\n  raw:\n    path: lidar/2026\n'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeHTTP:
    """Stands in for ``HTTPAdapter.send``: records requests, replays responses."""

    def __init__(self):
        self.requests: list[requests.PreparedRequest] = []
        self._responses: list[tuple[int, object]] = []

    def respond(self, status: int = 200, body: object = None) -> "FakeHTTP":
        self._responses.append((status, body))
        return self

    def send(self, adapter, request, **kwargs) -> requests.Response:
        self.requests.append(request)
        status, body = self._responses.pop(0) if self._responses else (200, None)
        response = requests.Response()
        response.status_code = status
        response.reason = "Reason"
        response.url = request.url
        response.request = request
        if isinstance(body, str):
            response._content = body.encode()
        elif body is not None:
            response._content = json.dumps(body).encode()
            response.headers["Content-Type"] = "application/json"
        else:
            response._content = b""
        return response

    @property
    def last(self) -> requests.PreparedRequest:
        return self.requests[-1]


@pytest.fixture
def mock_creds(mocker: MockerFixture, set_env_vars, monkeypatch):
    """Short-circuit the API key exchange so no test reaches Keycloak."""
    monkeypatch.setenv(
        "PRESCIENT_ENDPOINT_URL", "https://example.server.prescient.earth"
    )
    mocker.patch(
        "prescient_sdk.client.PrescientClient._access_token",
        return_value="mock_token",
    )


@pytest.fixture
def http(mocker: MockerFixture) -> FakeHTTP:
    fake = FakeHTTP()
    mocker.patch(
        "requests.adapters.HTTPAdapter.send", autospec=True, side_effect=fake.send
    )
    # Bare requests.* calls would bypass client.session; make them fail loudly.
    for name in ("request", "get", "post"):
        mocker.patch(
            f"requests.{name}", side_effect=AssertionError(f"requests.{name} used")
        )
    return fake


@pytest.fixture
def ingest_client(mock_creds) -> IngestClient:
    return IngestClient()


def _path(request: requests.PreparedRequest) -> str:
    return urlsplit(request.url).path


def _query(request: requests.PreparedRequest) -> dict[str, list[str]]:
    return parse_qs(urlsplit(request.url).query)


# ---------------------------------------------------------------------------
# Initialization & URL handling
# ---------------------------------------------------------------------------


def test_ingest_client_default_init_builds_prescient_client(mock_creds):
    client = IngestClient()
    assert isinstance(client.client, PrescientClient)
    assert client.organization is None


def test_ingest_client_accepts_prescient_client(mock_creds):
    pc = PrescientClient()
    assert IngestClient(pc).client is pc
    assert IngestClient(client=pc).client is pc


def test_base_url_is_endpoint_ingest(ingest_client: IngestClient):
    assert ingest_client.base_url == BASE


def test_base_url_keeps_endpoint_path(mock_creds):
    settings = Settings(  # type: ignore[call-arg]
        prescient_endpoint_url="https://example.com/some/path/",
        prescient_api_key="pk_test",
    )
    client = IngestClient(PrescientClient(settings=settings))
    assert client.base_url == "https://example.com/some/path/ingest/"


# ---------------------------------------------------------------------------
# Every call goes through client.session
# ---------------------------------------------------------------------------


ALL_CALLS = [
    ("create_ingestion", (V2_SPEC,), "POST", "v1/ingestion/", INGESTION_PAYLOAD),
    ("list_ingestions", (), "GET", "v1/ingestion/", [INGESTION_PAYLOAD]),
    ("get_ingestion", (42,), "GET", "v1/ingestion/42", INGESTION_PAYLOAD),
    ("start_ingestion", (42,), "POST", "v1/ingestion/42/start", INGESTION_PAYLOAD),
    (
        "get_ingestion_input_files",
        (42,),
        "GET",
        "v1/ingestion/42/input_files",
        [INPUT_FILE_PAYLOAD],
    ),
    (
        "get_ingestion_output_files",
        (42,),
        "GET",
        "v1/ingestion/42/output_files",
        [OUTPUT_FILE_PAYLOAD],
    ),
    (
        "get_ingestion_stac_items",
        (42,),
        "GET",
        "v1/ingestion/42/stac_items",
        [STAC_ITEM_PAYLOAD],
    ),
    ("get_ingestion_errors", (42,), "GET", "v1/ingestion/42/errors", [ERROR_PAYLOAD]),
    ("list_batches", (42,), "GET", "v1/ingestion/42/batches", [BATCH_PAYLOAD]),
    ("create_batch", (42,), "POST", "v1/ingestion/42/batches", BATCH_PAYLOAD),
    ("get_batch", (42, 3), "GET", "v1/ingestion/42/batches/3", BATCH_PAYLOAD),
    (
        "start_batch",
        (42, 3),
        "POST",
        "v1/ingestion/42/batches/3/start",
        BATCH_PAYLOAD,
    ),
    (
        "get_batch_input_files",
        (42, 3),
        "GET",
        "v1/ingestion/42/batches/3/input_files",
        [INPUT_FILE_PAYLOAD],
    ),
    (
        "get_batch_output_files",
        (42, 3),
        "GET",
        "v1/ingestion/42/batches/3/output_files",
        [OUTPUT_FILE_PAYLOAD],
    ),
    (
        "get_batch_stac_items",
        (42, 3),
        "GET",
        "v1/ingestion/42/batches/3/stac_items",
        [STAC_ITEM_PAYLOAD],
    ),
    (
        "get_batch_errors",
        (42, 3),
        "GET",
        "v1/ingestion/42/batches/3/errors",
        [ERROR_PAYLOAD],
    ),
]


@pytest.mark.parametrize(
    "name,args,method,path,payload", ALL_CALLS, ids=[c[0] for c in ALL_CALLS]
)
def test_call_goes_through_session_with_bearer(
    http: FakeHTTP, ingest_client: IngestClient, name, args, method, path, payload
):
    http.respond(200, payload)
    getattr(ingest_client, name)(*args)

    assert len(http.requests) == 1
    request = http.last
    assert request.method == method
    assert request.url.split("?")[0] == BASE + path
    assert request.headers["Authorization"] == "Bearer mock_token"
    assert request.headers["Accept"] == "application/json"
    assert "organization" not in _query(request)


@pytest.mark.parametrize(
    "name,args,method,path,payload", ALL_CALLS, ids=[c[0] for c in ALL_CALLS]
)
def test_super_admin_organization_is_sent_on_every_call(
    http: FakeHTTP, mock_creds, name, args, method, path, payload
):
    """A SUPER_ADMIN names the Organization with the `organization` query param."""
    client = IngestClient(organization="spk-sandbox")
    http.respond(200, payload)
    getattr(client, name)(*args)
    assert _query(http.last)["organization"] == ["spk-sandbox"]


def test_session_retries_once_after_401(
    mocker: MockerFixture, http: FakeHTTP, ingest_client: IngestClient
):
    """A 401 forces one API key exchange and one retry, as client.session does."""
    # The session holds the bound exchange method it calls after a 401.
    exchange = mocker.patch.object(
        ingest_client.client.session, "_reauthenticate", return_value="new_token"
    )
    http.respond(401, {"detail": "expired"}).respond(200, INGESTION_PAYLOAD)

    result = ingest_client.get_ingestion(42)

    assert result.id == 42
    exchange.assert_called_once()
    assert [r.headers["Authorization"] for r in http.requests] == [
        "Bearer mock_token",
        "Bearer new_token",
    ]


def test_check_goes_through_session(http: FakeHTTP, ingest_client: IngestClient):
    http.respond(204)
    assert ingest_client.check() is True
    assert http.last.url == BASE + "healthz"
    assert http.last.headers["Authorization"] == "Bearer mock_token"


def test_check_returns_false_on_other_status(
    http: FakeHTTP, ingest_client: IngestClient
):
    http.respond(503, {"detail": "Service is not correctly configured."})
    assert ingest_client.check() is False


# ---------------------------------------------------------------------------
# create_ingestion
# ---------------------------------------------------------------------------


def test_create_ingestion_from_bytes_is_multipart(
    http: FakeHTTP, ingest_client: IngestClient
):
    http.respond(201, INGESTION_PAYLOAD)

    result = ingest_client.create_ingestion(V2_SPEC)

    assert isinstance(result, Ingestion)
    assert result.id == 42
    assert result.status is Status.READY
    request = http.last
    # requests sets the multipart Content-Type with its boundary itself.
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="spec_file"; filename="spec.yaml"' in request.body
    assert V2_SPEC in request.body


def test_create_ingestion_from_path(
    http: FakeHTTP, ingest_client: IngestClient, tmp_path
):
    spec_file = tmp_path / "my_spec.yaml"
    spec_file.write_bytes(V2_SPEC)
    http.respond(201, INGESTION_PAYLOAD)

    ingest_client.create_ingestion(spec_file)

    assert b'filename="my_spec.yaml"' in http.last.body
    assert V2_SPEC in http.last.body


def test_create_ingestion_from_string_path(
    http: FakeHTTP, ingest_client: IngestClient, tmp_path
):
    """A str argument is a file path, not YAML content."""
    spec_file = tmp_path / "my_spec.yaml"
    spec_file.write_bytes(V2_SPEC)
    http.respond(201, INGESTION_PAYLOAD)

    ingest_client.create_ingestion(str(spec_file))

    assert b'filename="my_spec.yaml"' in http.last.body


@pytest.mark.parametrize(
    "detail",
    [
        'Ingestion specification "version" must start with "2.", for example "2.0.0".',
        '"user" is not allowed in a version 2 ingestion specification: the '
        "Organization comes from the request.",
        'Location "out" is not publicly readable: an object written there could '
        "not be read back without credentials (PermissionError). Allow public "
        "reads of its prefix before submitting.",
    ],
)
def test_create_ingestion_400_raises_spec_error_with_server_message(
    http: FakeHTTP, ingest_client: IngestClient, detail
):
    http.respond(400, {"detail": detail})
    with pytest.raises(IngestSpecError) as excinfo:
        ingest_client.create_ingestion(V2_SPEC)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == detail
    assert detail in str(excinfo.value)
    # Still an HTTPError, so existing `except HTTPError` code keeps working.
    assert isinstance(excinfo.value, requests.HTTPError)


def test_create_ingestion_409_raises_collection_ownership_error(
    http: FakeHTTP, ingest_client: IngestClient
):
    http.respond(409, {"detail": "The collection belongs to another Organization."})
    with pytest.raises(CollectionOwnershipError) as excinfo:
        ingest_client.create_ingestion(V2_SPEC)
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "The collection belongs to another Organization."


def test_create_ingestion_403_raises_api_error(
    http: FakeHTTP, ingest_client: IngestClient
):
    http.respond(403, {"detail": "organization admin privileges required"})
    with pytest.raises(IngestAPIError) as excinfo:
        ingest_client.create_ingestion(V2_SPEC)
    assert not isinstance(excinfo.value, (IngestSpecError, CollectionOwnershipError))
    assert excinfo.value.detail == "organization admin privileges required"


def test_error_detail_falls_back_to_body_text(
    http: FakeHTTP, ingest_client: IngestClient
):
    http.respond(502, "Bad gateway")
    with pytest.raises(IngestAPIError) as excinfo:
        ingest_client.get_ingestion(42)
    assert excinfo.value.detail == "Bad gateway"


def test_error_detail_serializes_validation_errors(
    http: FakeHTTP, ingest_client: IngestClient
):
    detail = [{"loc": ["query", "limit"], "msg": "too big", "type": "less_than"}]
    http.respond(422, {"detail": detail})
    with pytest.raises(IngestAPIError) as excinfo:
        ingest_client.list_ingestions(limit=5000)
    assert json.loads(excinfo.value.detail) == detail


def test_get_ingestion_404_raises_api_error(
    http: FakeHTTP, ingest_client: IngestClient
):
    http.respond(404, {"detail": "Ingestion not found."})
    with pytest.raises(IngestAPIError, match="Ingestion not found."):
        ingest_client.get_ingestion(999)


# ---------------------------------------------------------------------------
# Listings and pagination
# ---------------------------------------------------------------------------


def test_list_ingestions(http: FakeHTTP, ingest_client: IngestClient):
    http.respond(200, [INGESTION_PAYLOAD, {**INGESTION_PAYLOAD, "id": 41}])

    result = ingest_client.list_ingestions()

    assert [i.id for i in result] == [42, 41]
    assert all(isinstance(i, Ingestion) for i in result)
    assert _path(http.last) == "/ingest/v1/ingestion/"
    assert _query(http.last) == {"limit": ["100"], "offset": ["0"]}


def test_list_ingestions_paginates(http: FakeHTTP, mock_creds):
    client = IngestClient(organization="spk-sandbox")
    http.respond(200, [])
    client.list_ingestions(limit=10, offset=20)
    assert _query(http.last) == {
        "limit": ["10"],
        "offset": ["20"],
        "organization": ["spk-sandbox"],
    }


def test_list_batches(http: FakeHTTP, ingest_client: IngestClient):
    http.respond(200, [BATCH_PAYLOAD])

    result = ingest_client.list_batches(42, limit=5, offset=1)

    assert len(result) == 1
    assert isinstance(result[0], Batch)
    assert _path(http.last) == "/ingest/v1/ingestion/42/batches"
    assert _query(http.last) == {"limit": ["5"], "offset": ["1"]}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


def test_models_parse_mt_payloads(http: FakeHTTP, ingest_client: IngestClient):
    http.respond(200, [INPUT_FILE_PAYLOAD])
    (input_file,) = ingest_client.get_ingestion_input_files(42)
    assert isinstance(input_file, InputFile)
    # MT stac_item_id is a string, not necessarily a UUID.
    assert input_file.stac_item_id == ITEM_ID

    http.respond(200, [OUTPUT_FILE_PAYLOAD])
    (output_file,) = ingest_client.get_ingestion_output_files(42)
    assert isinstance(output_file, OutputFile)
    assert output_file.status is FileStatus.DONE
    assert output_file.path == "assets/lidar/2026/file.tif"

    http.respond(200, [STAC_ITEM_PAYLOAD])
    (stac_item,) = ingest_client.get_batch_stac_items(42, 1)
    assert isinstance(stac_item, StacItem)
    assert stac_item.status is FileStatus.PENDING

    http.respond(200, [ERROR_PAYLOAD])
    (error,) = ingest_client.get_ingestion_errors(42)
    assert isinstance(error, Error)
    assert error.severity is ErrorSeverity.WARNING


def test_models_accept_fields_the_server_omits(
    http: FakeHTTP, ingest_client: IngestClient
):
    """Some MT routes use response_model_exclude_none, so null fields go missing."""
    http.respond(200, [{k: v for k, v in OUTPUT_FILE_PAYLOAD.items() if k != "path"}])
    (output_file,) = ingest_client.get_ingestion_output_files(42)
    assert output_file.path is None

    http.respond(
        200,
        [
            {
                "severity": "WARNING",
                "time_occurred": NOW_ISO,
                "description": "x",
                "ingestion_id": 1,
            }
        ],
    )
    (error,) = ingest_client.get_ingestion_errors(42)
    assert error.input_file is None


def test_start_batch_accepts_202_planning(http: FakeHTTP, ingest_client: IngestClient):
    """A slow launch returns 202 with the batch still PLANNING; that is not an error."""
    http.respond(202, {**BATCH_PAYLOAD, "status": "PLANNING"})
    batch = ingest_client.start_batch(42, 1)
    assert batch.status is Status.PLANNING


def test_status_has_no_incomplete():
    """The MT service has no INCOMPLETE status."""
    assert "INCOMPLETE" not in Status.__members__


def test_requests_have_a_default_timeout(
    mocker: MockerFixture, http: FakeHTTP, ingest_client: IngestClient
):
    """A stalled connection must not block a call, or a wait, without limit."""
    spy = mocker.spy(ingest_client.client.session, "request")
    http.respond(200, INGESTION_PAYLOAD)

    ingest_client.get_ingestion(42)

    assert spy.call_args.kwargs["timeout"] == 30
