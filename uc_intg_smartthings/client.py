"""
SmartThings API client with OAuth2 authentication.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import base64
import logging
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp
import certifi
import ssl

_LOG = logging.getLogger(__name__)

SMARTTHINGS_API_BASE = "https://api.smartthings.com/v1"
SMARTTHINGS_AUTH_URL = "https://api.smartthings.com/oauth/authorize"
SMARTTHINGS_TOKEN_URL = "https://api.smartthings.com/oauth/token"
REDIRECT_URI = "https://httpbin.org/get"
OAUTH_SCOPES = [
    "r:devices:*",
    "w:devices:*",
    "r:locations:*",
    "r:scenes:*",
    "x:scenes:*",
]


class SmartThingsAPIError(Exception):
    """SmartThings API error."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SmartThingsClient:
    """SmartThings API client with OAuth2 support."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: float | None = None,
    ):
        """Initialize the SmartThings client."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at or 0
        self._session: aiohttp.ClientSession | None = None
        self._rate_limit_window: list[float] = []
        self._rate_limit_max = 8
        self._rate_limit_period = 10.0
        self._on_token_refresh: Any = None

    @property
    def is_authenticated(self) -> bool:
        """Check if the client has valid tokens."""
        return bool(self.access_token and self.refresh_token)

    @property
    def token_expired(self) -> bool:
        """Check if the access token is expired or will expire soon."""
        return time.time() >= (self.expires_at - 300)

    def set_token_refresh_callback(self, callback: Any) -> None:
        """Set callback for token refresh events."""
        self._on_token_refresh = callback

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def generate_auth_url(self) -> str:
        """Generate the OAuth2 authorization URL."""
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(OAUTH_SCOPES),
        }
        return f"{SMARTTHINGS_AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, auth_code: str) -> dict:
        """Exchange authorization code for access and refresh tokens."""
        session = await self._get_session()

        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        }

        async with session.post(
            SMARTTHINGS_TOKEN_URL, headers=headers, data=data
        ) as response:
            if response.status != 200:
                text = await response.text()
                _LOG.error("Token exchange failed: %s - %s", response.status, text)
                raise SmartThingsAPIError(
                    f"Token exchange failed: {text}", response.status
                )

            token_data = await response.json()
            self.access_token = token_data["access_token"]
            self.refresh_token = token_data["refresh_token"]
            self.expires_at = time.time() + token_data.get("expires_in", 3600)

            _LOG.info("Successfully obtained OAuth2 tokens")
            return token_data

    async def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            _LOG.error("No refresh token available")
            return False

        session = await self._get_session()

        credentials = f"{self.client_id}:{self.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }

        try:
            async with session.post(
                SMARTTHINGS_TOKEN_URL, headers=headers, data=data
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    _LOG.error("Token refresh failed: %s - %s", response.status, text)
                    return False

                token_data = await response.json()
                self.access_token = token_data["access_token"]
                self.refresh_token = token_data.get(
                    "refresh_token", self.refresh_token
                )
                self.expires_at = time.time() + token_data.get("expires_in", 3600)

                _LOG.info("Successfully refreshed OAuth2 tokens")

                if self._on_token_refresh:
                    await self._on_token_refresh(
                        self.access_token, self.refresh_token, self.expires_at
                    )

                return True
        except Exception as e:
            _LOG.error("Token refresh error: %s", e)
            return False

    async def _check_rate_limit(self) -> None:
        """Check and enforce rate limiting."""
        now = time.time()
        self._rate_limit_window = [
            t for t in self._rate_limit_window if now - t < self._rate_limit_period
        ]

        if len(self._rate_limit_window) >= self._rate_limit_max:
            sleep_time = self._rate_limit_period - (now - self._rate_limit_window[0])
            if sleep_time > 0:
                _LOG.debug("Rate limit reached, sleeping for %.2f seconds", sleep_time)
                await asyncio.sleep(sleep_time)

        self._rate_limit_window.append(time.time())

    async def _ensure_valid_token(self) -> None:
        """Ensure we have a valid access token."""
        if self.token_expired and self.refresh_token:
            _LOG.debug("Access token expired, refreshing...")
            if not await self.refresh_access_token():
                raise SmartThingsAPIError("Failed to refresh access token")

    async def _api_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        retry_on_401: bool = True,
    ) -> dict | list:
        """Make an authenticated API request."""
        await self._ensure_valid_token()
        await self._check_rate_limit()

        session = await self._get_session()
        url = f"{SMARTTHINGS_API_BASE}{endpoint}"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with session.request(
                method, url, headers=headers, json=data
            ) as response:
                if response.status == 401 and retry_on_401:
                    _LOG.warning("Got 401, attempting token refresh...")
                    if await self.refresh_access_token():
                        return await self._api_request(
                            method, endpoint, data, retry_on_401=False
                        )
                    raise SmartThingsAPIError("Authentication failed", 401)

                if response.status == 429:
                    _LOG.warning("Rate limited by SmartThings API")
                    await asyncio.sleep(10)
                    return await self._api_request(method, endpoint, data)

                if response.status >= 400:
                    text = await response.text()
                    _LOG.error("API error: %s - %s", response.status, text)
                    raise SmartThingsAPIError(text, response.status)

                if response.status == 204:
                    return {}

                return await response.json()

        except aiohttp.ClientError as e:
            _LOG.error("HTTP error: %s", e)
            raise SmartThingsAPIError(str(e))

    async def get_locations(self) -> list[dict]:
        """Get all locations for the user."""
        result = await self._api_request("GET", "/locations")
        return result.get("items", [])

    async def get_devices(self, location_id: str | None = None) -> list[dict]:
        """Get all devices, optionally filtered by location."""
        endpoint = "/devices"
        if location_id:
            endpoint = f"/devices?locationId={location_id}"
        result = await self._api_request("GET", endpoint)
        return result.get("items", [])

    async def get_device(self, device_id: str) -> dict:
        """Get a single device by ID."""
        return await self._api_request("GET", f"/devices/{device_id}")

    async def get_device_status(self, device_id: str) -> dict:
        """Get the current status of a device."""
        return await self._api_request("GET", f"/devices/{device_id}/status")

    async def get_device_component_status(
        self, device_id: str, component_id: str = "main"
    ) -> dict:
        """Get status for a specific device component."""
        return await self._api_request(
            "GET", f"/devices/{device_id}/components/{component_id}/status"
        )

    async def execute_command(
        self,
        device_id: str,
        capability: str,
        command: str,
        args: list | None = None,
        component_id: str = "main",
    ) -> dict:
        """Execute a command on a device."""
        data = {
            "commands": [
                {
                    "component": component_id,
                    "capability": capability,
                    "command": command,
                    "arguments": args or [],
                }
            ]
        }
        return await self._api_request("POST", f"/devices/{device_id}/commands", data)

    async def get_rooms(self, location_id: str) -> list[dict]:
        """Get all rooms for a location."""
        result = await self._api_request("GET", f"/locations/{location_id}/rooms")
        return result.get("items", [])

    async def get_scenes(self, location_id: str) -> list[dict]:
        """Get all scenes for a location."""
        result = await self._api_request("GET", f"/scenes?locationId={location_id}")
        return result.get("items", [])

    async def execute_scene(self, scene_id: str) -> dict:
        """Execute a scene."""
        return await self._api_request("POST", f"/scenes/{scene_id}/execute")

    async def get_location_modes(self, location_id: str) -> list[dict]:
        """Get available modes for a location."""
        result = await self._api_request("GET", f"/locations/{location_id}/modes")
        return result.get("items", [])

    async def get_current_mode(self, location_id: str) -> dict:
        """Get the current mode for a location."""
        return await self._api_request("GET", f"/locations/{location_id}/modes/current")

    async def set_mode(self, location_id: str, mode_id: str) -> dict:
        """Set the mode for a location."""
        return await self._api_request(
            "PUT", f"/locations/{location_id}/modes/current", {"modeId": mode_id}
        )
