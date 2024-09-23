import logging
import datetime
import urllib.parse

import msal
import boto3
from rasterio.session import AWSSession

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

    Default configuration is set using the default values from prescient_sdk.config.
    These can be overridden by setting values explicitly when initializing the client.

    Args:
        settings (Settings, optional): Configuration settings for the client. Defaults to None.

    """

    def __init__(
        self,
        settings: Settings | None = None,
    ):
        # default configuration values are set in the Settings class (prescient_sdk.config)
        if settings is None:
            settings = Settings()  # type: ignore
        self.settings: Settings = settings

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
        return urllib.parse.urljoin(self.settings.endpoint_url, "stac")

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
        if "expiration" in self._auth_credentials and (
            datetime.datetime.now(datetime.timezone.utc)
            < self._auth_credentials["expiration"]
        ):
            return self._auth_credentials

        authority_url = urllib.parse.urljoin(
            self.settings.auth_url, self.settings.tenant_id
        )
        app = msal.PublicClientApplication(
            client_id=self.settings.client_id, authority=authority_url
        )

        # trigger auth or auth refresh flow
        time_zero = datetime.datetime.now(datetime.timezone.utc)
        if not self._auth_credentials:
            # aquire creds interactively if none have been fetched yet
            self._auth_credentials = app.acquire_token_interactive(scopes=[])
        else:
            # refresh creds if they have been fetched before and are expired
            self._auth_credentials = app.acquire_token_by_refresh_token(
                refresh_token=self._auth_credentials["refresh_token"], scopes=[]
            )

        # check that a nonzero length token has been obtained
        token: str = self._auth_credentials.get("id_token", "")
        if token == "":
            raise ValueError(f"Failed to obtain Auth token: {self._auth_credentials}")

        # set expiration time of the token
        self._auth_credentials["expiration"] = time_zero + datetime.timedelta(
            seconds=self._auth_credentials["expires_in"]
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
        if (
            "Expiration" in self._bucket_credentials
            and datetime.datetime.now(datetime.timezone.utc)
            < self._bucket_credentials["Expiration"]
        ):
            return self._bucket_credentials

        access_token = self.auth_credentials.get("id_token")
        sts_client = boto3.client("sts", region_name=self.settings.aws_region)

        # exchange token with aws temp creds
        response: dict = sts_client.assume_role_with_web_identity(
            DurationSeconds=3600,  # 1 hour
            RoleArn=self.settings.aws_role,
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
    def session(self) -> AWSSession:
        """
        Get an AWS session to be used when authenticating rasterio

        Returns:
            AWSSession: Rasterio AWS session
        """
        return AWSSession(
            aws_access_key_id=self.bucket_credentials["AccessKeyId"],
            aws_secret_access_key=self.bucket_credentials["SecretAccessKey"],
            aws_session_token=self.bucket_credentials["SessionToken"],
        )
