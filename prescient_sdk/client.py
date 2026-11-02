import logging
import time
from pathlib import Path
from typing import Callable

import requests
from requests.auth import AuthBase

from prescient_sdk import _logging
from prescient_sdk.config import Settings

logger = logging.getLogger("prescient_sdk")

# Re-exchange the API key when the cached token has less than this many seconds left.
_TOKEN_REFRESH_MARGIN = 60
_EXCHANGE_TIMEOUT = 30


class PrescientAuthError(Exception):
    """Raised when Keycloak refuses to exchange the API key for a token.

    Args:
        message (str): Description of the failure.
        retry_after (int, optional): Seconds to wait before trying again, from
            the `Retry-After` header of a 429 response. Defaults to None.

    Attributes:
        retry_after (int | None): Seconds to wait before trying again, or None.
    """

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class _BearerAuth(AuthBase):
    """Sets `Authorization: Bearer <token>` with a fresh token on each request."""

    def __init__(self, token: Callable[[], str]):
        self._token = token

    def __call__(self, request):
        request.headers["Authorization"] = f"Bearer {self._token()}"
        return request


class _ReauthSession(requests.Session):
    """A `requests.Session` that retries once with a new token after a 401."""

    def __init__(self, auth: AuthBase, reauthenticate: Callable[[], str]):
        super().__init__()
        self.auth = auth
        self._reauthenticate = reauthenticate

    def send(self, request, **kwargs):
        response = super().send(request, **kwargs)
        # Resend the prepared request only when:
        # - its body is in memory (None, str or bytes, which includes `json=` and
        #   `files=`). A file object or generator passed as `data=` has been read.
        # - it carried an Authorization header. requests strips it on a redirect
        #   to another host, and the token must not go to that host.
        # - the 401 is not the end of a redirect chain. The hop that got the 401
        #   has already retried.
        body = request.body
        if (
            response.status_code != 401
            or response.history
            or "Authorization" not in request.headers
            or not (body is None or isinstance(body, (str, bytes)))
        ):
            return response
        logger.info("Got 401 from %s; exchanging the API key again", request.url)
        response.close()
        retry = request.copy()
        retry.headers["Authorization"] = f"Bearer {self._reauthenticate()}"
        return super().send(retry, **kwargs)


class PrescientClient:
    """
    Client for signing in to the Prescient platform with an API key.

    The client exchanges your API key (`prescient_api_key`) with your
    Organization's Keycloak realm for a short-lived access token. It caches the
    token and exchanges the key again shortly before the token expires. Use
    `session`, `auth`, `headers` or `request_modifier` to send the token to the
    platform APIs.

    Configuration Options:
        1. Construct the `prescient_sdk.config.Settings` object directly
        2. Specify the path to an environment file containing configuration values
        3. Do neither, and allow the client to build the `Settings` object using default
           methods (env variables, config.env file location in the working directory)

        Note that you cannot specify the env_file location AND provide a `Settings` object.

    Args:
        env_file (str | Path, optional): Path to a configuration file. Defaults to None.
        settings (Settings, optional): Configuration settings for the client. Defaults to None.
        debug (bool, optional): When True, emit DEBUG/INFO/WARNING/ERROR logs;
            otherwise only WARNING/ERROR. Defaults to False.
        log_file (str | Path, optional): Destination for log output. When None
            (default), logs go to stdout; when set, logs go to this file.

    Raises:
        ValueError: If both an environment file and a settings object are provided.
        ValueError: If the provided configuration file is not found.
        ValueError: If the configuration contains settings removed in 1.0.
    """

    settings: Settings
    """The configuration the client was built with."""

    auth: AuthBase
    """A `requests` auth object that sets `Authorization: Bearer <token>` with
    a fresh token on each request. Use it with other libraries that accept
    `requests` auth. It does not retry after a 401."""

    session: requests.Session
    """A `requests.Session` that sends `Authorization: Bearer <token>` with a
    fresh token. After a 401 response it exchanges the API key again and retries
    the request once. A request whose body is a file object or generator is not
    retried."""

    def __init__(
        self,
        env_file: str | Path | None = None,
        settings: Settings | None = None,
        debug: bool = False,
        log_file: str | Path | None = None,
    ):
        _logging.configure(debug, log_file)
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
        self.settings = settings
        logger.debug(
            "Settings loaded: endpoint=%s realm=%s keycloak=%s",
            settings.prescient_endpoint_url,
            settings.realm,
            settings.keycloak_url,
        )
        # ponytail: single-threaded use assumed; concurrent threads may each
        # exchange the key at expiry. Add a lock if that becomes a problem.
        self._token: str | None = None
        self._token_expiry = 0.0  # time.monotonic() value
        self.auth = _BearerAuth(self._access_token)
        self.session = _ReauthSession(self.auth, self._exchange)

    def _exchange(self) -> str:
        """Exchange the API key for a new access token and cache it.

        Returns:
            str: The new access token.

        Raises:
            PrescientAuthError: If Keycloak rejects the key (401/403) or rate
                limits the exchange (429).
            requests.HTTPError: For any other non-2xx response.
        """
        url = (
            f"{self.settings.keycloak_url}/realms/{self.settings.realm}"
            "/api-keys/exchange"
        )
        logger.debug("POST %s", url)
        response = requests.post(
            url,
            headers={"X-API-Key": self.settings.prescient_api_key.get_secret_value()},
            timeout=_EXCHANGE_TIMEOUT,
        )
        if response.status_code in (401, 403):
            raise PrescientAuthError(
                "API key rejected: it is invalid, expired or revoked. Create a new "
                "one in your Organization's Keycloak Account Console."
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            raise PrescientAuthError(
                "Too many API key exchanges; try again later.",
                retry_after=int(retry_after) if retry_after.isdigit() else None,
            )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expiry = time.monotonic() + payload["expires_in"]
        logger.info("Obtained access token for realm %s", self.settings.realm)
        return payload["access_token"]

    def _access_token(self) -> str:
        """Return the cached access token, exchanging the API key when needed."""
        if (
            self._token is None
            or time.monotonic() >= self._token_expiry - _TOKEN_REFRESH_MARGIN
        ):
            return self._exchange()
        return self._token

    @property
    def headers(self) -> dict:
        """
        Get an `Authorization` header with a fresh access token.

        Use it for one-off requests. The token expires, so get the headers
        again for each request rather than storing them.

        Returns:
            dict: `{"Authorization": "Bearer <access_token>"}`.

        Raises:
            PrescientAuthError: If the API key cannot be exchanged for a token.
        """
        return {"Authorization": f"Bearer {self._access_token()}"}

    def request_modifier(self, request: requests.Request) -> requests.Request:
        """
        Add an `Authorization` header with a fresh access token to a request.

        Pass this method to pystac-client, for example
        `Client.open(client.stac_url, request_modifier=client.request_modifier)`.

        Args:
            request (requests.Request): The request to modify.

        Returns:
            requests.Request: The same request, with the header set.

        Raises:
            PrescientAuthError: If the API key cannot be exchanged for a token.
        """
        request.headers["Authorization"] = f"Bearer {self._access_token()}"
        return request

    @property
    def stac_url(self) -> str:
        """
        Get the STAC API URL of your Organization.

        Returns:
            str: `<prescient_endpoint_url>/stac`.
        """
        return self.settings.prescient_endpoint_url.rstrip("/") + "/stac"
