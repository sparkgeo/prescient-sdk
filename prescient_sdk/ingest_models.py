"""Pydantic models for the Prescient Ingest API.

These mirror the schemas defined in the Ingest API OpenAPI specification
and are returned by :class:`prescient_sdk.ingest_client.IngestClient`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

# NOTE: Model fields below use Optional[X] rather than `X | None` because
# Pydantic evaluates annotations at class-creation time and PEP 604 union
# syntax requires Python 3.10+. Switch to `X | None` once Python 3.9 support
# is dropped.


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
    """An input file discovered during the scan phase of an ingestion."""

    location: str
    path: str
    last_modified: datetime
    stac_item_id: UUID
    source_file_set: Optional[str] = None


class OutputFile(BaseModel):
    """A STAC item produced by an ingestion task."""

    stac_item_id: UUID
    task_name: str
    status: FileStatus


class Ingestion(BaseModel):
    """A top-level ingestion plus its current status and submitted spec."""

    id: int
    status: Status
    spec: dict[str, Any]


class Batch(BaseModel):
    """A single batch within an ingestion, including its lifecycle timestamps."""

    id: int
    ingestion_id: int
    batch_number: int
    created: datetime
    started: Optional[datetime]
    finalized: Optional[datetime]
    status: Status


class Error(BaseModel):
    """An error or warning recorded against an ingestion."""

    severity: ErrorSeverity
    time_occurred: datetime
    description: str
    ingestion_id: int
    location: Optional[str]
    task: Optional[str]
    input_file: Optional[InputFile]
    stack_trace: Optional[str]


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
