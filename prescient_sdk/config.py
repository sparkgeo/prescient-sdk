from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    Default configuration for the Prescient SDK.

    Configuration is handled using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

    Order of precedence for configuration values:

    1. Environment variables are always highest precedence and will override any other configuration values
    2. `.env` file: if a `.env` file is present in the root of the project, it will be used
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="PRESCIENT_"
    )

    endpoint_url: str = "https://enexus.server-uat.prescient.earth"
    aws_region: str = "us-west-2"
    aws_role: str = Field(
        min_length=20, default="00000000000000000000"
    )  # default role so that tests can run

    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    azure_client_secret: str | None = None

    azure_auth_url: str = "https://login.microsoftonline.com/"
    azure_auth_token_path: str = "/oauth2/v2.0/token"
    azure_client_scope: str | None = None

    request_timeout: int = 15  # seconds
