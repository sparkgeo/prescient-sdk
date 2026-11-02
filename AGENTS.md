# AGENTS.md

Guidance for coding agents working in this repository.

Shared standards for every Prescient repo: @../prescient-platform/AGENTS.md. Follow them; this file adds only what is specific to this repo.

## What this repo is

`prescient-sdk`, the Python client that users install from PyPI and conda-forge to sign in to Prescient and call its APIs. On `main` it does three things: get an identity token, get temporary S3 credentials, and upload a directory to the upload bucket. It was written against the legacy platform and has no Keycloak or Organization support yet.

`main` is the released line (0.4.x). `develop` carries the 0.5.0 pre-releases: an `IngestClient` (`prescient_sdk/ingest_client.py`), ingest models and resources, `IngestSpec`, a `justfile` in place of the `Makefile`, and logging. The `IngestClient` exists only on `develop`. Issue [sparkgeo/prescient-sdk#77](https://github.com/sparkgeo/prescient-sdk/issues/77) tracks updating it for the MT ingestion API and spec v2. Check which branch you are on before you trust anything below.

## Sibling repos

Cloned next to this one, under `../`.

| Path | What you need from it |
| --- | --- |
| `../prescient-platform/` | Shared standards, ADRs and service docs. ADR-020 and ADR-021 define MT ingestion, which #77 targets |
| `../prescient-platform-services/` | The MT STAC, fileproxy, titiler and (planned) ingestion APIs this SDK calls. Its `AGENTS.md` holds the platform glossary |
| `../prescient-platform-authentication-providers/` | Keycloak realms and the API key provider. `docs/api-keys.md` defines how MT accepts API keys |

## Commands

```sh
uv sync                          # install with dev dependencies
uv run pytest                    # all tests (make run-tests)
uv run ruff check                # what CI checks
uv run ruff format               # format (make format runs check, then format)
uv run jupyter-book build docs/  # docs to docs/_build/html
uv build                         # sdist and wheel, as publish.yaml does
```

## Conventions

- Packaging: hatchling, uv, one `uv.lock`. `requires-python = ">=3.9"` and CI tests 3.9 to 3.12. Use `from __future__ import annotations` for `X | None` hints. Publish and docs jobs use `.python-version` (3.12).
- Public API: `prescient_sdk/__init__.py` is empty. Users import `prescient_sdk.client.PrescientClient`, `prescient_sdk.config.Settings` and `prescient_sdk.upload.upload` by module path. A rename there breaks users and the notebooks in `docs/examples/`.
- Settings: pydantic-settings, no env prefix, case insensitive. Every field is `prescient_*`. Sources are env vars, then `config.env` in the working directory, or an `env_file` passed to `PrescientClient`.
- Auth modes, chosen in `config.py`:
  - `prescient_api_key` set: no IdP. Sends the key in an `api-key` header. Upload raises `NotImplementedError`, and `prescient_aws_role` is ignored.
  - `prescient_auth_provider = "microsoft"` (default): MSAL interactive login, then refresh token.
  - `prescient_auth_provider = "google"`: `InstalledAppFlow` on a loopback port, then refresh token.
- The client sends the IdP `id_token`, not the access token, as `Authorization: Bearer`.
- Credentials are lazy properties on `PrescientClient` and are cached until `credentials_expired`.
- Tests: pytest with `pytest-mock`. MSAL and the Google flow are patched, STS is a botocore `Stubber`, S3 is `moto`. No test makes a network call. Keep it that way.
- Docs: Jupyter Book in `docs/`. The reference pages are `automodule` stubs, so docstrings are the docs. Notebooks are not executed in the build (`execute_notebooks: off`).
- Release: set the version in `pyproject.toml`, merge to `main`, then create a GitHub release tagged `vX.Y.Z`. The tag triggers `publish.yaml` (PyPI) and `deploy-book.yaml`. A tag with an `a`, `b` or `rc` suffix deploys the docs to `/dev/`. conda-forge is a manual step; see `README.md`.

## Traps

- **Token expiry is fixed, not read.** `client.py` sets `_expiration_duration` to one hour from the time of login. It ignores the token's own `exp`. Bucket credential expiry is also ignored for caching; only the auth expiry counts.
- **Two STS paths.** `_fetch_sts_credentials` (read bucket) and `_get_bucket_credentials` (upload bucket) both call `assume_role_with_web_identity`. Change both, or neither.
- **`urljoin` drops paths.** `stac_catalog_url` and the fileproxy URL use `urljoin`. An endpoint URL with a path but no trailing slash loses its last segment. The Google flow joins absolute paths (`/o/oauth2/token`), so any path in `prescient_auth_url` is dropped.
- **The `api-key` header may not reach MT.** The MT gateway docs (`prescient-platform-authentication-providers/docs/api-keys.md`) name `X-API-Key` or an `api-key` query parameter. Nobody has tested the SDK's `api-key` header against MT.
- **`/fileproxy/credentials` is not in MT fileproxy.** The routes in `prescient-platform-services/packages/prescient-fileproxy/src/prescient/fileproxy/routes/` do not include it. The fallback for read credentials works only where some other deployment serves that path.
- **`make update-binder-reqs`** writes to `.binder/`, which does not exist. `make build-docs` calls `jupyter-book` without `uv run`.
- `tests/test_client.py` redefines several fixtures from `tests/conftest.py`. The local copy wins in that file.

## Language

Platform terms (Organization, User, roles, Collection) are in the `## Language` section of `../prescient-platform-services/AGENTS.md`. SDK-only terms:

**Bucket credentials**:
Temporary AWS keys for reading platform buckets. They come from STS when `prescient_aws_role` is set, and from `/fileproxy/credentials` otherwise.

**Upload bucket**:
The bucket named by `prescient_upload_bucket`. `upload()` writes to it with credentials from `prescient_upload_role`. Object keys start with the input directory's name.

**API key mode**:
The client configured with `prescient_api_key`. No IdP, no STS, no upload. In v2 there is no other mode: the API key is how the SDK signs in.

**API key**:
A long-lived secret (`pk_...`) that a User creates for one Organization. The SDK trades it for a short-lived access token and never sends the key to the platform APIs.

**Organization host**:
The hostname `<org>.<env>.prescient.earth` that names one Organization. A token from one Organization is not valid at another's host.

## Integrations

### Microsoft Entra ID

| | |
| --- | --- |
| Service type | Identity provider, external |
| Direction | Outbound |
| Source | `prescient_sdk/client.py` `_fetch_microsoft_credentials` |
| Transport | REST over HTTPS, via `msal` |
| Protocol | OAuth 2.0 / OpenID Connect, public client, interactive browser login |
| Authentication | User signs in. Later calls use the refresh token |
| Authorization | Scope `https://graph.microsoft.com/.default` |
| Credentials | `prescient_client_id`, `prescient_tenant_id`, `prescient_auth_url` from settings. No secret |
| Failure mode | No `id_token` in the response raises `ValueError` |
| Criticality | Hard dependency in Microsoft mode |

### Google OAuth

| | |
| --- | --- |
| Service type | Identity provider, external |
| Direction | Outbound, plus a loopback listener for the redirect |
| Source | `prescient_sdk/client.py` `_fetch_google_credentials` |
| Transport | REST over HTTPS; local HTTP server on `prescient_google_redirect_port` (8765) |
| Protocol | OAuth 2.0 / OpenID Connect, installed-app flow |
| Authentication | User signs in. Later calls use the refresh token |
| Authorization | Scopes `openid`, `userinfo.email` |
| Credentials | `prescient_client_id`, `prescient_google_client_secret`, `prescient_auth_url` from settings |
| Failure mode | No `id_token` raises `ValueError`; refresh errors propagate from `google-auth` |
| Criticality | Hard dependency in Google mode |

### Keycloak

Not supported on `main` or `develop`. MT signs users in through one Keycloak realm per Organization, so MT login needs new code. Issue [#57](https://github.com/sparkgeo/prescient-sdk/issues/57) tracks adding Keycloak as an auth provider.

On `v2-multi-tenant` (planned, not built yet), the API key exchange replaces Microsoft and Google:

| | |
| --- | --- |
| Service type | Identity provider, Prescient platform |
| Direction | Outbound |
| Source | Planned on `v2-multi-tenant` |
| Transport | REST over HTTPS |
| Protocol | `POST <keycloak>/realms/<org>/api-keys/exchange` with header `X-API-Key`. Returns `{access_token, token_type, expires_in}`, no refresh token (`../prescient-platform-authentication-providers/docs/api-keys.md`) |
| Authentication | The user's API key (`pk_...`), created in the Keycloak Account Console of their Organization's realm |
| Authorization | Key belongs to a User in the realm. The token carries `aud` `prescient`, `organization` and `username`, which the services require |
| Credentials | `prescient_api_key` from settings. Realm is the Organization, taken from the first DNS label of `prescient_endpoint_url`. Keycloak base URL is `prescient_auth_url` when set; otherwise `https://keycloak.staging.prescient.earth` if the endpoint host contains `staging`, else `https://keycloak.prescient.earth` |
| Failure mode | 401/403 (key invalid, expired or revoked) raises `PrescientAuthError`. 429 above 60 exchanges per minute per key raises with `Retry-After`, no retry. The limit is checked before Keycloak's token cache, so the SDK caches the token and re-exchanges within 60 s of `exp`, and never sends `X-API-Key` to the gateway. Tokens last 5 minutes today; [prescient-platform-applications#428](https://github.com/sparkgeo/prescient-platform-applications/issues/428) raises that to about 1 hour |
| Criticality | Hard dependency |

### Prescient MT platform APIs (v2, planned)

| | |
| --- | --- |
| Service type | Prescient platform, internal |
| Direction | Outbound |
| Source | Planned on `v2-multi-tenant`: `client.session`, `client.auth`, `client.request_modifier`, `IngestClient` |
| Transport | REST over HTTPS, through the Organization's Envoy gateway at the Organization host |
| Protocol | HTTP, JSON. `/stac` (STAC API), `/fileproxy/stac/...` (asset reads; STAC hrefs already point here), `/raster` (titiler), `/ingest/v1/...` (MT ingestion, part of the Organization chart, deployed on staging for `spk-sandbox`) |
| Authentication | `Authorization: Bearer <access_token>` from the API key exchange above |
| Authorization | Services check `iss`, `aud` `prescient`, `organization` and `username`. Roles are decided by the platform |
| Credentials | Access token from the exchange. Base URL from `prescient_endpoint_url` |
| Failure mode | A 401 on a call made through `client.session` forces one re-exchange and one retry, then raises. Calls from other libraries through `client.auth` get a fresh token per request and no retry |
| Criticality | Hard dependency |

Interactive login (device code or PKCE) needs a public client in every org realm, which does not exist yet. It is a follow-up in `prescient-platform-applications`.

### Prescient platform APIs (STAC, fileproxy)

| | |
| --- | --- |
| Service type | Prescient platform, internal |
| Direction | Outbound |
| Source | `prescient_sdk/client.py`: `stac_catalog_url`, `headers`, `_fetch_fileproxy_credentials` |
| Transport | REST over HTTPS |
| Protocol | HTTP, JSON. STAC searches are made by the user's own client (for example `pystac-client`) with `client.headers` |
| Authentication | `Authorization: Bearer <id_token>`, or `api-key` header in API key mode |
| Authorization | Decided by the platform. unknown how the legacy platform checks the token |
| Credentials | Token from the IdP above, or `prescient_api_key` from settings. Base URL from `prescient_endpoint_url` |
| Failure mode | `GET fileproxy/credentials` calls `raise_for_status()`; no retry, no timeout |
| Criticality | Hard dependency |

### AWS STS

| | |
| --- | --- |
| Service type | AWS STS, external |
| Direction | Outbound |
| Source | `prescient_sdk/client.py` `_fetch_sts_credentials`, `_get_bucket_credentials` |
| Transport | AWS API over HTTPS, via `boto3` |
| Protocol | `AssumeRoleWithWebIdentity`, 1 hour sessions |
| Authentication | The IdP `id_token` as the web identity token |
| Authorization | The role's trust policy. Roles from `prescient_aws_role` (read) and `prescient_upload_role` (upload) |
| Credentials | Role ARNs and `prescient_aws_region` from settings |
| Failure mode | Empty `Credentials` raises `ValueError`; boto errors propagate |
| Criticality | Hard dependency for S3 access when a role is set, and always for upload |

### S3 (asset and upload buckets)

| | |
| --- | --- |
| Service type | AWS S3, external |
| Direction | Outbound: read through `client.session`, write through `upload()` |
| Source | `prescient_sdk/client.py` `session`, `upload_session`; `prescient_sdk/upload.py` |
| Transport | S3 REST over HTTPS, via `boto3` |
| Protocol | AWS SigV4 |
| Authentication | Temporary keys from STS or `/fileproxy/credentials` |
| Authorization | IAM policy on the assumed role. unknown beyond that |
| Credentials | Bucket credentials above. Upload bucket from `prescient_upload_bucket` |
| Failure mode | Upload is sequential with no retry. `overwrite=False` skips keys that already exist, so a failed run can resume |
| Criticality | Hard dependency for data access and upload |
