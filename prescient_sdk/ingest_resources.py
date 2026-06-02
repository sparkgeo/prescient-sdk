"""High-level resource classes built on top of :class:`IngestClient`.

These wrap an ingestion (and its batches) as stateful Python objects with
context-manager support and a live, readable progress display in both
notebooks and terminals.
"""

from __future__ import annotations

import io
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prescient_sdk import ingest_models as models
from prescient_sdk.ingest import IngestClient
from prescient_sdk.ingest_models import (
    Error,
    ErrorSeverity,
    InputFile,
    IngestionSpec,
    OutputFile,
    Status,
)


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


class _IngestResource:
    """Shared lifecycle / display machinery for :class:`Ingestion` and :class:`Batch`."""

    def __init__(self, client: IngestClient):
        self._client = client
        self._console = Console()
        self._live: Live | None = None
        self._errors: list[Error] = []

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

    # -- Lifecycle -------------------------------------------------------

    def refresh(self) -> "_IngestResource":
        """Re-fetch the underlying model + errors and update any live display."""
        self._set_model(self._fetch_model())
        self._errors = self._fetch_errors()
        self._update_display()
        return self

    def _wait(
        self,
        target_statuses: Iterable[Status],
        poll_interval: float,
        timeout: float,
    ) -> "_IngestResource":
        targets = set(target_statuses)
        deadline = time.monotonic() + timeout
        while True:
            self.refresh()
            if self.status in targets:
                return self
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Status {self.status.value!r} did not reach "
                    f"{sorted(s.value for s in targets)} within {timeout}s"
                )
            time.sleep(poll_interval)

    # -- Context manager -------------------------------------------------

    def __enter__(self) -> "_IngestResource":
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
        )
        self._live.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            self.refresh()
        except Exception:
            # Best-effort final refresh; never mask the user's own exception.
            pass
        live = self._live
        self._live = None
        if live is not None:
            try:
                live.update(self._render(), refresh=True)
            finally:
                live.stop()
        return False

    def _update_display(self) -> None:
        if self._live is not None:
            self._live.update(self._render(), refresh=True)

    # -- Rich integrations -----------------------------------------------

    def __rich__(self) -> RenderableType:
        return self._render()

    def _repr_html_(self) -> str:
        """Render to HTML for Jupyter when the object is displayed bare (no `with`)."""
        console = Console(record=True, file=io.StringIO(), force_jupyter=False)
        console.print(self._render())
        return console.export_html(inline_styles=True)


class Ingestion(_IngestResource):
    """A Prescient ingestion as a stateful Python resource.

    Construct with exactly one of ``spec`` (to create a new ingestion) or
    ``id`` (to attach to an existing one). Use as a context manager to get
    a live, auto-updating progress display::

        with Ingestion(client, spec="spec.yaml") as ing:
            ing.wait_until_ready()
            if not ing.errors():
                ing.start().wait_until_done()
    """

    def __init__(
        self,
        client: IngestClient,
        *,
        spec: Path | str | bytes | None = None,
        id: int | None = None,
    ):
        if (spec is None) == (id is None):
            raise ValueError("Provide exactly one of `spec` or `id`")
        super().__init__(client)
        if spec is not None:
            self._model: models.Ingestion = client.create_ingestion(spec)
        else:
            assert id is not None
            self._model = client.get_ingestion(id)

    # -- Identity / state ------------------------------------------------

    @property
    def id(self) -> int:
        return self._model.id

    @property
    def status(self) -> Status:
        return self._model.status

    @property
    def spec(self) -> IngestionSpec:
        return self._model.spec

    # -- Listings (always fresh) -----------------------------------------

    def input_files(self) -> list[InputFile]:
        return self._client.get_ingestion_input_files(self.id)

    def output_files(self) -> list[OutputFile]:
        return self._client.get_ingestion_output_files(self.id)

    def errors(self) -> list[Error]:
        return self._client.get_ingestion_errors(self.id)

    # -- State transitions -----------------------------------------------

    def start(self) -> "Ingestion":
        self._set_model(self._client.start_ingestion(self.id))
        self._update_display()
        return self

    def wait_until_ready(
        self, poll_interval: float = 5.0, timeout: float = 300.0
    ) -> "Ingestion":
        self._wait(
            [Status.READY, Status.FAILED, Status.INCOMPLETE], poll_interval, timeout
        )
        return self

    def wait_until_done(
        self, poll_interval: float = 10.0, timeout: float = 3600.0
    ) -> "Ingestion":
        self._wait(
            [Status.DONE, Status.FAILED, Status.INCOMPLETE], poll_interval, timeout
        )
        return self

    # -- Batches ---------------------------------------------------------

    def create_batch(self) -> "Batch":
        """Create a new batch under this ingestion."""
        return Batch._from_model(
            self._client, self._client.create_batch(self.id)
        )

    def list_batches(self) -> list["Batch"]:
        """Return ``Batch`` wrappers for every batch belonging to this ingestion."""
        return [
            Batch._from_model(self._client, m)
            for m in self._client.list_batches(self.id)
        ]

    # -- Internals -------------------------------------------------------

    def _set_model(self, model: models.Ingestion) -> None:
        self._model = model

    def _fetch_model(self) -> models.Ingestion:
        return self._client.get_ingestion(self.id)

    def _fetch_errors(self) -> list[Error]:
        return self._client.get_ingestion_errors(self.id)

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
        spec_table.add_row("User", spec.user)
        spec_table.add_row("Tasks", str(len(spec.tasks)))
        spec_table.add_row("Locations", str(len(spec.locations)))
        spec_table.add_row("Source file sets", str(len(spec.source_file_sets)))

        renderables: list[RenderableType] = [header, spec_table]
        errs_panel = _errors_panel(self._errors)
        if errs_panel is not None:
            renderables.append(errs_panel)
        return Panel(Group(*renderables), title="Ingestion", title_align="left")


class Batch(_IngestResource):
    """A single ingestion batch as a stateful Python resource.

    Construct with an ``ingestion_id`` and either a ``batch_number`` (to
    attach to an existing batch) or no batch number (to create a new
    batch). Most users will get a ``Batch`` back from
    :meth:`Ingestion.create_batch` rather than constructing one directly.
    """

    def __init__(
        self,
        client: IngestClient,
        *,
        ingestion_id: int,
        batch_number: int | None = None,
    ):
        super().__init__(client)
        if batch_number is None:
            self._model: models.Batch = client.create_batch(ingestion_id)
        else:
            self._model = client.get_batch(ingestion_id, batch_number)

    @classmethod
    def _from_model(cls, client: IngestClient, model: models.Batch) -> "Batch":
        """Internal: build a ``Batch`` wrapping an already-fetched pydantic model."""
        obj = cls.__new__(cls)
        _IngestResource.__init__(obj, client)
        obj._model = model
        return obj

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

    def start(self) -> "Batch":
        self._set_model(
            self._client.start_batch(self.ingestion_id, self.batch_number)
        )
        self._update_display()
        return self

    def wait_until_ready(
        self, poll_interval: float = 5.0, timeout: float = 300.0
    ) -> "Batch":
        self._wait(
            [Status.READY, Status.FAILED, Status.INCOMPLETE], poll_interval, timeout
        )
        return self

    def wait_until_done(
        self, poll_interval: float = 10.0, timeout: float = 3600.0
    ) -> "Batch":
        self._wait(
            [Status.DONE, Status.FAILED, Status.INCOMPLETE], poll_interval, timeout
        )
        return self

    # -- Internals -------------------------------------------------------

    def _set_model(self, model: models.Batch) -> None:
        self._model = model

    def _fetch_model(self) -> models.Batch:
        return self._client.get_batch(self.ingestion_id, self.batch_number)

    def _fetch_errors(self) -> list[Error]:
        return self._client.get_batch_errors(self.ingestion_id, self.batch_number)

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
