import logging
import datetime
import urllib.parse

import msal
import boto3

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

    Default configuration is set using the default values from prescient_sdk.config.
    These can be overridden by setting values explicitly when initializing the client.

    Args:
        settings (Settings, optional): Configuration settings for the client. Defaults to None.

    Attributes:
        catalog_url (str): The STAC URL used for searching available data in the bucket.
        azure_credentials (dict): Azure credentials used for all authentication.
        headers (dict): Headers for making and authorizing a request to the stac API.
        aws_credentials (dict): AWS credentials for connecting to the S3 bucket containing the data.

    """

    def __init__(
        self,
        settings: Settings | None = None,
    ):
        # default configuration values are set in the Settings class (prescient_sdk.config)
        if settings is None:
            settings = Settings()
        self.settings: Settings = settings

        # initialize empty credentials
        self._azure_credentials: dict = {}
        self._aws_credentials: dict = {}

    @property
    def catalog_url(self) -> str:
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

        authority_url = (
            f"https://login.microsoftonline.com/{self.settings.azure_tenant_id}"
        )
        scopes = [
            f"api://{self.settings.azure_client_id}/{self.settings.azure_client_scope}"
        ]
        app = msal.PublicClientApplication(
            client_id=self.settings.azure_client_id, authority=authority_url
        )

        # trigger auth or auth refresh flow
        time_zero = datetime.datetime.now(datetime.timezone.utc)
        if not self._azure_credentials:
            # aquire creds interactively if none have been fetched yet
            self._azure_credentials = app.acquire_token_interactive(scopes=scopes)
        else:
            # refresh creds if they have been fetched before and are expired
            self._azure_credentials = app.acquire_token_by_refresh_token(
                refresh_token=self._azure_credentials["refresh_token"], scopes=scopes
            )

        # check that a nonzero length token has been obtained
        token: str = self._azure_credentials.get("access_token", "")
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
            "Authorization": f"Bearer {self.azure_credentials['access_token']}",
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

        access_token = self.azure_credentials.get("access_token")
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


if __name__ == "__main__":
    # TODO: remove this test code
    logging.basicConfig(level=logging.DEBUG)
    client = PrescientClient()
    print(client.aws_credentials)
