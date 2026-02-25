"""
SmartThings setup flow with OAuth2 authentication.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import logging
from typing import Any

import ucapi

from uc_intg_smartthings.client import SmartThingsClient, SmartThingsAPIError, REDIRECT_URI
from uc_intg_smartthings.config import SmartThingsConfig, OAuth2Tokens

_LOG = logging.getLogger(__name__)


class SmartThingsSetupFlow:
    """SmartThings OAuth2 setup flow handler."""

    def __init__(self, on_setup_complete: Any = None):
        """Initialize the setup flow."""
        self._on_setup_complete = on_setup_complete
        self._temp_client_id: str | None = None
        self._temp_client_secret: str | None = None
        self._temp_client: SmartThingsClient | None = None

    async def handle_setup_request(
        self, request: ucapi.SetupDriver
    ) -> ucapi.SetupAction:
        """Handle setup requests from the Remote."""
        if isinstance(request, ucapi.DriverSetupRequest):
            return self._get_credentials_form()

        if isinstance(request, ucapi.UserDataResponse):
            return await self._handle_user_data(request.input_values)

        return ucapi.SetupError("Invalid setup request")

    def _get_credentials_form(self) -> ucapi.RequestUserInput:
        """Get the initial credentials form."""
        return ucapi.RequestUserInput(
            title={"en": "SmartThings OAuth2 Credentials"},
            settings=[
                {
                    "id": "info",
                    "label": {"en": "Instructions"},
                    "field": {
                        "label": {
                            "value": {
                                "en": "Enter your SmartThings OAuth2 application credentials.\n\n"
                                "You can create these in the SmartThings Developer Workspace:\n"
                                "https://smartthings.developer.samsung.com/workspace/projects"
                            }
                        }
                    },
                },
                {
                    "id": "client_id",
                    "label": {"en": "OAuth Client ID"},
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "client_secret",
                    "label": {"en": "OAuth Client Secret"},
                    "field": {"password": {"value": ""}},
                },
            ],
        )

    async def _handle_user_data(self, input_values: dict) -> ucapi.SetupAction:
        """Handle user input data."""
        if "client_id" in input_values and "auth_code" not in input_values:
            return await self._handle_credentials_step(input_values)

        if "auth_code" in input_values and "location_id" not in input_values:
            return await self._handle_auth_code_step(input_values)

        if "location_id" in input_values:
            return await self._handle_location_step(input_values)

        return ucapi.SetupError("Invalid setup step")

    async def _handle_credentials_step(self, input_values: dict) -> ucapi.SetupAction:
        """Handle credentials step - generate auth URL."""
        client_id = input_values.get("client_id", "").strip()
        client_secret = input_values.get("client_secret", "").strip()

        if not client_id or not client_secret:
            return ucapi.SetupError("Client ID and Client Secret are required")

        self._temp_client_id = client_id
        self._temp_client_secret = client_secret
        self._temp_client = SmartThingsClient(client_id, client_secret)

        auth_url = self._temp_client.generate_auth_url()
        _LOG.info("Generated OAuth2 authorization URL")

        return ucapi.RequestUserInput(
            title={"en": "Authorize SmartThings"},
            settings=[
                {
                    "id": "info",
                    "label": {"en": "Authorization Required"},
                    "field": {
                        "label": {
                            "value": {
                                "en": f"1. Open this URL in a browser:\n{auth_url}\n\n"
                                f"2. Log in and authorize the application\n\n"
                                f"3. After authorization, you will be redirected to:\n{REDIRECT_URI}\n\n"
                                f"4. Copy the 'code' parameter from the URL and paste it below"
                            }
                        }
                    },
                },
                {
                    "id": "auth_code",
                    "label": {"en": "Authorization Code"},
                    "field": {"text": {"value": ""}},
                },
            ],
        )

    async def _handle_auth_code_step(self, input_values: dict) -> ucapi.SetupAction:
        """Handle authorization code step - exchange for tokens."""
        auth_code = input_values.get("auth_code", "").strip()

        if not auth_code:
            return ucapi.SetupError("Authorization code is required")

        if not self._temp_client:
            return ucapi.SetupError("Setup flow error: client not initialized")

        try:
            await self._temp_client.exchange_code_for_tokens(auth_code)
            _LOG.info("Successfully exchanged authorization code for tokens")
        except SmartThingsAPIError as e:
            _LOG.error("Token exchange failed: %s", e)
            return ucapi.SetupError(f"Token exchange failed: {e}")

        try:
            locations = await self._temp_client.get_locations()
            _LOG.info("Found %d locations", len(locations))
        except SmartThingsAPIError as e:
            _LOG.error("Failed to get locations: %s", e)
            return ucapi.SetupError(f"Failed to get locations: {e}")

        if not locations:
            return ucapi.SetupError("No SmartThings locations found")

        location_items = [
            {"id": loc["locationId"], "label": {"en": loc.get("name", "Unknown")}}
            for loc in locations
        ]

        return ucapi.RequestUserInput(
            title={"en": "Select Location"},
            settings=[
                {
                    "id": "location_id",
                    "label": {"en": "SmartThings Location"},
                    "field": {
                        "dropdown": {
                            "value": locations[0]["locationId"],
                            "items": location_items,
                        }
                    },
                },
                {
                    "id": "include_lights",
                    "label": {"en": "Include Lights"},
                    "field": {"checkbox": {"value": True}},
                },
                {
                    "id": "include_switches",
                    "label": {"en": "Include Switches"},
                    "field": {"checkbox": {"value": True}},
                },
                {
                    "id": "include_sensors",
                    "label": {"en": "Include Sensors"},
                    "field": {"checkbox": {"value": True}},
                },
                {
                    "id": "include_climate",
                    "label": {"en": "Include Climate"},
                    "field": {"checkbox": {"value": True}},
                },
                {
                    "id": "include_covers",
                    "label": {"en": "Include Covers"},
                    "field": {"checkbox": {"value": True}},
                },
                {
                    "id": "include_media_players",
                    "label": {"en": "Include Media Players"},
                    "field": {"checkbox": {"value": True}},
                },
            ],
        )

    async def _handle_location_step(self, input_values: dict) -> ucapi.SetupAction:
        """Handle location selection step - complete setup."""
        location_id = input_values.get("location_id", "")

        if not location_id or not self._temp_client:
            return ucapi.SetupError("Setup flow error")

        try:
            locations = await self._temp_client.get_locations()
            location = next(
                (loc for loc in locations if loc["locationId"] == location_id),
                None,
            )
            location_name = location.get("name", "SmartThings") if location else "SmartThings"
        except SmartThingsAPIError:
            location_name = "SmartThings"

        identifier = f"st-{location_id[:8]}"

        config = SmartThingsConfig(
            identifier=identifier,
            name=location_name,
            client_id=self._temp_client_id or "",
            client_secret=self._temp_client_secret or "",
            location_id=location_id,
            location_name=location_name,
            oauth2_tokens=OAuth2Tokens(
                access_token=self._temp_client.access_token or "",
                refresh_token=self._temp_client.refresh_token or "",
                expires_at=self._temp_client.expires_at,
            ),
            include_lights=input_values.get("include_lights", True),
            include_switches=input_values.get("include_switches", True),
            include_sensors=input_values.get("include_sensors", True),
            include_climate=input_values.get("include_climate", True),
            include_covers=input_values.get("include_covers", True),
            include_media_players=input_values.get("include_media_players", True),
            include_buttons=True,
            polling_interval=10,
        )

        await self._temp_client.close()
        self._temp_client = None
        self._temp_client_id = None
        self._temp_client_secret = None

        _LOG.info("Setup complete for location: %s", location_name)

        if self._on_setup_complete:
            await self._on_setup_complete(config)

        return ucapi.SetupComplete()
