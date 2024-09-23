
import logging
import datetime
import urllib.parse
from pathlib import Path

import msal
import boto3
from rasterio.session import AWSSession

from prescient_sdk.config import Settings

logger = logging.getLogger("prescient_sdk")


class PrescientClient:
    """
    Client for interacting with the Prescient API.

    This client is used to authenticate using Azure AD, and for obtaining AWS
    credentials using the Azure AD access token. The client also provides helpers such as
    provding the STAC URL for the Prescient API, and authentication headers for making
    requests to the STAC API.

    Token expiration (both AWS and Azure) is handled automatically for long running instances
    of the client (in a notebook for example).

    Configuration Options:
        1. Construct the `prescient_sdk.config.Settings` object directly
        2. Specify the path to an environment file containing configuration values
        3. Do neither, and allow the client to build the `Settings` object using default
           methods (env variables, config.env file location in the working directory)

        Note that you cannot specify the env_file location AND provide a `Settings` object.

    Args:
        env_file (str | Path, optional): Path to a configuration file. Defaults to None.
        settings (Settings, optional): Configuration settings for the client. Defaults to None.

    Raises:
        ValueError: If both an environment file and a settings object are provided.
        ValueError: If the provided configuration file is not found.

    """

    def __init__(
        self,
        env_file: str | Path | None = None,
        settings: Settings | None = None,
    ):
        if env_file and settings:
            raise ValueError(
                "Cannot provide both an environment file and a settings object"
            )

        if env_file:
            env_file = Path(env_file)
            if env_file.exists():
                logger.info(f"Loading configuration variables from {env_file}")
            else:
                raise ValueError(f"Configuration file not found: {env_file}")

        # default configuration values are set in the Settings class (prescient_sdk.config.py)
        if settings is None:
            if env_file:
                settings = Settings(_env_file=env_file)  # type: ignore
            else:
                # if no env file is present, we use default settings 
                # which can be sourced from a config.env file in the working 
                # directory, or env variables
                settings = Settings()  # type: ignore
        self.settings: Settings = settings

        # initialize empty credentials
        self._azure_credentials: dict = {}
        self._aws_credentials: dict = {}

    @property
    def stac_catalog_url(self) -> str:
        """
        Get the STAC URL.

        Returns:
            str: The STAC URL.
        """
        return urllib.parse.urljoin(self.settings.endpoint_url, "stac")

    @property
    def azure_credentials(self) -> dict:
        """
        Get the Azure credentials for the client.

        Returns:
            dict: Azure access token::

                {
                    "token_type": "string",
                    "scope": "string",
                    "expires_in": "int",
                    "ext_expires_in": "int",
                    "access_token": "string",
                    "refresh_token": "string",
                    "id_token": "string",
                    "client_info": "string",
                    "id_token_claims": {
                        "aud": "string",
                        "iss": "string",
                        "iat": "int",
                        "nbf": "int",
                        "exp": "int",
                        "aio": "string",
                        "name": "string",
                        "nonce": "string",
                        "oid": "string",
                        "preferred_username": "string",
                        "rh": "string",
                        "roles": ["string"],
                        "sub": "string",
                        "tid": "string",
                        "uti": "string",
                        "ver": "string",
                    },
                    "token_source": "string",
                }
        Raises:
            ValueError: If the response status code is not 200, or if the access token is not in the response.
        """
        # return cached credentials if they exist and are not expired
        if "expiration" in self._azure_credentials and (
            datetime.datetime.now(datetime.timezone.utc)
            < self._azure_credentials["expiration"]
        ):
            return self._azure_credentials

        authority_url = urllib.parse.urljoin(
            self.settings.azure_auth_url, self.settings.azure_tenant_id
        )
        app = msal.PublicClientApplication(
            client_id=self.settings.azure_client_id, authority=authority_url
        )

        # trigger auth or auth refresh flow
        time_zero = datetime.datetime.now(datetime.timezone.utc)
        if not self._azure_credentials:
            # aquire creds interactively if none have been fetched yet
            self._azure_credentials = app.acquire_token_interactive(scopes=[])
        else:
            # refresh creds if they have been fetched before and are expired
            self._azure_credentials = app.acquire_token_by_refresh_token(
                refresh_token=self._azure_credentials["refresh_token"], scopes=[]
            )

        # check that a nonzero length token has been obtained
        token: str = self._azure_credentials.get("id_token", "")
        if token == "":
            raise ValueError(f"Failed to obtain Azure token: {self._azure_credentials}")

        # set expiration time of the token
        self._azure_credentials["expiration"] = time_zero + datetime.timedelta(
            seconds=self._azure_credentials["expires_in"]
        )

        return self._azure_credentials

    @property
    def headers(self) -> dict:
        """
        Get headers for a request, including the auth header with a bearer token.

        Returns:
            dict: The headers.
        """
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.azure_credentials['id_token']}",
        }

    @property
    def aws_credentials(self):
        """Get AWS credentials using Azure AD access token

        Returns:
            dict: AWS temporary credentials::

                {
                    "AccessKeyId": "string",
                    "SecretAccessKey": "string",
                    "SessionToken": "string",
                    "Expiration": datetime(2015, 1, 1)
                }

        Raises:
            ValueError: If the AWS credentials response is empty
        """
        if (
            "Expiration" in self._aws_credentials
            and datetime.datetime.now(datetime.timezone.utc)
            < self._aws_credentials["Expiration"]
        ):
            return self._aws_credentials

        access_token = self.azure_credentials.get("id_token")
        sts_client = boto3.client("sts", region_name=self.settings.aws_region)

        # exchange token with aws temp creds
        response: dict = sts_client.assume_role_with_web_identity(
            DurationSeconds=3600,  # 1 hour
            RoleArn=self.settings.aws_role,
            RoleSessionName="prescient-s3-access",
            WebIdentityToken=access_token,
        )
        self._aws_credentials = response.get("Credentials", {})

        if not self._aws_credentials:
            raise ValueError(f"Failed to obtain AWS creds: {response}")

        # convert datetime to UTC for later comparison
        self._aws_credentials["Expiration"] = self._aws_credentials[
            "Expiration"
        ].astimezone(datetime.timezone.utc)

        return self._aws_credentials
    
    @property
    def session(self) -> AWSSession:
        """
        Get an AWS session to be used when authenticating rasterio

        Returns:
            AWSSession: Rasterio AWS session
        """
        return AWSSession(
            aws_access_key_id=self.aws_credentials["AccessKeyId"], 
            aws_secret_access_key=self.aws_credentials["SecretAccessKey"], 
            aws_session_token=self.aws_credentials["SessionToken"]
        )
