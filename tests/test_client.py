import io
import json
from unittest.mock import MagicMock

import pytest
import requests
from pystac_client.stac_api_io import StacApiIO
from pytest_mock import MockerFixture

from prescient_sdk.client import PrescientAuthError, PrescientClient
from prescient_sdk.config import Settings

EXCHANGE_URL = (
    "https://keycloak.staging.prescient.earth/realms/spk-sandbox/api-keys/exchange"
)


def _response(status_code: int, json_payload=None, headers=None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = json.dumps(json_payload).encode() if json_payload else b""
    response._content_consumed = True
    return response


def _token(n: int, expires_in: int = 300) -> requests.Response:
    return _response(
        200,
        {
            "access_token": f"token-{n}",
            "token_type": "Bearer",
            "expires_in": expires_in,
        },
    )


@pytest.fixture
def exchange(mocker: MockerFixture) -> MagicMock:
    """Mock the Keycloak exchange; each call returns token-1, token-2, ..."""
    tokens = iter(range(1, 100))
    return mocker.patch(
        "prescient_sdk.client.requests.post",
        side_effect=lambda *args, **kwargs: _token(next(tokens)),
    )


@pytest.fixture
def clock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("prescient_sdk.client.time.monotonic", return_value=1000.0)


@pytest.fixture
def send(mocker: MockerFixture) -> MagicMock:
    """Mock the transport under every requests.Session; returns 200 by default."""

    def reply(request, **kwargs):
        response = _response(200, {})
        response.request = request
        return response

    return mocker.patch.object(requests.Session, "send", side_effect=reply)


def _statuses(send: MagicMock, *codes: int) -> None:
    """Make the mocked transport answer with these status codes in order."""
    codes_iter = iter(codes)

    def reply(request, **kwargs):
        response = _response(next(codes_iter), {})
        response.request = request
        return response

    send.side_effect = reply


# Construction


def test_prescient_client_initialization(set_env_vars):
    client = PrescientClient()
    assert client.settings.prescient_endpoint_url is not None


def test_env_file_init(clear_prescient_env, tmp_path):
    env_file = tmp_path / "config.env"
    env_file.write_text(
        "PRESCIENT_ENDPOINT_URL=https://some-test.prescient.earth\n"
        "PRESCIENT_API_KEY=pk_test\n"
    )
    client = PrescientClient(env_file=str(env_file))
    assert client.settings.prescient_endpoint_url == "https://some-test.prescient.earth"


def test_missing_env_file_raises(clear_prescient_env, tmp_path):
    with pytest.raises(ValueError, match="not found"):
        PrescientClient(env_file=tmp_path / "missing.env")


def test_fail_when_passing_both_env_file_and_settings(set_env_vars):
    with pytest.raises(ValueError):
        PrescientClient(env_file="some-file.env", settings=Settings())  # type: ignore


def test_settings_loaded_explicitly(clear_prescient_env):
    settings = Settings(
        prescient_endpoint_url="https://spk-sandbox.staging.prescient.earth",
        prescient_api_key="pk_test",  # type: ignore[arg-type]
    )
    client = PrescientClient(settings=settings)
    assert client.settings is settings


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://acme.prescient.earth", "https://acme.prescient.earth/stac"),
        ("https://acme.prescient.earth/", "https://acme.prescient.earth/stac"),
        ("https://example.com/api/v2", "https://example.com/api/v2/stac"),
    ],
)
def test_stac_url(clear_prescient_env, endpoint, expected):
    settings = Settings(prescient_endpoint_url=endpoint, prescient_api_key="pk_test")  # type: ignore[arg-type]
    assert PrescientClient(settings=settings).stac_url == expected


# Token exchange


def test_exchange_request(set_env_vars, exchange, clock):
    client = PrescientClient()
    assert client.headers == {"Authorization": "Bearer token-1"}
    exchange.assert_called_once()
    assert exchange.call_args.args[0] == EXCHANGE_URL
    assert exchange.call_args.kwargs["headers"] == {"X-API-Key": "pk_test"}
    assert exchange.call_args.kwargs["timeout"]


def test_token_cached_within_lifetime(set_env_vars, exchange, clock):
    client = PrescientClient()
    client.headers
    clock.return_value += 200  # 100 s left of 300
    assert client.headers == {"Authorization": "Bearer token-1"}
    assert exchange.call_count == 1


def test_token_reexchanged_near_expiry(set_env_vars, exchange, clock):
    client = PrescientClient()
    client.headers
    clock.return_value += 241  # 59 s left of 300
    assert client.headers == {"Authorization": "Bearer token-2"}
    assert exchange.call_count == 2


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_raises(set_env_vars, mocker: MockerFixture, status):
    mocker.patch("prescient_sdk.client.requests.post", return_value=_response(status))
    with pytest.raises(PrescientAuthError, match="Account Console"):
        PrescientClient().headers


@pytest.mark.parametrize(("header", "expected"), [("17", 17), (None, None)])
def test_rate_limited_raises_with_retry_after(
    set_env_vars, mocker: MockerFixture, header, expected
):
    post = mocker.patch(
        "prescient_sdk.client.requests.post",
        return_value=_response(429, headers={"Retry-After": header} if header else {}),
    )
    with pytest.raises(PrescientAuthError) as excinfo:
        PrescientClient().headers
    assert excinfo.value.retry_after == expected
    post.assert_called_once()


def test_other_exchange_error_raises_http_error(set_env_vars, mocker: MockerFixture):
    mocker.patch("prescient_sdk.client.requests.post", return_value=_response(500))
    with pytest.raises(requests.HTTPError):
        PrescientClient().headers


# Session, auth and request_modifier


def test_session_sends_bearer(set_env_vars, exchange, clock, send):
    response = PrescientClient().session.get("https://example.com/stac")
    assert response.status_code == 200
    assert send.call_args.args[0].headers["Authorization"] == "Bearer token-1"


def test_session_retries_once_after_401(set_env_vars, exchange, clock, send):
    _statuses(send, 401, 200)
    response = PrescientClient().session.post(
        "https://example.com/stac/search", json={"limit": 1}
    )
    assert response.status_code == 200
    assert exchange.call_count == 2
    sent = [call.args[0] for call in send.call_args_list]
    assert [r.headers["Authorization"] for r in sent] == [
        "Bearer token-1",
        "Bearer token-2",
    ]
    assert sent[1].body == sent[0].body


def test_session_retry_resends_uploaded_file(set_env_vars, exchange, clock, send):
    """`files=` reads the file once; the retry must resend the same bytes."""
    _statuses(send, 401, 200)
    PrescientClient().session.post(
        "https://example.com/ingest/v1/ingestion",
        files={"spec": io.BytesIO(b"user: tester")},
    )
    sent = [call.args[0] for call in send.call_args_list]
    assert b"user: tester" in sent[1].body
    assert sent[1].body == sent[0].body


def test_session_no_retry_without_authorization(set_env_vars, exchange, clock, send):
    """A request without our header (e.g. after a cross-host redirect) is not retried."""
    _statuses(send, 401)
    session = PrescientClient().session
    session.auth = None
    response = session.get("https://other-host.example.com/")
    assert response.status_code == 401
    assert send.call_count == 1
    exchange.assert_not_called()


def test_session_second_401_surfaces(set_env_vars, exchange, clock, send):
    _statuses(send, 401, 401)
    response = PrescientClient().session.get("https://example.com/stac")
    assert response.status_code == 401
    assert send.call_count == 2
    assert exchange.call_count == 2


def test_session_does_not_retry_stream_body(set_env_vars, exchange, clock, send):
    _statuses(send, 401)
    response = PrescientClient().session.put(
        "https://example.com/upload", data=io.BytesIO(b"data")
    )
    assert response.status_code == 401
    assert send.call_count == 1
    assert exchange.call_count == 1


def test_auth_sets_bearer_on_plain_requests(set_env_vars, exchange, clock, send):
    client = PrescientClient()
    requests.get("https://example.com/raster", auth=client.auth)
    assert send.call_args.args[0].headers["Authorization"] == "Bearer token-1"


def test_request_modifier_with_pystac_client(set_env_vars, exchange, clock, send):
    client = PrescientClient()
    stac_io = StacApiIO(request_modifier=client.request_modifier)
    stac_io.request(client.stac_url)
    sent = send.call_args.args[0]
    assert sent.url == "https://spk-sandbox.staging.prescient.earth/stac"
    assert sent.headers["Authorization"] == "Bearer token-1"
