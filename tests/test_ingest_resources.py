"""Tests for the high-level IngestionResource / BatchResource classes."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from prescient_sdk import ingest_models as models
from prescient_sdk.ingest_client import IngestClient
from prescient_sdk.ingest_resources import BatchResource, IngestionResource, LiveStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ingestion_model(
    id: int = 1,
    status: str = "SCANNING",
    user: str = "tester",
) -> models.Ingestion:
    return models.Ingestion(
        id=id,
        status=status,
        spec={"user": user},
    )


def make_batch_model(
    ingestion_id: int = 1,
    batch_number: int = 1,
    status: str = "SCANNING",
) -> models.Batch:
    return models.Batch(
        id=batch_number * 100,
        ingestion_id=ingestion_id,
        batch_number=batch_number,
        created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        started=None,
        finalized=None,
        status=status,
    )


def make_error_model(severity: str = "WARNING", description: str = "x") -> models.Error:
    return models.Error(
        severity=severity,
        time_occurred=datetime(2026, 1, 1, tzinfo=timezone.utc),
        description=description,
        ingestion_id=1,
        location=None,
        task=None,
        input_file=None,
        stack_trace=None,
    )


def make_output_file_model(
    status: str = "DONE", task_name: str = "transform_main"
) -> models.OutputFile:
    return models.OutputFile(
        stac_item_id=uuid4(),
        task_name=task_name,
        status=status,
    )


@pytest.fixture
def client(mocker: MockerFixture) -> MagicMock:
    """A MagicMock IngestClient with sensible default return values."""
    mock = mocker.MagicMock(spec=IngestClient)
    mock.create_ingestion.return_value = make_ingestion_model(id=1, status="SCANNING")
    mock.get_ingestion.return_value = make_ingestion_model(id=1, status="SCANNING")
    mock.start_ingestion.return_value = make_ingestion_model(id=1, status="INGESTING")
    mock.get_ingestion_input_files.return_value = []
    mock.get_ingestion_output_files.return_value = []
    mock.get_ingestion_errors.return_value = []
    mock.create_batch.return_value = make_batch_model(batch_number=1, status="SCANNING")
    mock.get_batch.return_value = make_batch_model(batch_number=1, status="SCANNING")
    mock.start_batch.return_value = make_batch_model(batch_number=1, status="INGESTING")
    mock.list_batches.return_value = []
    mock.get_batch_input_files.return_value = []
    mock.get_batch_output_files.return_value = []
    mock.get_batch_errors.return_value = []
    return mock


# ---------------------------------------------------------------------------
# IngestionResource construction
# ---------------------------------------------------------------------------


def test_ingestion_create_calls_create_ingestion(client):
    ing = IngestionResource.create(client, spec=b"user: tester\n")
    client.create_ingestion.assert_called_once_with(b"user: tester\n")
    client.get_ingestion.assert_not_called()
    assert ing.id == 1


def test_ingestion_from_id_calls_get_ingestion(client):
    ing = IngestionResource.from_id(client, id=42)
    client.get_ingestion.assert_called_once_with(42)
    client.create_ingestion.assert_not_called()
    assert ing.id == 1  # from the mock's return value


# ---------------------------------------------------------------------------
# IngestionResource properties & listings
# ---------------------------------------------------------------------------


def test_ingestion_properties_delegate_to_model(client):
    client.create_ingestion.return_value = make_ingestion_model(
        id=7, status="READY", user="alice"
    )
    ing = IngestionResource.create(client, spec=b"")
    assert ing.id == 7
    assert ing.status is models.Status.READY
    assert ing.spec["user"] == "alice"


def test_ingestion_listings_call_through(client):
    ing = IngestionResource.create(client, spec=b"")
    ing.input_files()
    ing.output_files()
    ing.errors()
    client.get_ingestion_input_files.assert_called_with(1)
    client.get_ingestion_output_files.assert_called_with(1)
    client.get_ingestion_errors.assert_called_with(1)


# ---------------------------------------------------------------------------
# IngestionResource lifecycle
# ---------------------------------------------------------------------------


def test_ingestion_refresh_updates_status_and_errors(client):
    ing = IngestionResource.create(client, spec=b"")
    # After construction the status is SCANNING; switch the mock to READY.
    client.get_ingestion.return_value = make_ingestion_model(id=1, status="READY")
    client.get_ingestion_errors.return_value = [make_error_model()]

    ing.refresh()

    assert ing.status is models.Status.READY
    assert len(ing._errors) == 1


def test_ingestion_start_updates_state(client):
    ing = IngestionResource.create(client, spec=b"")
    ing.start()
    client.start_ingestion.assert_called_once_with(1)
    assert ing.status is models.Status.INGESTING


def test_ingestion_wait_until_ready_polls_until_target(
    mocker: MockerFixture, client
):
    ing = IngestionResource.create(client, spec=b"")
    # Two SCANNING polls, then READY.
    client.get_ingestion.side_effect = [
        make_ingestion_model(status="SCANNING"),
        make_ingestion_model(status="SCANNING"),
        make_ingestion_model(status="READY"),
    ]
    sleep = mocker.patch("prescient_sdk.ingest_client.time.sleep")

    result = ing.wait_until_ready(poll_interval=0.01, timeout=10)

    assert result is ing
    assert ing.status is models.Status.READY
    # Slept between non-terminal polls but not after the terminal one.
    assert sleep.call_count == 2


def test_ingestion_wait_until_done_targets_done_failed_incomplete(
    mocker: MockerFixture, client
):
    ing = IngestionResource.create(client, spec=b"")
    # READY should NOT terminate wait_until_done — it should keep polling.
    client.get_ingestion.side_effect = [
        make_ingestion_model(status="READY"),
        make_ingestion_model(status="INGESTING"),
        make_ingestion_model(status="DONE"),
    ]
    mocker.patch("prescient_sdk.ingest_client.time.sleep")

    ing.wait_until_done(poll_interval=0.01)
    assert ing.status is models.Status.DONE


def test_ingestion_wait_times_out(mocker: MockerFixture, client):
    ing = IngestionResource.create(client, spec=b"")
    client.get_ingestion.return_value = make_ingestion_model(status="SCANNING")
    mocker.patch("prescient_sdk.ingest_client.time.sleep")
    # Force monotonic to jump past the deadline on first check.
    mocker.patch(
        "prescient_sdk.ingest_client.time.monotonic",
        side_effect=[0.0, 100.0, 100.0],
    )

    with pytest.raises(TimeoutError):
        ing.wait_until_ready(poll_interval=0.01, timeout=1)


# ---------------------------------------------------------------------------
# IngestionResource batches
# ---------------------------------------------------------------------------


def test_ingestion_create_batch_returns_batch_resource(client):
    ing = IngestionResource.create(client, spec=b"")
    client.create_batch.return_value = make_batch_model(
        ingestion_id=1, batch_number=2
    )

    batch = ing.create_batch()
    assert isinstance(batch, BatchResource)
    assert batch.batch_number == 2
    client.create_batch.assert_called_once_with(1)


def test_ingestion_list_batches_returns_wrappers(client):
    client.list_batches.return_value = [
        make_batch_model(batch_number=1),
        make_batch_model(batch_number=2),
    ]
    ing = IngestionResource.create(client, spec=b"")

    batches = ing.list_batches()
    assert len(batches) == 2
    assert all(isinstance(b, BatchResource) for b in batches)
    assert [b.batch_number for b in batches] == [1, 2]


# ---------------------------------------------------------------------------
# LiveStatus wrapper
# ---------------------------------------------------------------------------


def test_live_status_starts_and_stops_live(mocker: MockerFixture, client):
    live_cls = mocker.patch("prescient_sdk.ingest_resources.Live")
    live_instance = live_cls.return_value

    ing = IngestionResource.create(client, spec=b"")
    with LiveStatus(ing) as scope:
        assert scope is ing
        live_instance.start.assert_called_once()

    # On exit: a final refresh, then update + stop.
    live_instance.stop.assert_called_once()
    assert live_instance.update.call_count >= 1


def test_live_status_updates_on_refresh(mocker: MockerFixture, client):
    live_cls = mocker.patch("prescient_sdk.ingest_resources.Live")
    live_instance = live_cls.return_value

    ing = IngestionResource.create(client, spec=b"")
    with LiveStatus(ing):
        # Each refresh should fire the observer and update the live display.
        ing.refresh()
        ing.refresh()

    # At least one update per refresh plus the final exit update.
    assert live_instance.update.call_count >= 3


def test_live_status_unsubscribes_on_exit(mocker: MockerFixture, client):
    live_cls = mocker.patch("prescient_sdk.ingest_resources.Live")
    live_instance = live_cls.return_value

    ing = IngestionResource.create(client, spec=b"")
    with LiveStatus(ing):
        pass

    # After exit, refresh() must not poke the (now-stopped) live display.
    live_instance.update.reset_mock()
    ing.refresh()
    live_instance.update.assert_not_called()


def test_live_status_stops_live_even_if_refresh_fails(
    mocker: MockerFixture, client
):
    live_cls = mocker.patch("prescient_sdk.ingest_resources.Live")
    live_instance = live_cls.return_value

    ing = IngestionResource.create(client, spec=b"")
    # The first call (in create) succeeded; make the next refresh raise.
    client.get_ingestion.side_effect = RuntimeError("network down")

    with LiveStatus(ing):
        pass

    live_instance.stop.assert_called_once()


def test_live_status_does_not_swallow_exceptions(
    mocker: MockerFixture, client
):
    mocker.patch("prescient_sdk.ingest_resources.Live")
    ing = IngestionResource.create(client, spec=b"")

    with pytest.raises(RuntimeError, match="user code"):
        with LiveStatus(ing):
            raise RuntimeError("user code")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_produces_non_empty_renderable(client):
    """_render output can be printed without raising."""
    import io
    from rich.console import Console

    ing = IngestionResource.create(client, spec=b"")
    buf = io.StringIO()
    Console(file=buf, force_terminal=True, width=120).print(ing)
    out = buf.getvalue()
    assert "Ingestion" in out
    assert "#1" in out
    assert "SCANNING" in out


def test_repr_html_contains_status_and_id(client):
    client.create_ingestion.return_value = make_ingestion_model(
        id=99, status="DONE", user="alice"
    )
    ing = IngestionResource.create(client, spec=b"")
    html = ing._repr_html_()
    assert isinstance(html, str)
    assert "#99" in html
    assert "DONE" in html


def test_render_includes_error_panel_when_errors_present(client):
    ing = IngestionResource.create(client, spec=b"")
    client.get_ingestion_errors.return_value = [
        make_error_model(severity="CRITICAL", description="boom"),
    ]
    ing.refresh()

    import io
    from rich.console import Console

    buf = io.StringIO()
    Console(file=buf, force_terminal=True, width=120).print(ing)
    out = buf.getvalue()
    assert "Errors" in out
    assert "CRITICAL" in out


# ---------------------------------------------------------------------------
# BatchResource
# ---------------------------------------------------------------------------


def test_batch_create_calls_create_batch(client):
    batch = BatchResource.create(client, ingestion_id=1)
    client.create_batch.assert_called_once_with(1)
    client.get_batch.assert_not_called()
    assert batch.batch_number == 1


def test_batch_from_number_calls_get_batch(client):
    BatchResource.from_number(client, ingestion_id=1, batch_number=3)
    client.get_batch.assert_called_once_with(1, 3)
    client.create_batch.assert_not_called()


def test_batch_properties_delegate(client):
    client.create_batch.return_value = make_batch_model(
        ingestion_id=42, batch_number=7, status="READY"
    )
    batch = BatchResource.create(client, ingestion_id=42)
    assert batch.ingestion_id == 42
    assert batch.batch_number == 7
    assert batch.status is models.Status.READY
    assert batch.started is None
    assert batch.finalized is None


def test_batch_listings_call_through(client):
    client.get_batch.return_value = make_batch_model(ingestion_id=1, batch_number=2)
    batch = BatchResource.from_number(client, ingestion_id=1, batch_number=2)
    batch.input_files()
    batch.output_files()
    batch.errors()
    client.get_batch_input_files.assert_called_with(1, 2)
    client.get_batch_output_files.assert_called_with(1, 2)
    client.get_batch_errors.assert_called_with(1, 2)


def test_batch_start_updates_state(client):
    client.get_batch.return_value = make_batch_model(ingestion_id=1, batch_number=2)
    client.start_batch.return_value = make_batch_model(
        ingestion_id=1, batch_number=2, status="INGESTING"
    )
    batch = BatchResource.from_number(client, ingestion_id=1, batch_number=2)
    batch.start()
    client.start_batch.assert_called_once_with(1, 2)
    assert batch.status is models.Status.INGESTING


def test_batch_wait_until_done(mocker: MockerFixture, client):
    batch = BatchResource.from_number(client, ingestion_id=1, batch_number=1)
    client.get_batch.side_effect = [
        make_batch_model(status="INGESTING"),
        make_batch_model(status="DONE"),
    ]
    mocker.patch("prescient_sdk.ingest_client.time.sleep")

    batch.wait_until_done(poll_interval=0.01)
    assert batch.status is models.Status.DONE


def test_batch_render_produces_expected_text(client):
    client.create_batch.return_value = make_batch_model(
        ingestion_id=42, batch_number=7, status="READY"
    )
    batch = BatchResource.create(client, ingestion_id=42)

    import io
    from rich.console import Console

    buf = io.StringIO()
    Console(file=buf, force_terminal=True, width=120).print(batch)
    out = buf.getvalue()
    assert "Batch" in out
    assert "#42" in out
    assert "#7" in out
    assert "READY" in out
