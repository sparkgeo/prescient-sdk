# `from __future__ import annotations` defers annotation evaluation so the
# PEP 604 `X | Y` union syntax below works on Python 3.9. Remove this import
# once Python 3.9 support is dropped.
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("prescient_sdk")

# NOTE: Fields below use Optional[X] rather than `X | None` because Pydantic
# evaluates annotations at class-creation time and PEP 604 union syntax
# requires Python 3.10+. Switch to `X | None` once Python 3.9 support is dropped.


class Settings(BaseSettings):
    """
    Default configuration for the Prescient SDK.

    Configuration is handled using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

    Order of precedence for configuration values:

    1. Environment variables are always highest precedence and will override any other configuration values
    2. `config.env` file: if a `config.env` file is present in the root of the project, it will be used
    """

    prescient_endpoint_url: Optional[str] = Field(
        description="Base URL of the Prescient API endpoint."
    )

    prescient_api_key: Optional[str] | None = Field(
        default=None,
        description=(
            "Static API key for authenticating to Prescient endpoints. When set, "
            "the SDK skips the OAuth2/IDP flow and sends the key in the "
            "`api-key` request header. `prescient_aws_role` is ignored "
            "when ``prescient_api_key`` is set (STS requires an IDP id_token); "
            "bucket credentials are fetched from `/fileproxy/credentials` instead."
        ),
    )

    prescient_ingest_endpoint_url: Optional[str] = Field(
        default=None,
        description=(
            "Optional override for the Ingest API base URL. When unset, "
            "IngestClient falls back to $prescient_endpoint_url/ingest."
        ),
    )

    prescient_auth_provider: Literal["microsoft", "google"] = Field(
        default="microsoft",
        description="OAuth2 authentication provider. Determines which provider-specific fields are required.",
    )
    prescient_client_id: Optional[str] | None = Field(
        default=None,
        description=(
            "OAuth2 client ID issued by the selected authentication provider. "
            "Required when `prescient_api_key` is not set."
        ),
    )
    prescient_auth_url: Optional[str] | None = Field(
        default=None,
        description=(
            "OAuth2 token endpoint URL used to exchange credentials for access tokens. "
            "Required when `prescient_api_key` is not set."
        ),
    )

    prescient_auth_token_path: Optional[str] = Field(
        default=None,
        description="Deprecated. Retained for backwards compatibility; no longer used.",
    )

    prescient_tenant_id: Optional[str] = Field(
        default=None,
        description="Microsoft Entra tenant ID. Required when `prescient_auth_provider` is `microsoft`.",
    )

    prescient_google_client_secret: Optional[str] = Field(
        default=None,
        description="Google OAuth2 client secret. Required when `prescient_auth_provider` is `google`.",
    )
    prescient_google_redirect_port: Optional[int] = Field(
        default=8765,
        description=(
            "Loopback port for the Google OAuth2 redirect URI. Set to the registered "
            "port when using a Web-application OAuth client; leave as the default for "
            "Desktop-app OAuth clients, which permit any local port."
        ),
    )

    prescient_aws_role: Optional[str] = Field(
        default=None,
        min_length=20,
        description=(
            "Optional AWS IAM role ARN. When set, the client assumes this role via STS "
            "to obtain bucket credentials. When unset, the client fetches temporary "
            "credentials from the Prescient API's `/fileproxy/credentials` endpoint."
        ),
    )
    prescient_aws_region: Optional[str] = Field(
        default=None,
        description="AWS region used when assuming `prescient_aws_role`. Required only when that role is set.",
    )

    prescient_upload_role: Optional[str] = Field(
        default=None,
        min_length=20,
        description="Optional AWS IAM role ARN used by the upload helpers to write to the upload bucket.",
    )
    prescient_upload_bucket: Optional[str] = Field(
        default=None,
        description="Optional AWS S3 bucket name targeted by the upload helpers.",
    )

    model_config = SettingsConfigDict(
        env_file="config.env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_provider_fields(self) -> "Settings":
        if self.prescient_api_key:
            if self.prescient_aws_role:
                logger.warning(
                    "prescient_aws_role cannot be used with prescient_api_key; "
                    "STS requires an IDP id_token. Unset one of them. "
                    "prescient_aws_role will be ignored."
                )
            return self

        if not self.prescient_client_id:
            raise ValueError(
                "prescient_client_id is required when prescient_api_key is not set"
            )
        if not self.prescient_auth_url:
            raise ValueError(
                "prescient_auth_url is required when prescient_api_key is not set"
            )
        if self.prescient_auth_provider == "microsoft" and not self.prescient_tenant_id:
            raise ValueError(
                "prescient_tenant_id is required when prescient_auth_provider is 'microsoft'"
            )
        if (
            self.prescient_auth_provider == "google"
            and not self.prescient_google_client_secret
        ):
            raise ValueError(
                "prescient_google_client_secret is required when prescient_auth_provider is 'google'"
            )
        return self
