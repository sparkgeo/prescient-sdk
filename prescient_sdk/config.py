"""
Default configuration for the Prescient SDK.

Configuration is done using Dynaconf: https://www.dynaconf.com/

Order of precedence for configuration values:

1. Environment variables: env variables with the prefix `PRESCIENT_` will be used
2. `.env` file: if a `.env` file is present in the root of the project, it will be used
3. `config.yaml` file: if a `config.yaml` file is present in the root of the project, it will be used
    - the location of the config.yaml file can be overridden by setting the `PRESCIENT_CONFIG_FILE` env variable

Note that the prescient SDK will be configured using the configuration listed here by default, however,
it is possible to initialize the SDK with a custom configuration by passing a `Dynaconf`
object to the `PrescientClient` constructor.

To list all settings and their values, run the following command in the root of the project:
    dynaconf -i prescient_sdk.config.config list

    More commands are available in the Dynaconf documentation: https://www.dynaconf.com/


Configuration values:
- ENDPOINT_URL: URL for the Prescient API
- AWS_REGION: AWS region
- AWS_PROFILE: AWS profile
- STAC_API_URL: URL for the STAC API
- AZURE_TENANT_ID: Azure tenant ID
- AZURE_CLIENT_ID: Azure client ID
- AZURE_CLIENT_SECRET: Azure client secret
- AZURE_AUTH_URL: Azure auth URL
- AZURE_AUTH_TOKEN_PATH: Azure auth token path
- AZURE_CLIENT_SCOPE: Azure client scope
- DESTINATION_BUCKET_NAME: Destination bucket name for uploading files

"""

import os
from dynaconf import Dynaconf, Validator

config = Dynaconf(
    envvar_prefix="PRESCIENT",
    settings_files=[os.environ.get("PRESCIENT_CONFIG_FILE", "config.yaml")],
    load_dotenv=True,
    validators=[
        Validator(
            "ENDPOINT_URL",
            default="https://enexus.server-uat.prescient.earth",
            apply_default_on_none=True,
        ),
        Validator(
            "AWS_REGION",
            default=os.environ.get("AWS_REGION", "us-west-2"),
            apply_default_on_none=True,
        ),
        Validator(
            "AWS_PROFILE",
            default=os.environ.get("AWS_PROFILE", "default"),
            apply_default_on_none=True,
        ),
        Validator("AWS_ROLE", default=None, apply_default_on_none=True),

        Validator("AZURE_TENANT_ID", default=None, apply_default_on_none=True),
        Validator("AZURE_CLIENT_ID", default=None, apply_default_on_none=True),
        Validator("AZURE_CLIENT_SECRET", default=None, apply_default_on_none=True),
        Validator(
            "AZURE_AUTH_URL",
            default="https://login.microsoftonline.com/",
            apply_default_on_none=True,
        ),
        Validator(
            "AZURE_AUTH_TOKEN_PATH",
            default="/oauth2/v2.0/token",
            apply_default_on_none=True,
        ),
        Validator("AZURE_CLIENT_SCOPE", default=None, apply_default_on_none=True),
        Validator("DESTINATION_BUCKET_NAME", default=None, apply_default_on_none=True),
        Validator("REQUEST_TIMEOUT", default=15, apply_default_on_none=True),  # seconds
    ],
)
