"""Pydantic models for the Prescient Ingest API.

These mirror the schemas defined in the Ingest API OpenAPI specification
and are returned by :class:`prescient_sdk.ingest_client.IngestClient`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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


class TaskType(str, Enum):
    """Type of a task in an ingestion specification."""

    TRANSFORM = "transform"
    MOVE = "move"
    THUMBNAIL = "thumbnail"
    STAC = "stac"


class Location(BaseModel):
    path: str


class SourceFileSet(BaseModel):
    location: str
    pattern: str
    stac_item_subexpression: int | None = None


class Task(BaseModel):
    type: TaskType
    input_location: str
    input_format: str | None = None
    input_subdataset: str | None = None
    output_format: str | None = None
    output_path_template: str | None = None
    output_location: str | None = None
    output_crs: str | None = None
    output_nodata: float | None = None
    output_color_table: str | None = None
    fail: bool | None = None
    delay: float | None = None


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


class StacProvider(BaseModel):
    name: str
    description: str | None = None
    roles: list[str] | None = None
    url: str | None = None


class StacAsset(BaseModel):
    asset_src: str | None = None
    type: str | None = None
    title: str | None = None
    roles: list[str] | None = None
    extra_fields: dict[str, Any] | None = None


class StacLink(BaseModel):
    rel: str
    href: str
    type: str | None = None
    title: str | None = None
    method: str | None = None
    headers: dict[str, str] | None = None
    body: str | None = None


class StacExtent(BaseModel):
    spatial: dict[str, list[list[float]]]
    temporal: dict[str, list[list[str | None]]]


class StacItem(BaseModel):
    properties_location: str | None = None
    properties_file: str | None = None
    links_location: str | None = None
    links_file: str | None = None
    assets: dict[str, StacAsset] = Field(default_factory=dict)
    links: list[StacLink] = Field(default_factory=list)


class StacCollection(BaseModel):
    id: str | None = None
    type: str = "Collection"
    stac_version: str | None = None
    title: str | None = None
    description: str | None = None
    license: str | None = None
    stac_extensions: list[str] | None = None
    keywords: list[str] | None = None
    providers: list[StacProvider] | None = None
    extent: StacExtent | None = None
    links: list[StacLink] | None = None


class Stac(BaseModel):
    collection: StacCollection | None = None
    item: StacItem | None = None


class IngestionSpec(BaseModel):
    user: str
    version: str | None = None
    name: str | None = None
    locations: dict[str, Location] = Field(default_factory=dict)
    source_file_sets: dict[str, SourceFileSet] = Field(default_factory=dict)
    tasks: dict[str, Task] = Field(default_factory=dict)
    stac: Stac | None = None


class Ingestion(BaseModel):
    id: int
    status: Status
    spec: IngestionSpec


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
