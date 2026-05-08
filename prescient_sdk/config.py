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

    prescient_aws_region: str = Field()
    prescient_aws_role: str = Field(min_length=20)

    prescient_auth_provider: Literal["microsoft", "google"] = "microsoft"
    prescient_client_id: str
    prescient_auth_url: str
    prescient_auth_token_path: str

    # Microsoft-specific (required when prescient_auth_provider="microsoft")
    prescient_tenant_id: str | None = None

    # Google-specific (required when prescient_auth_provider="google")
    prescient_google_client_secret: str | None = None

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
