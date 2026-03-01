"""
SmartThings setup flow with OAuth2 authentication using ucapi-framework.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import logging
from typing import Any

from ucapi import RequestUserInput, SetupAction
from ucapi_framework import BaseSetupFlow

from uc_intg_smartthings.client import SmartThingsClient, SmartThingsAPIError, REDIRECT_URI
from uc_intg_smartthings.config import SmartThingsConfig

_LOG = logging.getLogger(__name__)


class SmartThingsSetupFlow(BaseSetupFlow[SmartThingsConfig]):
    """SmartThings OAuth2 setup flow handler using framework."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._temp_client: SmartThingsClient | None = None
        self._locations: list[dict] = []

    async def get_pre_discovery_screen(self) -> RequestUserInput | None:
        """Show OAuth2 credentials form as pre-discovery screen."""
        return RequestUserInput(
            {"en": "SmartThings OAuth2 Setup"},
            [
                {
                    "id": "info",
                    "label": {"en": "Instructions"},
                    "field": {
                        "label": {
                            "value": {
                                "en": "Enter your SmartThings OAuth2 application credentials.\n\n"
                                "Create these in the SmartThings Developer Workspace:\n"
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

    async def handle_pre_discovery_response(
        self, msg: Any
    ) -> SetupAction | None:
        """Handle multi-step OAuth2 flow."""
        input_values = msg.input_values

        if "client_id" in input_values and "auth_code" not in self._pre_discovery_data:
            return await self._handle_credentials_step(input_values)

        if "auth_code" in input_values and "location_id" not in self._pre_discovery_data:
            return await self._handle_auth_code_step(input_values)

        if "location_id" in input_values:
            return None

        return None

    async def _handle_credentials_step(self, input_values: dict) -> RequestUserInput:
        """Handle credentials step - generate auth URL."""
        client_id = input_values.get("client_id", "").strip()
        client_secret = input_values.get("client_secret", "").strip()

        if not client_id or not client_secret:
            raise ValueError("Client ID and Client Secret are required")

        self._temp_client = SmartThingsClient(client_id, client_secret)
        auth_url = self._temp_client.generate_auth_url()
        _LOG.info("Generated OAuth2 authorization URL")

        return RequestUserInput(
            {"en": "Authorize SmartThings"},
            [
                {
                    "id": "info",
                    "label": {"en": "Step 1"},
                    "field": {
                        "label": {
                            "value": {
                                "en": "Copy the URL below and open it in a browser:"
                            }
                        }
                    },
                },
                {
                    "id": "auth_url",
                    "label": {"en": "Authorization URL"},
                    "field": {"text": {"value": auth_url}},
                },
                {
                    "id": "info2",
                    "label": {"en": "Step 2"},
                    "field": {
                        "label": {
                            "value": {
                                "en": "Log in and authorize. After redirect, copy the 'code' "
                                "parameter from the URL and paste it below:"
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

    async def _handle_discovery(self) -> SetupAction:
        """Handle device discovery - use collected OAuth data to finalize setup."""
        if self._pre_discovery_data and self._pre_discovery_data.get("location_id"):
            _LOG.info("Finalizing setup with collected OAuth data")
            try:
                result = await self.query_device(self._pre_discovery_data)
                if hasattr(result, "identifier"):
                    return await self._finalize_device_setup(result, self._pre_discovery_data)
                return result
            except Exception as err:
                _LOG.error("Discovery failed: %s", err)
                return self.get_manual_entry_form()

        return await self._handle_manual_entry()

    async def _handle_auth_code_step(self, input_values: dict) -> RequestUserInput:
        """Handle authorization code step - exchange for tokens."""
        auth_code = input_values.get("auth_code", "").strip()

        if not auth_code:
            raise ValueError("Authorization code is required")

        if not self._temp_client:
            raise ValueError("Setup flow error: client not initialized")

        try:
            await self._temp_client.exchange_code_for_tokens(auth_code)
            _LOG.info("Successfully exchanged authorization code for tokens")
        except SmartThingsAPIError as e:
            _LOG.error("Token exchange failed: %s", e)
            raise ValueError(f"Token exchange failed: {e}") from e

        try:
            self._locations = await self._temp_client.get_locations()
            _LOG.info("Found %d locations", len(self._locations))
        except SmartThingsAPIError as e:
            _LOG.error("Failed to get locations: %s", e)
            raise ValueError(f"Failed to get locations: {e}") from e

        if not self._locations:
            raise ValueError("No SmartThings locations found")

        location_items = [
            {"id": loc["locationId"], "label": {"en": loc.get("name", "Unknown")}}
            for loc in self._locations
        ]

        return RequestUserInput(
            {"en": "Select Location"},
            [
                {
                    "id": "location_id",
                    "label": {"en": "SmartThings Location"},
                    "field": {
                        "dropdown": {
                            "value": self._locations[0]["locationId"],
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

    def get_manual_entry_form(self) -> RequestUserInput:
        """Return manual entry form (redirects to pre-discovery)."""
        return RequestUserInput(
            {"en": "SmartThings OAuth2 Setup"},
            [
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

    async def query_device(
        self, input_values: dict[str, Any]
    ) -> SmartThingsConfig | RequestUserInput:
        """Create config from collected OAuth data and fetch all devices."""
        location_id = self._pre_discovery_data.get("location_id", "")

        if not location_id or not self._temp_client:
            raise ValueError("Setup flow error: missing required data")

        location = next(
            (loc for loc in self._locations if loc["locationId"] == location_id),
            None,
        )
        location_name = location.get("name", "SmartThings") if location else "SmartThings"

        identifier = f"st-{location_id[:8]}"

        _LOG.info("Fetching devices for location: %s", location_name)
        devices = await self._temp_client.get_devices(location_id)
        _LOG.info("Found %d devices", len(devices))

        rooms = await self._temp_client.get_rooms(location_id)
        room_map = {r.get("roomId"): r.get("name", "Unknown") for r in rooms}

        scenes = []
        modes = []
        try:
            scenes = await self._temp_client.get_scenes(location_id)
            _LOG.info("Found %d scenes", len(scenes))
        except SmartThingsAPIError as e:
            _LOG.warning("Could not fetch scenes: %s", e)

        try:
            modes = await self._temp_client.get_location_modes(location_id)
            _LOG.info("Found %d modes", len(modes))
        except SmartThingsAPIError as e:
            _LOG.warning("Could not fetch modes: %s", e)

        config = SmartThingsConfig(
            identifier=identifier,
            name=location_name,
            client_id=self._pre_discovery_data.get("client_id", ""),
            client_secret=self._pre_discovery_data.get("client_secret", ""),
            location_id=location_id,
            access_token=self._temp_client.access_token or "",
            refresh_token=self._temp_client.refresh_token or "",
            expires_at=self._temp_client.expires_at,
            include_lights=self._pre_discovery_data.get("include_lights", True),
            include_switches=self._pre_discovery_data.get("include_switches", True),
            include_sensors=self._pre_discovery_data.get("include_sensors", True),
            include_climate=self._pre_discovery_data.get("include_climate", True),
            include_covers=self._pre_discovery_data.get("include_covers", True),
            include_media_players=self._pre_discovery_data.get("include_media_players", True),
            include_buttons=True,
            scenes=scenes,
            modes=modes,
        )

        for device in devices:
            device_id = device.get("deviceId", "")
            device_name = device.get("label") or device.get("name", "Unknown")
            room_id = device.get("roomId")
            room_name = room_map.get(room_id, "") if room_id else ""

            caps = []
            for component in device.get("components", []):
                for cap in component.get("capabilities", []):
                    cap_id = cap.get("id", "") if isinstance(cap, dict) else cap
                    if cap_id:
                        caps.append(cap_id)

            config.add_device(device_id, device_name, room_name, caps)

        _LOG.info("Added %d devices to config", len(config.devices))

        await self._temp_client.close()
        self._temp_client = None
        self._locations = []

        _LOG.info("Setup complete for location: %s", location_name)
        return config
