from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


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

    prescient_tenant_id: str
    prescient_client_id: str
    prescient_auth_url: str
    prescient_auth_token_path: str

    model_config = SettingsConfigDict(
        env_file="config.env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
    )