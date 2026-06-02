import io
import os
from unittest.mock import MagicMock

import pytest
import requests
from pytest_mock import MockerFixture

from prescient_sdk.client import PrescientClient
from prescient_sdk.config import Settings
from prescient_sdk.ingest import IngestClient
from prescient_sdk.ingest_models import (
    Batch,
    Error,
    ErrorSeverity,
    FileStatus,
    Ingestion,
    InputFile,
    OutputFile,
    Status,
    TaskType,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"
NOW_ISO = "2026-01-01T00:00:00Z"

INGESTION_PAYLOAD = {
    "id": 42,
    "status": "READY",
    "spec": {"user": "test@example.com"},
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
    "location": "s3://bucket/data",
    "source_file_set": "fileset_a",
    "path": "data/file.tif",
    "last_modified": NOW_ISO,
    "stac_item_id": UUID_A,
}

OUTPUT_FILE_PAYLOAD = {
    "stac_item_id": UUID_A,
    "task_name": "transform_main",
    "status": "DONE",
}

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clear_prescient_env(monkeypatch: pytest.MonkeyPatch):
    """Remove every PRESCIENT_* env var so tests aren't polluted by the host shell."""
    for key in list(os.environ):
        if key.startswith("PRESCIENT_"):
            monkeypatch.delenv(key)


@pytest.fixture
def set_env_vars(monkeypatch: pytest.MonkeyPatch, clear_prescient_env):
    """Set the minimum config env vars for IngestClient initialization."""
    monkeypatch.setenv(
        "PRESCIENT_ENDPOINT_URL", "https://example.server.prescient.earth"
    )
    monkeypatch.setenv("PRESCIENT_TENANT_ID", "some-tenant-id")
    monkeypatch.setenv("PRESCIENT_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("PRESCIENT_AUTH_URL", "https://login.somewhere.com/")


@pytest.fixture
def mock_creds(mocker: MockerFixture, set_env_vars):
    """Short-circuit auth so headers always return a Bearer token."""
    mocker.patch(
        "prescient_sdk.client.PrescientClient.auth_credentials",
        new_callable=mocker.PropertyMock,
        return_value={"id_token": "mock_token"},
    )


@pytest.fixture
def ingest_client(mock_creds) -> IngestClient:
    return IngestClient()


def _make_response(
    json_payload=None, status_code: int = 200, raise_for_status: bool = False
) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = json_payload
    if raise_for_status:
        response.raise_for_status.side_effect = requests.HTTPError("boom")
    else:
        response.raise_for_status = MagicMock()
    return response


# ---------------------------------------------------------------------------
# Initialization & URL handling
# ---------------------------------------------------------------------------


def test_ingest_client_default_init(mock_creds):
    """IngestClient can be constructed without arguments using env vars."""
    client = IngestClient()
    assert isinstance(client.client, PrescientClient)


def test_ingest_client_accepts_prescient_client(mock_creds):
    """A pre-built PrescientClient is reused rather than re-constructed."""
    pc = PrescientClient()
    ic = IngestClient(prescient_client=pc)
    assert ic.client is pc


def test_ingest_client_rejects_conflicting_args(mock_creds):
    """Passing both prescient_client and settings/env_file is an error."""
    pc = PrescientClient()
    with pytest.raises(ValueError, match="prescient_client"):
        IngestClient(prescient_client=pc, settings=pc.settings)


def test_base_url_falls_back_to_endpoint_url(mock_creds):
    """When prescient_ingest_endpoint_url is unset, base_url uses prescient_endpoint_url."""
    client = IngestClient()
    assert client._client.settings.prescient_ingest_endpoint_url is None
    assert client.base_url == "https://example.server.prescient.earth/ingest/"


def test_base_url_override_wins(monkeypatch: pytest.MonkeyPatch, mock_creds):
    """When prescient_ingest_endpoint_url is set, it wins over the main endpoint."""
    monkeypatch.setenv("PRESCIENT_INGEST_ENDPOINT_URL", "https://ingest.example.com/")
    client = IngestClient()
    assert client.base_url == "https://ingest.example.com/"


def test_base_url_override_is_strict(monkeypatch: pytest.MonkeyPatch, mock_creds):
    """An explicit override is used as-is; no ``/ingest`` segment is appended."""
    monkeypatch.setenv(
        "PRESCIENT_INGEST_ENDPOINT_URL", "https://different.example.com/api"
    )
    client = IngestClient()
    # Trailing slash normalized, but /ingest is NOT added.
    assert client.base_url == "https://different.example.com/api/"
    assert "/ingest" not in client.base_url


def test_base_url_adds_trailing_slash(mock_creds):
    """base_url always ends with a slash so urljoin produces sensible URLs."""
    settings = Settings(  # type: ignore[call-arg]
        prescient_endpoint_url="https://no-trailing-slash.example.com",
        prescient_tenant_id="t",
        prescient_client_id="c",
        prescient_auth_url="https://a/",
    )
    client = IngestClient(prescient_client=PrescientClient(settings=settings))
    assert client.base_url.endswith("/")


def test_url_joins_v1_paths(mock_creds):
    """_url composes v1-prefixed endpoint paths against the base URL."""
    client = IngestClient()
    assert (
        client._url("v1/ingestion/42/start")
        == "https://example.server.prescient.earth/ingest/v1/ingestion/42/start"
    )


# ---------------------------------------------------------------------------
# create_ingestion
# ---------------------------------------------------------------------------


def test_create_ingestion_from_bytes(mocker: MockerFixture, ingest_client: IngestClient):
    """Bytes are uploaded directly as the multipart spec_file part."""
    post_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(INGESTION_PAYLOAD),
    )
    spec = b"user: tester\n"

    result = ingest_client.create_ingestion(spec)

    assert isinstance(result, Ingestion)
    assert result.id == 42
    assert result.status is Status.READY

    method, url = post_mock.call_args.args
    kwargs = post_mock.call_args.kwargs
    assert method == "POST"
    assert url == "https://example.server.prescient.earth/ingest/v1/ingestion/"
    assert kwargs["files"]["spec_file"][0] == "spec.yaml"
    assert kwargs["files"]["spec_file"][1] == spec
    assert kwargs["files"]["spec_file"][2] == "application/yaml"
    # Multipart upload must NOT pin Content-Type — requests sets it with
    # the boundary parameter when files= is supplied.
    assert "Content-Type" not in kwargs["headers"]
    # IngestClient does not send an Authorization header (port-forwarded API).
    assert "Authorization" not in kwargs["headers"]


def test_create_ingestion_from_path(
    mocker: MockerFixture, ingest_client: IngestClient, tmp_path
):
    """A Path is opened in binary mode and uploaded."""
    spec_file = tmp_path / "my_spec.yaml"
    spec_file.write_text("user: tester\n")

    post_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(INGESTION_PAYLOAD),
    )

    result = ingest_client.create_ingestion(spec_file)
    assert isinstance(result, Ingestion)

    files = post_mock.call_args.kwargs["files"]
    assert files["spec_file"][0] == "my_spec.yaml"
    # Filename came from the Path; file handle was opened in binary mode.
    assert isinstance(files["spec_file"][1], io.BufferedReader) or hasattr(
        files["spec_file"][1], "read"
    )


def test_create_ingestion_from_string_path(
    mocker: MockerFixture, ingest_client: IngestClient, tmp_path
):
    """A str argument is treated as a file path, not as YAML content."""
    spec_file = tmp_path / "my_spec.yaml"
    spec_file.write_text("user: tester\n")

    post_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(INGESTION_PAYLOAD),
    )

    ingest_client.create_ingestion(str(spec_file))

    assert post_mock.call_args.kwargs["files"]["spec_file"][0] == "my_spec.yaml"


def test_create_ingestion_propagates_http_errors(
    mocker: MockerFixture, ingest_client: IngestClient
):
    """4xx responses surface as requests.HTTPError via raise_for_status."""
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(status_code=400, raise_for_status=True),
    )
    with pytest.raises(requests.HTTPError):
        ingest_client.create_ingestion(b"user: tester\n")


# ---------------------------------------------------------------------------
# Ingestion-level GETs / POSTs
# ---------------------------------------------------------------------------


def test_get_ingestion(mocker: MockerFixture, ingest_client: IngestClient):
    request_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(INGESTION_PAYLOAD),
    )

    result = ingest_client.get_ingestion(42)

    assert isinstance(result, Ingestion)
    assert result.id == 42
    assert result.status is Status.READY
    method, url = request_mock.call_args.args
    assert method == "GET"
    assert url == "https://example.server.prescient.earth/ingest/v1/ingestion/42"
    # No Authorization header — Ingest API is reached over a port-forward.
    assert "Authorization" not in request_mock.call_args.kwargs["headers"]
    assert request_mock.call_args.kwargs["headers"]["Accept"] == "application/json"


def test_start_ingestion(mocker: MockerFixture, ingest_client: IngestClient):
    request_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response({**INGESTION_PAYLOAD, "status": "INGESTING"}),
    )

    result = ingest_client.start_ingestion(42)
    assert result.status is Status.INGESTING
    assert request_mock.call_args.args == (
        "POST",
        "https://example.server.prescient.earth/ingest/v1/ingestion/42/start",
    )


def test_get_ingestion_input_files(mocker: MockerFixture, ingest_client: IngestClient):
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response([INPUT_FILE_PAYLOAD, INPUT_FILE_PAYLOAD]),
    )
    result = ingest_client.get_ingestion_input_files(42)
    assert len(result) == 2
    assert all(isinstance(f, InputFile) for f in result)
    assert result[0].path == "data/file.tif"


def test_get_ingestion_output_files(mocker: MockerFixture, ingest_client: IngestClient):
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response([OUTPUT_FILE_PAYLOAD]),
    )
    result = ingest_client.get_ingestion_output_files(42)
    assert len(result) == 1
    assert isinstance(result[0], OutputFile)
    assert result[0].status is FileStatus.DONE
    assert result[0].task_name == "transform_main"


def test_get_ingestion_errors(mocker: MockerFixture, ingest_client: IngestClient):
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response([ERROR_PAYLOAD]),
    )
    result = ingest_client.get_ingestion_errors(42)
    assert len(result) == 1
    assert isinstance(result[0], Error)
    assert result[0].severity is ErrorSeverity.WARNING


# ---------------------------------------------------------------------------
# Batch-level endpoints
# ---------------------------------------------------------------------------


def test_list_batches(mocker: MockerFixture, ingest_client: IngestClient):
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response([BATCH_PAYLOAD]),
    )
    result = ingest_client.list_batches(42)
    assert len(result) == 1
    assert isinstance(result[0], Batch)
    assert result[0].batch_number == 1


def test_create_batch(mocker: MockerFixture, ingest_client: IngestClient):
    request_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(BATCH_PAYLOAD),
    )
    result = ingest_client.create_batch(42)
    assert isinstance(result, Batch)
    assert request_mock.call_args.args == (
        "POST",
        "https://example.server.prescient.earth/ingest/v1/ingestion/42/batches",
    )


def test_get_batch(mocker: MockerFixture, ingest_client: IngestClient):
    request_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(BATCH_PAYLOAD),
    )
    result = ingest_client.get_batch(42, 1)
    assert result.status is Status.SCANNING
    assert request_mock.call_args.args == (
        "GET",
        "https://example.server.prescient.earth/ingest/v1/ingestion/42/batches/1",
    )


def test_start_batch(mocker: MockerFixture, ingest_client: IngestClient):
    request_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response({**BATCH_PAYLOAD, "status": "INGESTING"}),
    )
    result = ingest_client.start_batch(42, 1)
    assert result.status is Status.INGESTING
    assert request_mock.call_args.args == (
        "POST",
        "https://example.server.prescient.earth/ingest/v1/ingestion/42/batches/1/start",
    )


def test_get_batch_input_files(mocker: MockerFixture, ingest_client: IngestClient):
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response([INPUT_FILE_PAYLOAD]),
    )
    result = ingest_client.get_batch_input_files(42, 1)
    assert len(result) == 1
    assert isinstance(result[0], InputFile)


def test_get_batch_output_files(mocker: MockerFixture, ingest_client: IngestClient):
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response([OUTPUT_FILE_PAYLOAD]),
    )
    result = ingest_client.get_batch_output_files(42, 1)
    assert len(result) == 1
    assert isinstance(result[0], OutputFile)


def test_get_batch_errors(mocker: MockerFixture, ingest_client: IngestClient):
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response([ERROR_PAYLOAD]),
    )
    result = ingest_client.get_batch_errors(42, 1)
    assert len(result) == 1
    assert isinstance(result[0], Error)


# ---------------------------------------------------------------------------
# Error propagation on GETs
# ---------------------------------------------------------------------------


def test_get_ingestion_propagates_404(
    mocker: MockerFixture, ingest_client: IngestClient
):
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(status_code=404, raise_for_status=True),
    )
    with pytest.raises(requests.HTTPError):
        ingest_client.get_ingestion(999)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


def test_check_returns_true_on_204(
    mocker: MockerFixture, ingest_client: IngestClient
):
    get_mock = mocker.patch(
        "prescient_sdk.ingest.requests.get",
        return_value=_make_response(status_code=204),
    )
    assert ingest_client.check() is True
    assert (
        get_mock.call_args.args[0]
        == "https://example.server.prescient.earth/ingest/healthy"
    )


def test_check_returns_false_on_other_status(
    mocker: MockerFixture, ingest_client: IngestClient, capsys: pytest.CaptureFixture
):
    """Non-204 response returns False; when the override is unset, also warns to stdout."""
    mocker.patch(
        "prescient_sdk.ingest.requests.get",
        return_value=_make_response(status_code=500),
    )
    assert ingest_client.check() is False
    # PRESCIENT_INGEST_ENDPOINT_URL is not set in the test env, so the warning fires.
    captured = capsys.readouterr()
    assert "PRESCIENT_INGEST_ENDPOINT_URL" in captured.out


def test_check_does_not_warn_when_override_is_set(
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    mock_creds,
    capsys: pytest.CaptureFixture,
):
    """When the override URL is set, a failing /healthy does not print a warning."""
    monkeypatch.setenv("PRESCIENT_INGEST_ENDPOINT_URL", "https://ingest.example.com/")
    client = IngestClient()
    mocker.patch(
        "prescient_sdk.ingest.requests.get",
        return_value=_make_response(status_code=500),
    )
    assert client.check() is False
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# wait_for_status
# ---------------------------------------------------------------------------


def test_wait_for_status_returns_when_target_reached(
    mocker: MockerFixture, ingest_client: IngestClient
):
    """Polls until status enters target set, then returns."""
    responses = [
        _make_response({**INGESTION_PAYLOAD, "status": "SCANNING"}),
        _make_response({**INGESTION_PAYLOAD, "status": "SCANNING"}),
        _make_response({**INGESTION_PAYLOAD, "status": "READY"}),
    ]
    mocker.patch("prescient_sdk.ingest.requests.request", side_effect=responses)
    sleep_mock = mocker.patch("prescient_sdk.ingest.time.sleep")

    result = ingest_client.wait_for_status(42, poll_interval=0.01, timeout=10)

    assert isinstance(result, Ingestion)
    assert result.status is Status.READY
    # Slept after each non-terminal poll, but not after the terminal one.
    assert sleep_mock.call_count == 2


def test_wait_for_status_polls_batch_when_batch_number_given(
    mocker: MockerFixture, ingest_client: IngestClient
):
    request_mock = mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response({**BATCH_PAYLOAD, "status": "DONE"}),
    )
    mocker.patch("prescient_sdk.ingest.time.sleep")

    result = ingest_client.wait_for_status(42, batch_number=1, poll_interval=0.01)
    assert isinstance(result, Batch)
    assert result.status is Status.DONE
    # Must hit the batch endpoint, not the top-level ingestion endpoint.
    assert request_mock.call_args.args[1].endswith("/batches/1")


def test_wait_for_status_times_out(
    mocker: MockerFixture, ingest_client: IngestClient
):
    """If a target status is never reached, TimeoutError is raised."""
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response({**INGESTION_PAYLOAD, "status": "SCANNING"}),
    )
    mocker.patch("prescient_sdk.ingest.time.sleep")
    # Drive monotonic so the deadline elapses on the first iteration.
    mocker.patch(
        "prescient_sdk.ingest.time.monotonic", side_effect=[0.0, 100.0, 100.0]
    )

    with pytest.raises(TimeoutError):
        ingest_client.wait_for_status(
            42,
            target_statuses=[Status.DONE],
            poll_interval=0.01,
            timeout=1,
        )


def test_wait_for_status_custom_target(
    mocker: MockerFixture, ingest_client: IngestClient
):
    """Custom target sets are honored (e.g., waiting for DONE/FAILED only)."""
    responses = [
        _make_response({**INGESTION_PAYLOAD, "status": "READY"}),
        _make_response({**INGESTION_PAYLOAD, "status": "INGESTING"}),
        _make_response({**INGESTION_PAYLOAD, "status": "DONE"}),
    ]
    mocker.patch("prescient_sdk.ingest.requests.request", side_effect=responses)
    mocker.patch("prescient_sdk.ingest.time.sleep")

    result = ingest_client.wait_for_status(
        42,
        target_statuses=[Status.DONE, Status.FAILED],
        poll_interval=0.01,
    )
    assert result.status is Status.DONE


# ---------------------------------------------------------------------------
# Model coverage: TaskType enum is reachable via IngestionSpec
# ---------------------------------------------------------------------------


def test_ingestion_spec_deserializes_tasks(
    mocker: MockerFixture, ingest_client: IngestClient
):
    """A richer Ingestion payload with tasks parses cleanly into typed enums."""
    payload = {
        "id": 7,
        "status": "READY",
        "spec": {
            "user": "tester",
            "tasks": {
                "main": {"type": "transform", "input_location": "loc_a"},
                "thumb": {"type": "thumbnail", "input_location": "loc_b"},
            },
        },
    }
    mocker.patch(
        "prescient_sdk.ingest.requests.request",
        return_value=_make_response(payload),
    )
    result = ingest_client.get_ingestion(7)
    assert result.spec.tasks["main"].type is TaskType.TRANSFORM
    assert result.spec.tasks["thumb"].type is TaskType.THUMBNAIL
