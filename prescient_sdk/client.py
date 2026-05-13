import datetime
import logging
import urllib.parse
from pathlib import Path

import boto3
import google.auth.transport.requests
import google.oauth2.credentials
import msal
import requests
from google_auth_oauthlib.flow import InstalledAppFlow

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
        self._upload_bucket_credentials: dict = {}

    @property
    def stac_catalog_url(self) -> str:
        """
        Get the STAC URL.

        Returns:
            str: The STAC URL.
        """
        return urllib.parse.urljoin(self.settings.prescient_endpoint_url, "stac")

    def _fetch_microsoft_credentials(self) -> dict:
        """Acquire or refresh credentials using Microsoft MSAL.

        Returns:
            dict: Raw MSAL token response containing ``id_token`` and ``refresh_token``.
        """
        authority_url = urllib.parse.urljoin(
            self.settings.prescient_auth_url, self.settings.prescient_tenant_id
        )
        app = msal.PublicClientApplication(
            client_id=self.settings.prescient_client_id, authority=authority_url
        )

        if (
            not self._auth_credentials
            or "refresh_token" not in self._auth_credentials.keys()
        ):
            return app.acquire_token_interactive(
                scopes=["https://graph.microsoft.com/.default"]
            )
        else:
            return app.acquire_token_by_refresh_token(
                refresh_token=self._auth_credentials["refresh_token"],
                scopes=["https://graph.microsoft.com/.default"],
            )

    def _fetch_google_credentials(self) -> dict:
        """Acquire or refresh credentials using Google OAuth2.

        Uses ``google-auth-oauthlib`` for the interactive browser flow and
        ``google-auth`` for silent token refresh. The returned dict is
        normalized to include the same ``id_token`` and ``refresh_token`` keys
        used by the Microsoft flow so that all downstream code is unaffected.

        Returns:
            dict: Normalized credential dict containing ``id_token``, ``refresh_token``,
                and ``access_token``.

        """
        token_uri = urllib.parse.urljoin(
            self.settings.prescient_auth_url, "/o/oauth2/token"
        )
        scopes = ["openid", "https://www.googleapis.com/auth/userinfo.email"]

        if not self._auth_credentials or "refresh_token" not in self._auth_credentials:
            flow = InstalledAppFlow.from_client_config(
                client_config={
                    "installed": {
                        "client_id": self.settings.prescient_client_id,
                        "client_secret": self.settings.prescient_google_client_secret,
                        "auth_uri": urllib.parse.urljoin(
                            self.settings.prescient_auth_url, "/o/oauth2/auth"
                        ),
                        "token_uri": token_uri,
                    }
                },
                scopes=scopes,
            )
            credentials = flow.run_local_server(
                port=self.settings.prescient_google_redirect_port
            )
        else:
            credentials = google.oauth2.credentials.Credentials(
                token=None,
                refresh_token=self._auth_credentials["refresh_token"],
                token_uri=token_uri,
                client_id=self.settings.prescient_client_id,
                client_secret=self.settings.prescient_google_client_secret,
            )
            credentials.refresh(google.auth.transport.requests.Request())

        return {
            "id_token": credentials.id_token,
            "refresh_token": credentials.refresh_token,
            "access_token": credentials.token,
        }

    @property
    def auth_credentials(self) -> dict:
        """
        Get the authorization credentials for the client.

        Returns:
            dict: Token response containing at minimum::

                {
                    "id_token": "string",
                    "refresh_token": "string",
                    "access_token": "string",
                }

        Raises:
            ValueError: If a valid id_token cannot be obtained.
        """
        if not self.credentials_expired:
            return self._auth_credentials

        time_zero = datetime.datetime.now(datetime.timezone.utc)

        if self.settings.prescient_auth_provider == "google":
            self._auth_credentials = self._fetch_google_credentials()
        else:
            self._auth_credentials = self._fetch_microsoft_credentials()

        token: str = self._auth_credentials.get("id_token", "")
        if token == "":
            raise ValueError(f"Failed to obtain Auth token: {self._auth_credentials}")

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

    def _get_bucket_credentials(self, role: str):
        access_token = self.auth_credentials.get("id_token")
        sts_client = boto3.client("sts", region_name=self.settings.prescient_aws_region)

        # assume arn string, otherwise last 10 characters of role string
        try:
            role_name_stub = role.split("/")[1]
        except IndexError:
            role_name_stub = role[-10:]
        role_session_name = f"prescient-s3-access-{role_name_stub}"

        # exchange token with aws temp creds
        response: dict = sts_client.assume_role_with_web_identity(
            DurationSeconds=self._expiration_duration,
            RoleArn=role,
            RoleSessionName=role_session_name,
            WebIdentityToken=access_token,
        )
        credentials = response.get("Credentials", {})

        if not credentials:
            raise ValueError(f"Failed to obtain creds: {response}")

        # convert datetime to UTC for later comparison
        credentials["Expiration"] = credentials["Expiration"].astimezone(
            datetime.timezone.utc
        )

        return credentials

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

        if self.settings.prescient_aws_role:
            self._bucket_credentials = self._fetch_sts_credentials()
        else:
            self._bucket_credentials = self._fetch_fileproxy_credentials()

        expiration = self._bucket_credentials["Expiration"]
        if isinstance(expiration, str):
            expiration = datetime.datetime.fromisoformat(
                expiration.replace("Z", "+00:00")
            )
        self._bucket_credentials["Expiration"] = expiration.astimezone(
            datetime.timezone.utc
        )

        return self._bucket_credentials

    def _fetch_sts_credentials(self) -> dict:
        """Exchange the auth id_token for AWS credentials via STS."""
        access_token = self.auth_credentials.get("id_token")
        sts_client = boto3.client("sts", region_name=self.settings.prescient_aws_region)
        response: dict = sts_client.assume_role_with_web_identity(
            DurationSeconds=self._expiration_duration,
            RoleArn=self.settings.prescient_aws_role,
            RoleSessionName="prescient-s3-access",
            WebIdentityToken=access_token,
        )
        creds = response.get("Credentials")
        if not creds:
            raise ValueError(f"Failed to obtain creds: {response}")
        return creds

    def _fetch_fileproxy_credentials(self) -> dict:
        """Fetch temporary bucket credentials from the Prescient fileproxy endpoint.

        The endpoint returns snake_case keys; map them to the PascalCase shape
        used by the rest of the client (matching the boto3 STS response).
        """
        url = urllib.parse.urljoin(
            self.settings.prescient_endpoint_url, "fileproxy/credentials"
        )
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        payload = response.json()
        return {
            "AccessKeyId": payload["access_key_id"],
            "SecretAccessKey": payload["secret_access_key"],
            "SessionToken": payload["session_token"],
            "Expiration": payload["expiration"],
        }

    @property
    def upload_bucket_credentials(self):
        """Get upload bucket credentials using an auth access token

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
        if self._upload_bucket_credentials and not self.credentials_expired:
            return self._upload_bucket_credentials

        if not self.settings.prescient_upload_role:
            raise ValueError(
                "prescient_upload_role is not configured; set PRESCIENT_UPLOAD_ROLE "
                "to use the upload bucket."
            )

        self._upload_bucket_credentials = self._get_bucket_credentials(
            role=self.settings.prescient_upload_role
        )

        return self._upload_bucket_credentials

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
    def upload_session(self) -> boto3.Session:
        """
        Get an AWS session for authenticating to the upload bucket

        Returns:
            Session: boto3 Session object
        """
        return boto3.Session(
            aws_access_key_id=self.upload_bucket_credentials["AccessKeyId"],
            aws_secret_access_key=self.upload_bucket_credentials["SecretAccessKey"],
            aws_session_token=self.upload_bucket_credentials["SessionToken"],
            region_name=self.settings.prescient_aws_region,
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

        _ = self.bucket_credentials  # Will call self.auth_credentials
        if self.settings.prescient_upload_role:
            _ = self.upload_bucket_credentials
