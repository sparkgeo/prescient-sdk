# AGENTS.md

Guidance for coding agents working in this repository.

Shared standards for every Prescient repo: @../prescient-platform/AGENTS.md. Follow them; this file adds only what is specific to this repo.

## What this repo is

`prescient-sdk`, the Python client that users install from PyPI and conda-forge to call the Prescient multi-tenant (MT) platform. It signs in with an API key, gives users an authenticated `requests` session and helpers for STAC and asset reads, and wraps the MT ingestion API (`IngestClient`, `IngestResource`, `BatchResource`, `IngestSpec` for version 2 specs).

`v2-multi-tenant` carries 1.0.0, a clean break from the legacy platform: no MSAL, Google, STS, boto3 or S3 upload. `main` is the released 0.4.x line for the legacy platform and `develop` the 0.5.0 pre-releases; neither has API key exchange or MT support. Check which branch you are on before you trust anything below. Users moving to 1.0 follow `docs/migration.md`.

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
- Upload: the SDK ships no uploader. `prescient_sdk/upload.py` selects files; `IngestSpec.with_uploaded_sources` takes a caller-supplied `uploader`.
- Tests: pytest with `pytest-mock`. HTTP is mocked by patching `requests.post` and `requests.Session.send`. No test makes a network call. Keep it that way. There is no boto3 or moto.
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
| Protocol | HTTP, JSON. `/stac` (STAC API, called by the user's own pystac-client), `/fileproxy/stac/...` (asset reads; STAC hrefs already point here), `/raster` (titiler), `/ingest/v1/...` and `/ingest/healthz` (MT ingestion, part of the Organization chart, deployed on staging for `spk-sandbox`) |
| Authentication | `Authorization: Bearer <access_token>` from the API key exchange above |
| Authorization | Services check `iss`, `aud` `prescient`, `organization` and `username`. Roles are decided by the platform; creating and starting an ingestion needs an Organization admin. A super admin passes `organization` (`IngestClient(organization=...)`), sent as a query parameter |
| Credentials | Access token from the exchange. Base URL from `prescient_endpoint_url` |
| Failure mode | A 401 on a call made through `client.session` forces one re-exchange and one retry, then returns the response. Calls from other libraries through `client.auth`, `headers` or `request_modifier` get a fresh token per request and no retry. `IngestClient` raises `IngestAPIError` for any status of 400 or more: `IngestSpecError` for 400 and `CollectionOwnershipError` for 409 on create. No timeout on `IngestClient` requests except `check` (10 s) |
| Criticality | Hard dependency |
