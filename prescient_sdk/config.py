import os
import urllib.parse
from typing import Any

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIGRATION_URL = "https://sparkgeo.github.io/prescient-sdk/migration.html"

REMOVED_SETTINGS = (
    "prescient_auth_provider",
    "prescient_client_id",
    "prescient_tenant_id",
    "prescient_google_client_secret",
    "prescient_google_redirect_port",
    "prescient_aws_role",
    "prescient_aws_region",
    "prescient_upload_role",
    "prescient_upload_bucket",
    "prescient_auth_token_path",
    "prescient_ingest_endpoint_url",
)


class Settings(BaseSettings):
    """
    Configuration for the Prescient SDK.

    Configuration is handled using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

    Order of precedence for configuration values:

    1. Environment variables are always highest precedence and will override any other configuration values
    2. `config.env` file: if a `config.env` file is present in the root of the project, it will be used

    Settings from SDK versions before 1.0 (for example `prescient_client_id` or
    `prescient_aws_role`) are rejected with a `ValueError`. See the
    [migration guide](https://sparkgeo.github.io/prescient-sdk/migration.html).
    """

    prescient_endpoint_url: str = Field(
        description=(
            "Base URL of your Organization host, for example "
            "`https://<org>.<env>.prescient.earth`."
        )
    )

    prescient_api_key: SecretStr = Field(
        description=(
            "Your API key (`pk_...`). Create it in the Keycloak Account Console "
            "of your Organization. The SDK exchanges it for a short-lived access token."
        ),
    )

    prescient_auth_url: str | None = Field(
        default=None,
        description=(
            "Optional Keycloak base URL. When unset, it is derived from "
            "`prescient_endpoint_url`."
        ),
    )

    model_config = SettingsConfigDict(
        env_file="config.env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        # Validation errors would otherwise echo all input, including the API key.
        hide_input_in_errors=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_removed_settings(cls, data: Any) -> Any:
        # Init kwargs and env file keys arrive in `data` (pydantic-settings passes
        # unknown dotenv keys through); unknown env vars do not, so check os.environ.
        names = {key.lower() for key in [*data, *os.environ]}
        found = sorted(names.intersection(REMOVED_SETTINGS))
        if found:
            raise ValueError(
                f"Settings removed in prescient-sdk 1.0: {', '.join(found)}. "
                f"Remove them from your environment and env file. See {MIGRATION_URL}"
            )
        return data

    @property
    def realm(self) -> str:
        """The Keycloak realm, which is the first DNS label of the endpoint host.

        Returns:
            str: The realm name, for example `spk-sandbox` for
            `https://spk-sandbox.staging.prescient.earth`.
        """
        host = urllib.parse.urlsplit(self.prescient_endpoint_url).hostname or ""
        return host.split(".")[0]

    @property
    def keycloak_url(self) -> str:
        """The Keycloak base URL, without a trailing slash.

        Returns:
            str: `prescient_auth_url` when set. Otherwise
            `https://keycloak.staging.prescient.earth` when the endpoint host
            contains `staging`, else `https://keycloak.prescient.earth`.
        """
        if self.prescient_auth_url:
            return self.prescient_auth_url.rstrip("/")
        host = urllib.parse.urlsplit(self.prescient_endpoint_url).hostname or ""
        if "staging" in host:
            return "https://keycloak.staging.prescient.earth"
        return "https://keycloak.prescient.earth"
