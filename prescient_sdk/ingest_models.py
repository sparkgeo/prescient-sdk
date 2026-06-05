"""Pydantic models for the Prescient Ingest API.

These mirror the schemas defined in the Ingest API OpenAPI specification
and are returned by :class:`prescient_sdk.ingest_client.IngestClient`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class Status(str, Enum):
    """Status of an ingestion or batch."""

    SCANNING = "SCANNING"
    READY = "READY"
    PLANNING = "PLANNING"
    INGESTING = "INGESTING"
    DONE = "DONE"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class FileStatus(str, Enum):
    """Status of an individual output file."""

    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


class ErrorSeverity(str, Enum):
    """The severity and scope of an error."""

    CRITICAL = "CRITICAL"
    INGESTION_FAILURE = "INGESTION_FAILURE"
    LOCATION_FAILURE = "LOCATION_FAILURE"
    FILE_FAILURE = "FILE_FAILURE"
    TASK_FAILURE = "TASK_FAILURE"
    TASK_ERROR = "TASK_ERROR"
    WARNING = "WARNING"


class InputFile(BaseModel):
    location: str
    path: str
    last_modified: datetime
    stac_item_id: UUID
    source_file_set: str | None = None


class OutputFile(BaseModel):
    stac_item_id: UUID
    task_name: str
    status: FileStatus


class Ingestion(BaseModel):
    id: int
    status: Status
    spec: dict[str, Any]


class Batch(BaseModel):
    id: int
    ingestion_id: int
    batch_number: int
    created: datetime
    started: datetime | None
    finalized: datetime | None
    status: Status


class Error(BaseModel):
    severity: ErrorSeverity
    time_occurred: datetime
    description: str
    ingestion_id: int
    location: str | None
    task: str | None
    input_file: InputFile | None
    stack_trace: str | None


TERMINAL_STATUSES: frozenset[Status] = frozenset(
    {Status.READY, Status.DONE, Status.FAILED, Status.INCOMPLETE}
)

# Targets for "wait until the create/scan phase resolves" — anything that
# ends SCANNING/PLANNING.
READY_STATUSES: frozenset[Status] = frozenset(
    {Status.READY, Status.FAILED, Status.INCOMPLETE}
)

# Targets for "wait until ingestion finishes" — READY is no longer a stop
# condition once ingestion has been started.
DONE_STATUSES: frozenset[Status] = frozenset(
    {Status.DONE, Status.FAILED, Status.INCOMPLETE}
)
