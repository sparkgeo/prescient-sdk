import importlib

import pytest

import prescient_sdk

PUBLIC_NAMES = {
    "BatchResource": "prescient_sdk.ingest_resources",
    "CollectionOwnershipError": "prescient_sdk.ingest_client",
    "IngestAPIError": "prescient_sdk.ingest_client",
    "IngestClient": "prescient_sdk.ingest_client",
    "IngestResource": "prescient_sdk.ingest_resources",
    "IngestSpec": "prescient_sdk.ingest_spec",
    "IngestSpecError": "prescient_sdk.ingest_client",
    "LiveStatus": "prescient_sdk.ingest_resources",
    "PrescientAuthError": "prescient_sdk.client",
    "PrescientClient": "prescient_sdk.client",
    "Settings": "prescient_sdk.config",
}


def test_all_lists_exactly_the_public_names():
    assert sorted(prescient_sdk.__all__) == sorted(PUBLIC_NAMES)


@pytest.mark.parametrize("name,module", sorted(PUBLIC_NAMES.items()))
def test_name_imports_from_root_and_module(name, module):
    from_root = getattr(prescient_sdk, name)
    from_module = getattr(importlib.import_module(module), name)
    assert from_root is from_module


def test_star_import_exports_all():
    namespace: dict = {}
    exec("from prescient_sdk import *", namespace)
    assert set(PUBLIC_NAMES) <= namespace.keys()
