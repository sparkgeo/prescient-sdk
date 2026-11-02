# Migrate to version 1.0

Version 1.0 of the Prescient SDK works with the multi-tenant Prescient platform. You sign in with an API key for your Organization. Microsoft and Google sign-in, AWS credentials and the S3 upload are removed.

Version 1.0 needs Python 3.11 or later.

## Before you start

You need:

- The URL of your Organization host, for example `https://<org>.<env>.prescient.earth`.
- A user account in your Organization.

## Create an API key

1. Open the Keycloak Account Console of your Organization:
   `https://keycloak.prescient.earth/realms/<org>/account`.
   For a staging Organization, use `https://keycloak.staging.prescient.earth/realms/<org>/account`.
   `<org>` is the first part of your Organization host name.
2. Sign in with your Organization user account.
3. In the sidebar, click **API Keys**.
4. Create a key. You can set an expiry date.
5. Copy the key. It starts with `pk_`. The console shows the key only once.

Keep the key secret. Do not put it in a notebook or commit it to a repository. Put it in an environment variable or in a `config.env` file that is not under version control.

If the key expires or you revoke it, the SDK raises `PrescientAuthError`. Create a new key.

## Update your settings

Version 1.0 has three settings:

| Setting | Required | Value |
| --- | --- | --- |
| `prescient_endpoint_url` | Yes | Your Organization host, for example `https://<org>.<env>.prescient.earth` |
| `prescient_api_key` | Yes | Your API key (`pk_...`) |
| `prescient_auth_url` | No | The Keycloak base URL. If you do not set it, the SDK uses `https://keycloak.staging.prescient.earth` for a host that contains `staging`, and `https://keycloak.prescient.earth` for all other hosts |

If your environment or `config.env` file contains a setting from an earlier version, the SDK raises a `ValueError` that names the setting. Remove each setting in this table:

| Earlier setting | Version 1.0 |
| --- | --- |
| `prescient_auth_provider` | Removed. The API key is the only way to sign in |
| `prescient_client_id` | Removed |
| `prescient_tenant_id` | Removed |
| `prescient_google_client_secret` | Removed |
| `prescient_google_redirect_port` | Removed |
| `prescient_aws_role` | Removed. You read data with the access token, not AWS credentials |
| `prescient_aws_region` | Removed |
| `prescient_upload_role` | Removed. Upload is not available in 1.0 |
| `prescient_upload_bucket` | Removed. Upload is not available in 1.0 |
| `prescient_auth_token_path` | Removed |
| `prescient_ingest_endpoint_url` | Removed. The Ingest API is always at `<prescient_endpoint_url>/ingest/` |
| `prescient_auth_url` | Changed meaning. It was the OAuth token endpoint. Now it is the Keycloak base URL, for example `https://keycloak.prescient.earth`. Remove it unless you use a Keycloak server at a different URL |

A `config.env` file for version 1.0:

```
PRESCIENT_ENDPOINT_URL="https://<org>.<env>.prescient.earth"
PRESCIENT_API_KEY="pk_..."
```

## Update your code

You can import the public names from the package root, for example `from prescient_sdk import PrescientClient, IngestClient`. The module paths also still work.

### PrescientClient

| Earlier API | Version 1.0 |
| --- | --- |
| `client.stac_catalog_url` | `client.stac_url`. It is `<prescient_endpoint_url>/stac` |
| `client.headers` | Still exists. It returns `{"Authorization": "Bearer <token>"}` with a fresh token each time you read it |
| `client.session` (a `boto3.Session`) | Removed. `client.session` is now a `requests.Session` that sends the access token |
| `client.bucket_credentials` | Removed |
| `client.upload_session` | Removed |
| `client.auth_credentials`, `client.credentials_expired`, `client.refresh_credentials()` | Removed. The client exchanges the API key for a new token when the current token is about to expire |
| `prescient_sdk.upload.upload()` | Removed. Upload is not available in 1.0 |

New in version 1.0:

- `client.request_modifier`: pass it to pystac-client, for example `Client.open(client.stac_url, request_modifier=client.request_modifier)`.
- `client.auth`: a `requests` auth object for other libraries.

### Read data

STAC asset links point at the platform file proxy over HTTPS. To read data, send the access token in an `Authorization` header. You do not need AWS credentials. See the [STAC search example](examples/stac_search.ipynb).

### Upload

Upload is not available in version 1.0. A version 1.x release will add an uploader for the platform file proxy. Until then, `IngestSpec.with_uploaded_sources` needs an `uploader` function that you supply.

### IngestClient

| Earlier API | Version 1.0 |
| --- | --- |
| `IngestClient(prescient_client=..., env_file=..., settings=..., debug=..., log_file=...)` | `IngestClient(client=None, organization=None)`. Pass a `PrescientClient` as `client`. If you do not, the SDK makes one from your environment and `config.env`. Only a super admin sets `organization` |
| `ingest_client.headers` | Removed. Every request uses `client.session` |
| `ingest_client.wait_for_status(...)` | Removed. Use `IngestResource` or `BatchResource`, and call `wait_until_ready()` or `wait_until_done()` |
| `Status.INCOMPLETE` | Removed. A finished ingestion or batch is `DONE` or `FAILED` |
| HTTP errors as `requests.HTTPError` | `IngestAPIError`, a subclass of `requests.HTTPError`. `IngestSpecError` for a rejected spec (400) and `CollectionOwnershipError` for a collection that another Organization owns (409) |

### Ingestion specs

The Ingest API accepts only version 2 specs:

- Set `version: "2.0.0"`. Quote the value in YAML.
- Remove the `user` field. The Organization comes from your API key.
- A location `path` with no scheme, for example `lidar/2026`, is a path in your Organization bucket.

`IngestSpec.problems()` lists the problems that the SDK can find before you submit a spec. See the [ingest example](examples/ingest.ipynb).
