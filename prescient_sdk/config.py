from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator


class Settings(BaseSettings):
    """
    Default configuration for the Prescient SDK.

    Configuration is handled using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

    Order of precedence for configuration values:

    1. Environment variables are always highest precedence and will override any other configuration values
    2. `config.env` file: if a `config.env` file is present in the root of the project, it will be used
    """

    prescient_endpoint_url: str = Field()

    # Optional. When set, the client assumes this role via STS to obtain bucket
    # credentials. When unset, the client fetches temporary credentials from
    # the Prescient API's /fileproxy/credentials endpoint instead.
    prescient_aws_role: str | None = Field(default=None, min_length=20)
    prescient_aws_region: str | None = Field(default=None)

    # Optional. Required only when using the upload helpers (upload_session,
    # upload_bucket_credentials, prescient_sdk.upload.upload).
    prescient_upload_role: str | None = Field(
        default=None, min_length=20, description="AWS ARN role upload bucket"
    )
    prescient_upload_bucket: str | None = Field(
        default=None, description="AWS S3 upload bucket name"
    )

    prescient_auth_provider: Literal["microsoft", "google"] = "microsoft"
    prescient_client_id: str
    prescient_auth_url: str

    # Not used, but required for backwards compatibility. TODO Schedule deprecation.
    prescient_auth_token_path: str | None = None

    # Microsoft-specific (required when prescient_auth_provider="microsoft")
    prescient_tenant_id: str | None = None

    # Google-specific (required when prescient_auth_provider="google")
    prescient_google_client_secret: str | None = None

    # Google-specific, optional. Set to the registered loopback port when using a
    # Web-application OAuth client. Leave as None for Desktop-app OAuth clients,
    # which permit any random local port.
    prescient_google_redirect_port: int | None = 8765

    model_config = SettingsConfigDict(
        env_file="config.env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_provider_fields(self) -> "Settings":
        if self.prescient_auth_provider == "microsoft" and not self.prescient_tenant_id:
            raise ValueError(
                "prescient_tenant_id is required when prescient_auth_provider is 'microsoft'"
            )
        if self.prescient_auth_provider == "google" and not self.prescient_google_client_secret:
            raise ValueError(
                "prescient_google_client_secret is required when prescient_auth_provider is 'google'"
            )
        return self
