# AGENTS.md

Guidance for coding agents working in this repository.

Shared standards for every Prescient repo: @../prescient-platform/AGENTS.md. Follow them; this file adds only what is specific to this repo.

## What this repo is

`prescient-sdk`, the Python client that users install from PyPI and conda-forge to call the Prescient multi-tenant (MT) platform. It signs in with an API key, gives users an authenticated `requests` session and helpers for STAC and asset reads, and wraps the MT ingestion API (`IngestClient`, `IngestResource`, `BatchResource`, `IngestSpec` for version 2 specs).

`v2-multi-tenant` carries 1.0.0, a clean break from the legacy platform: no MSAL, Google or STS, and upload goes through credentials that fileproxy issues (ADR-025). `main` is the released 0.4.x line for the legacy platform and `develop` the 0.5.0 pre-releases; neither has API key exchange or MT support. Check which branch you are on before you trust anything below. Users moving to 1.0 follow `docs/migration.md`.

## Sibling repos

Cloned next to this one, under `../`.

| Path | What you need from it |
| --- | --- |
| `../prescient-platform/` | Shared standards, ADRs and service docs. ADR-020 and ADR-021 define MT ingestion, which #77 targets |
| `../prescient-platform-services/` | The MT STAC, fileproxy, titiler and ingestion APIs this SDK calls. Its `AGENTS.md` holds the platform glossary |
| `../prescient-platform-authentication-providers/` | Keycloak realms and the API key provider. `docs/api-keys.md` defines how MT accepts API keys |

## Commands

```sh
uv sync                          # install with dev dependencies
uv run pytest                    # all tests (just run-tests)
uv run ruff check                # what CI checks
uv run ruff format               # format (just format runs check, then format)
uv run jupyter-book build docs/  # docs to docs/_build/html
uv build                         # sdist and wheel, as publish.yaml does
```

## Conventions

- Packaging: hatchling, uv, one `uv.lock`. `requires-python = ">=3.11"` and CI tests 3.11 to 3.13. Write `X | None` hints directly; no `from __future__ import annotations`. Publish and docs jobs use `.python-version` (3.12).
- Public API: `prescient_sdk/__init__.py` re-exports the public names in `__all__`, and `tests/test_init.py` pins that list. Users import from the package root or the module path; both must keep working. A rename breaks users and the notebooks in `docs/examples/`.
- Settings: pydantic-settings, no env prefix, case insensitive. Three fields: `prescient_endpoint_url`, `prescient_api_key`, optional `prescient_auth_url`. Sources are env vars, then `config.env` in the working directory, or an `env_file` passed to `PrescientClient`. Settings removed in 1.0 are listed in `REMOVED_SETTINGS` in `config.py` and raise with a link to the migration page; add a name there when you remove a setting.
- Auth: API key only. `PrescientClient` exchanges the key with Keycloak for an access token, caches it, and sends `Authorization: Bearer <token>` through `session`, `auth`, `headers` and `request_modifier`. The key goes only to Keycloak, never to platform APIs.
- Upload: `prescient_sdk.uploads.upload` asks fileproxy for credentials and writes with boto3 (a required dependency). Without overwrite every write sends `If-None-Match: *`, and a 412 counts as skipped. Large files use the SDK's own multipart upload, because neither the boto3 transfer manager nor obstore sends `If-None-Match` on `CompleteMultipartUpload`. `IngestSpec.with_uploaded_sources` wraps `upload` for one spec location per call.
- Tests: pytest with `pytest-mock`. HTTP is mocked by patching `requests.post` and `requests.Session.send` (or `HTTPAdapter.send`). S3 is a botocore `Stubber` or a mock client; there is no moto. No test makes a network call. Keep it that way.
- Docs: Jupyter Book in `docs/`. The reference pages are `automodule` stubs, so docstrings are the docs. Notebooks are not executed in the build (`execute_notebooks: off`); commit them with outputs cleared.
- Release: set the version in `pyproject.toml`, merge to `main`, then create a GitHub release tagged `vX.Y.Z`. The tag triggers `publish.yaml` (PyPI) and `deploy-book.yaml`. A tag with an `a`, `b` or `rc` suffix deploys the docs to `/dev/`. conda-forge is a manual step; see `README.md`.

## Traps

- **Removed settings are read from the whole environment.** `Settings` checks `os.environ` for every name in `REMOVED_SETTINGS`, even when you pass values to `Settings(...)` directly. A stale `PRESCIENT_AWS_ROLE` in a shell makes every client fail. Tests that build `Settings` use the `clear_prescient_env` or `set_env_vars` fixture from `tests/conftest.py`.
- **GDAL cannot refresh the token.** The rasterio pattern in `docs/examples/stac_search.ipynb` puts a token in `GDAL_HTTP_HEADERS`. It expires with the token, and GDAL sends it to every host opened in that `rasterio.Env`.
- **The 401 retry skips streamed bodies.** `client.session` re-exchanges and resends once after a 401 only when the body is in memory (`None`, `str` or `bytes`). A file object or generator passed as `data=` is not resent.
- **`just update-binder-reqs`** writes to `.binder/`, which does not exist. `just build-docs` calls `jupyter-book` without `uv run`.

## Language

Platform terms (Organization, User, roles, Collection) are in the `## Language` section of `../prescient-platform-services/AGENTS.md`. SDK-only terms:

**API key**:
A long-lived secret (`pk_...`) that a User creates for one Organization. The SDK trades it for a short-lived access token and never sends the key to the platform APIs.

**Organization host**:
The hostname `<org>.<env>.prescient.earth` that names one Organization. A token from one Organization is not valid at another's host.

## Integrations

### Keycloak

MT signs users in through one Keycloak realm per Organization. The SDK uses the API key exchange.

| | |
| --- | --- |
| Service type | Identity provider, Prescient platform |
| Direction | Outbound |
| Source | `prescient_sdk/client.py` `PrescientClient._exchange`, `_access_token`; `prescient_sdk/config.py` `Settings.realm`, `Settings.keycloak_url` |
| Transport | REST over HTTPS, `requests.post`, 30 s timeout |
| Protocol | `POST <keycloak>/realms/<org>/api-keys/exchange` with header `X-API-Key`. Returns `{access_token, token_type, expires_in}`, no refresh token (`../prescient-platform-authentication-providers/docs/api-keys.md`) |
| Authentication | The user's API key (`pk_...`), created in the Keycloak Account Console of their Organization's realm |
| Authorization | Key belongs to a User in the realm. The token carries `aud` `prescient`, `organization` and `username`, which the services require |
| Credentials | `prescient_api_key` from settings. Realm is the Organization, taken from the first DNS label of `prescient_endpoint_url`. Keycloak base URL is `prescient_auth_url` when set; otherwise `https://keycloak.staging.prescient.earth` if the endpoint host contains `staging`, else `https://keycloak.prescient.earth` |
| Failure mode | 401/403 (key invalid, expired or revoked) raises `PrescientAuthError`. 429 above 60 exchanges per minute per key raises `PrescientAuthError` with `retry_after`, no retry. Other errors raise `requests.HTTPError`. The limit is checked before Keycloak's token cache, so the SDK caches the token and re-exchanges within 60 s of expiry (from `expires_in`), and never sends `X-API-Key` to the gateway. Tokens last 5 minutes today; [prescient-platform-applications#428](https://github.com/sparkgeo/prescient-platform-applications/issues/428) raises that to about 1 hour |
| Criticality | Hard dependency |

Interactive login (device code or PKCE) needs a public client in every org realm, which does not exist yet. It is a follow-up in `prescient-platform-applications`.

### Prescient MT platform APIs

| | |
| --- | --- |
| Service type | Prescient platform, internal |
| Direction | Outbound |
| Source | `prescient_sdk/client.py`: `PrescientClient.session` (`_ReauthSession`), `auth` (`_BearerAuth`), `headers`, `request_modifier`, `stac_url`. `prescient_sdk/ingest_client.py`: `IngestClient._request`, `check` |
| Transport | REST over HTTPS, through the Organization's Envoy gateway at the Organization host |
| Protocol | HTTP, JSON. `/stac` (STAC API, called by the user's own pystac-client), `/fileproxy/stac/...` (asset reads; STAC hrefs already point here), `POST /fileproxy/uploads` (upload credentials, see below), `/raster` (titiler), `/ingest/v1/...` and `/ingest/healthz` (MT ingestion, part of the Organization chart, deployed on staging for `spk-sandbox`) |
| Authentication | `Authorization: Bearer <access_token>` from the API key exchange above |
| Authorization | Services check `iss`, `aud` `prescient`, `organization` and `username`. Roles are decided by the platform; creating and starting an ingestion needs an Organization admin. A super admin passes `organization` (`IngestClient(organization=...)`), sent as a query parameter |
| Credentials | Access token from the exchange. Base URL from `prescient_endpoint_url` |
| Failure mode | A 401 on a call made through `client.session` forces one re-exchange and one retry, then returns the response. Calls from other libraries through `client.auth` or `request_modifier` get a fresh token per request and no retry. `client.headers` is a snapshot: read it again for each request, or the token expires. `IngestClient` raises `IngestAPIError` for any status of 400 or more: `IngestSpecError` for 400 and `CollectionOwnershipError` for 409 on create. `IngestClient` requests time out after 30 s by default (`check` after 10 s) |
| Criticality | Hard dependency |

### S3 (Organization bucket `uploads/`)

| | |
| --- | --- |
| Service type | AWS S3 |
| Direction | Outbound; writes only |
| Source | `prescient_sdk/uploads.py`: `upload`, `_issue_credentials`, `_s3_client`, `_upload_file` |
| Transport | S3 REST over HTTPS, boto3. `PutObject` for files up to 64 MiB; larger files are a multipart upload with 64 MiB parts (grown to stay under 10,000 parts), 4 parts at a time |
| Protocol | HTTPS, AWS SigV4, signed for the `region` fileproxy returns. The credentials cannot call HeadBucket, so botocore cannot find the region itself |
| Authentication | Temporary credentials from `POST /fileproxy/uploads` with `{location?, overwrite}`, through `client.session`. The response is `{location, bucket, region, prefix, access_key_id, secret_access_key, session_token, expiration}`; every field is required. botocore `RefreshableCredentials` call fileproxy again with the same body (and the issued location) before `expiration`; they last at most 1 hour |
| Authorization | Only `s3:PutObject` and `s3:AbortMultipartUpload` on `uploads/<location>/*`: no list, get or head. Without overwrite, a write without `If-None-Match: *` is denied |
| Payload | Each file at `prefix` + its forward-slash path relative to the local directory |
| Failure mode | Fileproxy errors raise `requests.HTTPError` (403 without the ingest permission, 422 for an invalid location). A 412 without overwrite counts as skipped; on a multipart upload it comes only at completion, after the parts are sent. Any other S3 error raises `ClientError`, and a failed multipart upload is aborted |
| Criticality | Hard dependency for upload; none for anything else |
