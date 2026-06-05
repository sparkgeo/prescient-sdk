"""High-level resource classes built on top of :class:`IngestClient`.

These wrap an ingestion (and its batches) as stateful Python objects with
a small observer hook so external code can react to state changes.
Construction goes through the classmethods ``create`` / ``from_id`` /
``from_number`` so the network call is visible at the call site.

For a live, auto-updating Rich progress display, wrap a resource in
:class:`LiveStatus` — display lifecycle lives there, not on the resource.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prescient_sdk import ingest_models as models
from prescient_sdk.ingest_client import IngestClient, _poll_for_status
from prescient_sdk.ingest_models import (
    DONE_STATUSES,
    READY_STATUSES,
    Error,
    ErrorSeverity,
    InputFile,
    OutputFile,
    Status,
)

logger = logging.getLogger("prescient_sdk")


STATUS_STYLES: dict[Status, str] = {
    Status.SCANNING: "yellow",
    Status.READY: "bold green",
    Status.PLANNING: "yellow",
    Status.INGESTING: "bold cyan",
    Status.DONE: "bold green",
    Status.FAILED: "bold red",
    Status.INCOMPLETE: "bold yellow",
}

SEVERITY_STYLES: dict[ErrorSeverity, str] = {
    ErrorSeverity.CRITICAL: "bold red",
    ErrorSeverity.INGESTION_FAILURE: "bold red",
    ErrorSeverity.LOCATION_FAILURE: "red",
    ErrorSeverity.FILE_FAILURE: "red",
    ErrorSeverity.TASK_FAILURE: "yellow",
    ErrorSeverity.TASK_ERROR: "yellow",
    ErrorSeverity.WARNING: "dim",
}


def _status_badge(status: Status) -> Text:
    return Text(status.value, style=STATUS_STYLES.get(status, ""))


def _errors_panel(errors: list[Error]) -> Panel | None:
    """Build a small table summarizing errors by severity. Returns None if empty."""
    if not errors:
        return None

    counts: dict[ErrorSeverity, int] = {}
    last_by_severity: dict[ErrorSeverity, str] = {}
    for err in errors:
        counts[err.severity] = counts.get(err.severity, 0) + 1
        last_by_severity[err.severity] = err.description

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Severity")
    table.add_column("Count", justify="right")
    table.add_column("Latest")
    for severity in sorted(counts, key=lambda s: s.value):
        table.add_row(
            Text(severity.value, style=SEVERITY_STYLES.get(severity, "")),
            str(counts[severity]),
            last_by_severity[severity][:80],
        )
    return Panel(table, title="Errors", title_align="left", border_style="red")


_RefreshCallback = Callable[["_IngestResource"], None]


class _IngestResource:
    """Shared state + observer machinery for :class:`IngestionResource` and :class:`BatchResource`.

    Subclasses cache a pydantic model, expose status/listings, and notify
    registered observers each time the model changes (via ``refresh()`` or
    ``start()``). The class is intentionally display-agnostic — wrap it in
    :class:`LiveStatus` to get a Rich live progress display.
    """

    def __init__(self, client: IngestClient):
        self._client = client
        self._errors: list[Error] = []
        self._observers: list[_RefreshCallback] = []

    # -- Subclass hooks --------------------------------------------------

    @property
    def status(self) -> Status:
        raise NotImplementedError

    def _fetch_model(self) -> Any:
        raise NotImplementedError

    def _set_model(self, model: Any) -> None:
        raise NotImplementedError

    def _fetch_errors(self) -> list[Error]:
        raise NotImplementedError

    def _render(self) -> RenderableType:
        raise NotImplementedError

    def _fetch_status_carrier(self) -> Any:
        """Return the object whose ``.status`` is checked by the poller.

        Subclasses return their cached pydantic model.
        """
        raise NotImplementedError

    # -- Observers -------------------------------------------------------

    def on_refresh(self, callback: _RefreshCallback) -> _RefreshCallback:
        """Register a callback fired after every ``refresh()`` and ``start()``.

        Returns the callback unchanged so it can be passed to
        :meth:`off_refresh` when unsubscribing.
        """
        self._observers.append(callback)
        return callback

    def off_refresh(self, callback: _RefreshCallback) -> None:
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(self) -> None:
        for cb in self._observers:
            cb(self)

    # -- Lifecycle -------------------------------------------------------

    def refresh(self) -> "_IngestResource":
        """Re-fetch the underlying model + errors and notify observers."""
        logger.debug("Refreshing %s", self.__class__.__name__)
        self._set_model(self._fetch_model())
        self._errors = self._fetch_errors()
        self._notify()
        return self

    def _wait(
        self,
        target_statuses: Iterable[Status],
        poll_interval: float,
        timeout: float,
    ) -> "_IngestResource":
        # Drive the shared polling helper with a fetcher that refreshes this
        # resource on every iteration. Observers (e.g. LiveStatus) fire via
        # refresh() each tick.
        logger.info(
            "Waiting for %s to reach %s (timeout=%ss)",
            self.__class__.__name__,
            sorted(s.value for s in target_statuses),
            timeout,
        )

        def fetcher() -> Any:
            self.refresh()
            return self._fetch_status_carrier()

        _poll_for_status(fetcher, target_statuses, poll_interval, timeout)
        return self

    # -- Rich integrations (cheap, no lifecycle) -------------------------

    def __rich__(self) -> RenderableType:
        return self._render()

    def _repr_html_(self) -> str:
        """Render to HTML for Jupyter when displayed bare (no LiveStatus)."""
        console = Console(record=True, file=io.StringIO(), force_jupyter=False)
        console.print(self._render())
        return console.export_html(inline_styles=True)


class IngestionResource(_IngestResource):
    """A Prescient ingestion as a stateful Python resource.

    Construct via :meth:`create` (POST a new ingestion) or :meth:`from_id`
    (attach to an existing one). Wrap in :class:`LiveStatus` for a live
    progress display::

        ing = IngestionResource.create(client, spec="spec.yaml")
        with LiveStatus(ing):
            ing.wait_until_ready()
            if not ing.errors():
                ing.start().wait_until_done()
    """

    def __init__(self, client: IngestClient, model: models.Ingestion):
        super().__init__(client)
        self._model: models.Ingestion = model

    # -- Constructors ----------------------------------------------------

    @classmethod
    def create(
        cls, client: IngestClient, spec: Path | str | bytes
    ) -> "IngestionResource":
        """POST a new ingestion from ``spec`` and wrap the result."""
        ingestion = client.create_ingestion(spec)
        logger.info("IngestionResource created id=%s", ingestion.id)
        return cls(client, ingestion)

    @classmethod
    def from_id(cls, client: IngestClient, id: int) -> "IngestionResource":
        """GET an existing ingestion by ID and wrap it."""
        return cls(client, client.get_ingestion(id))

    # -- Identity / state ------------------------------------------------

    @property
    def id(self) -> int:
        return self._model.id

    @property
    def status(self) -> Status:
        return self._model.status

    @property
    def spec(self) -> dict[str, Any]:
        return self._model.spec

    # -- Listings (always fresh) -----------------------------------------

    def input_files(self) -> list[InputFile]:
        return self._client.get_ingestion_input_files(self.id)

    def output_files(self) -> list[OutputFile]:
        return self._client.get_ingestion_output_files(self.id)

    def errors(self) -> list[Error]:
        return self._client.get_ingestion_errors(self.id)

    # -- State transitions -----------------------------------------------

    def start(self) -> "IngestionResource":
        logger.info("Starting ingestion id=%s", self.id)
        self._set_model(self._client.start_ingestion(self.id))
        self._notify()
        return self

    def wait_until_ready(
        self, poll_interval: float = 5.0, timeout: float = 300.0
    ) -> "IngestionResource":
        self._wait(READY_STATUSES, poll_interval, timeout)
        return self

    def wait_until_done(
        self, poll_interval: float = 10.0, timeout: float = 3600.0
    ) -> "IngestionResource":
        self._wait(DONE_STATUSES, poll_interval, timeout)
        return self

    # -- Batches ---------------------------------------------------------

    def create_batch(self) -> "BatchResource":
        """POST a new batch under this ingestion."""
        return BatchResource.create(self._client, self.id)

    def list_batches(self) -> list["BatchResource"]:
        """Return ``BatchResource`` wrappers for every batch under this ingestion."""
        return [
            BatchResource(self._client, m)
            for m in self._client.list_batches(self.id)
        ]

    # -- Internals -------------------------------------------------------

    def _set_model(self, model: models.Ingestion) -> None:
        self._model = model

    def _fetch_model(self) -> models.Ingestion:
        return self._client.get_ingestion(self.id)

    def _fetch_errors(self) -> list[Error]:
        return self._client.get_ingestion_errors(self.id)

    def _fetch_status_carrier(self) -> models.Ingestion:
        return self._model

    def _render(self) -> RenderableType:
        header = Table.grid(padding=(0, 1))
        header.add_column()
        header.add_column()
        header.add_row(
            Text(f"Ingestion #{self.id}", style="bold"),
            _status_badge(self.status),
        )

        spec = self.spec
        spec_table = Table.grid(padding=(0, 2))
        spec_table.add_column(style="dim")
        spec_table.add_column()
        spec_table.add_row("User", str(spec.get("user", "—")))
        spec_table.add_row("Tasks", str(len(spec.get("tasks") or {})))
        spec_table.add_row("Locations", str(len(spec.get("locations") or {})))
        spec_table.add_row("Source file sets", str(len(spec.get("source_file_sets") or {})))

        renderables: list[RenderableType] = [header, spec_table]
        errs_panel = _errors_panel(self._errors)
        if errs_panel is not None:
            renderables.append(errs_panel)
        return Panel(Group(*renderables), title="Ingestion", title_align="left")


class BatchResource(_IngestResource):
    """A single ingestion batch as a stateful Python resource.

    Construct via :meth:`create` (POST a new batch under an ingestion) or
    :meth:`from_number` (attach to an existing batch). Most users will get
    a ``BatchResource`` back from :meth:`IngestionResource.create_batch`.
    Wrap in :class:`LiveStatus` for a live progress display.
    """

    def __init__(self, client: IngestClient, model: models.Batch):
        super().__init__(client)
        self._model: models.Batch = model

    # -- Constructors ----------------------------------------------------

    @classmethod
    def create(cls, client: IngestClient, ingestion_id: int) -> "BatchResource":
        """POST a new batch under ``ingestion_id`` and wrap the result."""
        batch = client.create_batch(ingestion_id)
        logger.info(
            "BatchResource created ingestion=%s batch=%s",
            ingestion_id,
            batch.batch_number,
        )
        return cls(client, batch)

    @classmethod
    def from_number(
        cls, client: IngestClient, ingestion_id: int, batch_number: int
    ) -> "BatchResource":
        """GET an existing batch and wrap it."""
        return cls(client, client.get_batch(ingestion_id, batch_number))

    # -- Identity / state ------------------------------------------------

    @property
    def ingestion_id(self) -> int:
        return self._model.ingestion_id

    @property
    def batch_number(self) -> int:
        return self._model.batch_number

    @property
    def status(self) -> Status:
        return self._model.status

    @property
    def created(self) -> datetime:
        return self._model.created

    @property
    def started(self) -> datetime | None:
        return self._model.started

    @property
    def finalized(self) -> datetime | None:
        return self._model.finalized

    # -- Listings --------------------------------------------------------

    def input_files(self) -> list[InputFile]:
        return self._client.get_batch_input_files(self.ingestion_id, self.batch_number)

    def output_files(self) -> list[OutputFile]:
        return self._client.get_batch_output_files(
            self.ingestion_id, self.batch_number
        )

    def errors(self) -> list[Error]:
        return self._client.get_batch_errors(self.ingestion_id, self.batch_number)

    # -- State transitions -----------------------------------------------

    def start(self) -> "BatchResource":
        logger.info(
            "Starting batch ingestion=%s batch=%s", self.ingestion_id, self.batch_number
        )
        self._set_model(
            self._client.start_batch(self.ingestion_id, self.batch_number)
        )
        self._notify()
        return self

    def wait_until_ready(
        self, poll_interval: float = 5.0, timeout: float = 300.0
    ) -> "BatchResource":
        self._wait(READY_STATUSES, poll_interval, timeout)
        return self

    def wait_until_done(
        self, poll_interval: float = 10.0, timeout: float = 3600.0
    ) -> "BatchResource":
        self._wait(DONE_STATUSES, poll_interval, timeout)
        return self

    # -- Internals -------------------------------------------------------

    def _set_model(self, model: models.Batch) -> None:
        self._model = model

    def _fetch_model(self) -> models.Batch:
        return self._client.get_batch(self.ingestion_id, self.batch_number)

    def _fetch_errors(self) -> list[Error]:
        return self._client.get_batch_errors(self.ingestion_id, self.batch_number)

    def _fetch_status_carrier(self) -> models.Batch:
        return self._model

    def _render(self) -> RenderableType:
        header = Table.grid(padding=(0, 1))
        header.add_column()
        header.add_column()
        header.add_row(
            Text(
                f"Ingestion #{self.ingestion_id} · Batch #{self.batch_number}",
                style="bold",
            ),
            _status_badge(self.status),
        )

        ts_table = Table.grid(padding=(0, 2))
        ts_table.add_column(style="dim")
        ts_table.add_column()
        ts_table.add_row("Created", self.created.isoformat())
        ts_table.add_row("Started", self.started.isoformat() if self.started else "—")
        ts_table.add_row(
            "Finalized", self.finalized.isoformat() if self.finalized else "—"
        )

        renderables: list[RenderableType] = [header, ts_table]
        errs_panel = _errors_panel(self._errors)
        if errs_panel is not None:
            renderables.append(errs_panel)
        return Panel(Group(*renderables), title="Batch", title_align="left")


class LiveStatus:
    """Render a live, auto-updating Rich display of a resource's status.

    Wraps any :class:`IngestionResource` or :class:`BatchResource`. Use as a
    context manager — the display starts on ``__enter__``, refreshes after
    every ``refresh()`` and ``start()`` on the wrapped resource, and
    finalizes on ``__exit__``. The resource itself remains fully usable
    outside the block (without the live display)::

        ing = IngestionResource.create(client, spec="spec.yaml")
        with LiveStatus(ing):
            ing.wait_until_ready()
            if not ing.errors():
                ing.start().wait_until_done()
    """

    def __init__(
        self,
        resource: _IngestResource,
        *,
        console: Console | None = None,
        refresh_per_second: int = 4,
    ):
        self._resource = resource
        self._live = Live(
            resource._render(),
            console=console or Console(),
            refresh_per_second=refresh_per_second,
        )

    def __enter__(self) -> _IngestResource:
        logger.debug(
            "LiveStatus started for %s", self._resource.__class__.__name__
        )
        self._live.start()
        self._resource.on_refresh(self._on_refresh)
        return self._resource

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._resource.off_refresh(self._on_refresh)
        # Best-effort final refresh; never mask the caller's exception.
        try:
            self._resource.refresh()
        except Exception:
            pass
        try:
            self._live.update(self._resource._render(), refresh=True)
        finally:
            self._live.stop()
        logger.debug("LiveStatus stopped")
        return False

    def _on_refresh(self, _resource: _IngestResource) -> None:
        self._live.update(self._resource._render(), refresh=True)
