import logging
import datetime
import urllib.parse
from pathlib import Path

import msal
import boto3

from prescient_sdk.config import Settings

logger = logging.getLogger("prescient_sdk")


class PrescientClient:
    """
    Client for interacting with the Prescient API.

    This client is used to authenticate, and for obtaining bucket
    credentials using the authenticated token. The client also provides helpers such as
    provding the STAC URL for the Prescient API, and authentication headers for making
    requests to the STAC API.

    Token expiration is handled automatically for long running instances
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
        self._expiration_duration = 1 * 60 * 60  # Fixed to 1hr
        # initialize empty credentials
        self._auth_credentials: dict = {}
        self._bucket_credentials: dict = {}

    @property
    def stac_catalog_url(self) -> str:
        """
        Get the STAC URL.

        Returns:
            str: The STAC URL.
        """
        return urllib.parse.urljoin(self.settings.prescient_endpoint_url, "stac")

    @property
    def auth_credentials(self) -> dict:
        """
        Get the authorization credentials for the client.

        Returns:
            dict: access token::

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
        if not self.credentials_expired:
            return self._auth_credentials

        authority_url = urllib.parse.urljoin(
            self.settings.prescient_auth_url, self.settings.prescient_tenant_id
        )
        app = msal.PublicClientApplication(
            client_id=self.settings.prescient_client_id, authority=authority_url
        )

        # trigger auth or auth refresh flow
        time_zero = datetime.datetime.now(datetime.timezone.utc)
        if (
            not self._auth_credentials
            or "refresh_token" not in self._auth_credentials.keys()
        ):
            # aquire creds interactively if none have been fetched yet
            self._auth_credentials = app.acquire_token_interactive(
                scopes=["https://graph.microsoft.com/.default"]
            )
        else:
            # refresh creds if they have been fetched before and are expired
            self._auth_credentials = app.acquire_token_by_refresh_token(
                refresh_token=self._auth_credentials["refresh_token"],
                scopes=["https://graph.microsoft.com/.default"],
            )

        # check that a nonzero length token has been obtained
        token: str = self._auth_credentials.get("id_token", "")
        if token == "":
            raise ValueError(f"Failed to obtain Auth token: {self._auth_credentials}")

        # set expiration time of the token
        self._auth_credentials["expiration"] = time_zero + datetime.timedelta(
            seconds=self._expiration_duration
        )

        return self._auth_credentials

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
            "Authorization": f"Bearer {self.auth_credentials['id_token']}",
        }

    @property
    def bucket_credentials(self):
        """Get bucket credentials using an auth access token

        Returns:
            dict: bucket temporary credentials::

                {
                    "AccessKeyId": "string",
                    "SecretAccessKey": "string",
                    "SessionToken": "string",
                    "Expiration": datetime(2015, 1, 1)
                }

        Raises:
            ValueError: If the credentials response is empty
        """
        if self._bucket_credentials and not self.credentials_expired:
            return self._bucket_credentials

        access_token = self.auth_credentials.get("id_token")
        sts_client = boto3.client("sts", region_name=self.settings.prescient_aws_region)

        # exchange token with aws temp creds
        response: dict = sts_client.assume_role_with_web_identity(
            DurationSeconds=self._expiration_duration,
            RoleArn=self.settings.prescient_aws_role,
            RoleSessionName="prescient-s3-access",
            WebIdentityToken=access_token,
        )
        self._bucket_credentials = response.get("Credentials", {})

        if not self._bucket_credentials:
            raise ValueError(f"Failed to obtain creds: {response}")

        # convert datetime to UTC for later comparison
        self._bucket_credentials["Expiration"] = self._bucket_credentials[
            "Expiration"
        ].astimezone(datetime.timezone.utc)

        return self._bucket_credentials

    @property
    def session(self) -> boto3.Session:
        """
        Get an AWS session for authenticating to the bucket

        Returns:
            Session: boto3 Session object
        """
        return boto3.Session(
            aws_access_key_id=self.bucket_credentials["AccessKeyId"],
            aws_secret_access_key=self.bucket_credentials["SecretAccessKey"],
            aws_session_token=self.bucket_credentials["SessionToken"],
        )

    @property
    def credentials_expired(self) -> bool:
        """Checks to see if the client credentials have expired.
        Note: if auth credentials have expired, all credentials are considered
        expired as they all depend on auth credentials.

        Returns:
            bool: True - credentials are expired, False - credentials have NOT expired.
        """
        if "expiration" in self._auth_credentials and (
            datetime.datetime.now(datetime.timezone.utc)
            < self._auth_credentials["expiration"]
        ):
            return False
        else:
            return True
    
    def refresh_credentials(self, force=False):
        """
        Will refresh all the client credentials.

        param force: If True will force the creds to be refreshed.

        Returns:
            None
        """
        if force:
            self._auth_credentials.pop("expiration")
        
        _ = self.bucket_credentials # Will call self.auth_credentials
