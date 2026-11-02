"""Pydantic models for the Prescient Ingest API.

These mirror the response schemas of the multi-tenant (MT) ingestion service
(``prescient.ingestion.schemas`` in prescient-platform-services) and are
returned by :class:`prescient_sdk.ingest_client.IngestClient`.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class Status(str, Enum):
    """Status of an ingestion or batch."""

    SCANNING = "SCANNING"
    READY = "READY"
    PLANNING = "PLANNING"
    INGESTING = "INGESTING"
    DONE = "DONE"
    FAILED = "FAILED"


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
    stac_item_id: str
    source_file_set: str | None = None


class OutputFile(BaseModel):
    """A file produced by an ingestion task for one STAC item."""

    stac_item_id: str
    task_name: str
    status: FileStatus
    path: str | None = None


class StacItem(BaseModel):
    """A STAC item an ingestion writes, and whether it has been written."""

    stac_item_id: str
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
    started: datetime | None
    finalized: datetime | None
    status: Status


class Error(BaseModel):
    """An error or warning recorded against an ingestion."""

    severity: ErrorSeverity
    time_occurred: datetime
    description: str
    ingestion_id: int
    location: str | None = None
    task: str | None = None
    input_file: InputFile | None = None
    stack_trace: str | None = None


# Targets for "wait until the create/scan phase resolves": anything that
# ends SCANNING. A scan that finds no input files goes straight to DONE.
READY_STATUSES: frozenset[Status] = frozenset(
    {Status.READY, Status.DONE, Status.FAILED}
)

# Targets for "wait until ingestion finishes": READY is no longer a stop
# condition once ingestion has been started.
DONE_STATUSES: frozenset[Status] = frozenset({Status.DONE, Status.FAILED})
