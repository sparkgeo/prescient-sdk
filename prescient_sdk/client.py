import logging
import datetime
import os

import msal
import boto3

from prescient_sdk.config import config as default_config

logger = logging.getLogger("prescient_sdk")


class PrescientClient:
    """
    Client for interacting with the Prescient API.

    Default configuration is set using the default values from prescient_sdk.config.
    These can be overridden by setting values explicitly when initializing the client.

    Args:
        endpoint_url (str, optional): URL for the Prescient API.
        aws_region (str, optional): AWS region.
        aws_profile (str, optional): AWS profile.
        stac_api_url (str, optional): URL for the STAC API.
        azure_tenant_id (str, optional): Azure tenant ID.
        azure_client_id (str, optional): Azure client ID.
        azure_client_secret (str, optional): Azure client secret.
        azure_auth_url (str, optional): Azure auth URL
        azure_auth_token_path (str, optional): Azure auth token path.
        azure_client_scope (str, optional): Azure client scope.
        destination_bucket_name (str, optional): Destination bucket name for uploading files.

    Attributes:
        catalog_url (str): The STAC URL used for searching available data in the bucket.
        azure_credentials (dict): Azure credentials used for all authentication.
        headers (dict): Headers for a request to the stac API.
        aws_credentials (dict): AWS credentials for connecting to the S3 bucket containing the data.

    """

    def __init__(
        self,
        endpoint_url: str | None = None,
        aws_region: str | None = None,
        aws_profile: str | None = None,
        aws_role: str | None = None,
        azure_tenant_id: str | None = None,
        azure_client_id: str | None = None,
        azure_client_secret: str | None = None,
        azure_auth_url: str | None = None,
        azure_auth_token_path: str | None = None,
        azure_client_scope: str | None = None,
        destination_bucket_name: str | None = None,
    ):
        # default configuration is from prescient_sdk.config, which uses Dynaconf to set the configuration
        # if a custom configuration values are passed to this init, they will override the default configuration

        self._endpoint_url = endpoint_url or default_config.endpoint_url
        self._aws_region = aws_region or default_config.aws_region
        self._aws_profile = aws_profile or default_config.aws_profile
        self._aws_role = aws_role or default_config.aws_role
        self._azure_tenant_id = azure_tenant_id or default_config.azure_tenant_id
        self._azure_client_id = azure_client_id or default_config.azure_client_id
        self._azure_client_secret = (
            azure_client_secret or default_config.azure_client_secret
        )
        self._azure_auth_url = azure_auth_url or default_config.azure_auth_url
        self._azure_auth_token_path = (
            azure_auth_token_path or default_config.azure_auth_token_path
        )
        self._azure_client_scope = (
            azure_client_scope or default_config.azure_client_scope
        )
        self._destination_bucket_name = (
            destination_bucket_name or default_config.destination_bucket_name
        )

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
        return os.path.join(self._endpoint_url, "stac")

    @property
    def azure_credentials(self) -> dict:
        """
        Get the Azure credentials for the client.

        Returns:
            dict: Azure access token

            {
                "token_type": "Bearer",
                "scope": "",
                "expires_in": 5021,
                "ext_expires_in": 5021,
                "access_token": "",
                "refresh_token": "",
                "id_token": "",
                "client_info": "",
                "id_token_claims": {
                    "aud": "",
                    "iss": "",
                    "iat": 1726515801,
                    "nbf": 1726515801,
                    "exp": 1726519701,
                    "aio": "",
                    "name": "",
                    "nonce": "",
                    "oid": "",
                    "preferred_username": "",
                    "rh": "",
                    "roles": [""],
                    "sub": "",
                    "tid": "",
                    "uti": "",
                    "ver": "",
                },
                "token_source": "",
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

        authority_url = f"https://login.microsoftonline.com/{self._azure_tenant_id}"
        scopes = [f"api://{self._azure_client_id}/{self._azure_client_scope}"]
        app = msal.PublicClientApplication(
            client_id=self._azure_client_id, authority=authority_url
        )

        # trigger auth or auth refresh flow
        time_zero = datetime.datetime.now(datetime.timezone.utc)
        if not self._azure_credentials:
            # aquire creds interactively if none have been fetched yet
            self._azure_credentials = app.acquire_token_interactive(scopes=scopes)
        else:
            # refresh creds if they have been fetched before
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
            dict: AWS temporary credentials
                {
                    'AccessKeyId': 'string',
                    'SecretAccessKey': 'string',
                    'SessionToken': 'string',
                    'Expiration': datetime(2015, 1, 1)
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
        sts_client = boto3.client("sts", region_name=self._aws_region)

        # exchange token with aws temp creds
        response: dict = sts_client.assume_role_with_web_identity(
            DurationSeconds=3600,  # 1 hour
            RoleArn=self._aws_role,
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
    logging.basicConfig(level=logging.DEBUG)
    client = PrescientClient()
    print(client.aws_credentials)
