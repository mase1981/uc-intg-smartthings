"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details.

Corrected version to ensure persistence and fix AttributeError.
"""

import asyncio
import logging
import json
import os
from typing import Any, Dict, Optional, List, Set

from ucapi import IntegrationAPI, api_definitions
# **FIX**: Import the base Entity class from the correct module
from ucapi.entity import Entity
from ucapi.api_definitions import Events, DeviceStates, SetupDriver, WsMsgEvents
import ucapi.api_definitions as uc

# --- Helper Classes (included for a self-contained example) ---

class ConfigManager:
    """Manages loading and saving of configuration files."""
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_path = os.path.join(config_dir, 'config.json')
        self.devices_path = os.path.join(config_dir, 'devices.json')

    def is_configured(self) -> bool:
        return os.path.exists(self.config_path)

    def load_config(self) -> Dict[str, Any]:
        if not self.is_configured():
            return {}
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def save_config(self, config: Dict[str, Any]):
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)

    def load_devices(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.devices_path):
            return []
        try:
            with open(self.devices_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def save_devices(self, devices: List[Dict[str, Any]]):
        with open(self.devices_path, 'w') as f:
            json.dump(devices, f, indent=2)

class SmartThingsClient:
    """A placeholder for the actual SmartThings API client."""
    def __init__(self, token: str):
        self._token = token
        _LOG.info("SmartThingsClient initialized.")

    async def get_devices(self, location_id: str) -> List[Dict]:
        _LOG.info("Fetching devices from SmartThings API...")
        # In a real implementation, this would make an HTTP request.
        return []

    async def get_rooms(self, location_id: str) -> List[Dict]:
        _LOG.info("Fetching rooms from SmartThings API...")
        return []

    async def get_device_status(self, device_id: str) -> Dict:
        return {}

    async def close(self):
        _LOG.info("SmartThingsClient closed.")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class SmartThingsEntityFactory:
    """A placeholder for the entity factory."""
    def __init__(self, client: Optional[SmartThingsClient], api: IntegrationAPI):
        self._client = client
        self._api = api
        self.command_callback = None

    # **FIX**: Corrected the type hint from api_definitions.Entity to Entity
    def create_entity(self, device_data: Dict, config: Dict, room_name: Optional[str]) -> Optional[Entity]:
        # This factory would contain the logic to convert SmartThings device data
        # into Unfolded Circle entity objects (e.g., uc.Light, uc.Switch).
        # Returning None as this is a placeholder.
        return None

    # **FIX**: Corrected the type hint from api_definitions.Entity to Entity
    def update_entity_attributes(self, entity: Entity, status: Dict):
        pass

class SmartThingsSetupFlow:
    """A placeholder for the setup flow handler."""
    def __init__(self, api: IntegrationAPI, config_manager: ConfigManager):
        self._api = api
        self._config_manager = config_manager

    async def handle_setup_request(self, msg: SetupDriver) -> Any:
        # On the final step, it saves the config and returns SetupComplete.
        if msg.step_id == "finalize":
            final_config = msg.user_input
            self._config_manager.save_config(final_config)
            return uc.SetupComplete()
        # Placeholder for other setup steps
        return None


# --- Main Integration Logic ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
_LOG = logging.getLogger(__name__)

class SmartThingsIntegration:
    
    def __init__(self, api: IntegrationAPI, loop: asyncio.AbstractEventLoop):
        self.api = api
        self.loop = loop
        self.client: Optional[SmartThingsClient] = None
        self.factory: Optional[SmartThingsEntityFactory] = None
        self.config_manager = ConfigManager(api.config_dir_path)
        self.config: Dict[str, Any] = {}
        self.setup_flow = SmartThingsSetupFlow(api, self.config_manager)
        self.polling_task: Optional[asyncio.Task] = None
        self.subscribed_entities: Set[str] = set()
        
        self._register_event_handlers()
        
    def _register_event_handlers(self):
        @self.api.listens_to(Events.CONNECT)
        async def on_connect():
            _LOG.info("Connected to UC Remote")
            if self.config_manager.is_configured():
                await self._initialize_integration()
            else:
                await self.api.set_device_state(DeviceStates.AWAITING_SETUP)
                
        @self.api.listens_to(Events.DISCONNECT)
        async def on_disconnect():
            await self._cleanup()

        @self.api.listens_to(WsMsgEvents.SUBSCRIBE_ENTITIES)
        async def on_subscribe_entities(entity_ids: List[str]):
            _LOG.info(f"Remote subscribed to entities: {entity_ids}")
            self.subscribed_entities = set(entity_ids)
            await self._poll_entities()

    async def setup_handler(self, msg: SetupDriver) -> Any:
        setup_result = await self.setup_flow.handle_setup_request(msg)
        if isinstance(setup_result, uc.SetupComplete):
            _LOG.info("Setup complete. Initializing integration immediately.")
            await self._initialize_integration()
        return setup_result
    
    async def _load_entities_from_cache(self):
        _LOG.info("Loading entities from cache...")
        cached_devices = self.config_manager.load_devices()
        if not cached_devices:
            _LOG.info("No cached devices found.")
            return

        if not self.factory:
            # We pass None for the client as it's not needed to create placeholder entities
            self.factory = SmartThingsEntityFactory(None, self.api)
        
        config_stub = {} 
        for device_data in cached_devices:
            try:
                entity = self.factory.create_entity(device_data, config_stub, None)
                if entity:
                    self.api.available_entities.add(entity)
            except Exception as e:
                _LOG.error(f"Error creating cached entity: {e}")
        _LOG.info(f"Loaded {len(self.api.available_entities)} entities from cache.")

    async def _initialize_integration(self):
        await self._cleanup(soft=True)
        try:
            await self.api.set_device_state(DeviceStates.CONNECTING)
            
            self.config = self.config_manager.load_config()
            access_token = self.config.get("access_token")
            if not access_token: 
                _LOG.error("No access token found in configuration.")
                await self.api.set_device_state(DeviceStates.ERROR)
                return

            self.client = SmartThingsClient(access_token)
            if not self.factory:
                self.factory = SmartThingsEntityFactory(self.client, self.api)
            else:
                # Update the factory with the live client
                self.factory._client = self.client

            await self._sync_entities()
            
            await self.api.set_device_state(DeviceStates.CONNECTED)
            _LOG.info("SmartThings integration initialized successfully")

            self._start_polling()
            
        except Exception as e:
            _LOG.error(f"Failed to initialize integration: {e}", exc_info=True)
            await self.api.set_device_state(DeviceStates.ERROR)
    
    async def _sync_entities(self):
        if not self.client or not self.factory:
            _LOG.error("Client or factory not available for entity sync.")
            return
            
        _LOG.info("Syncing entities with SmartThings API...")
        try:
            location_id = self.config.get("location_id")
            if not location_id: 
                _LOG.error("No location_id found in configuration")
                return
                
            async with self.client:
                fresh_devices = await self.client.get_devices(location_id)
                rooms = await self.client.get_rooms(location_id)
            
            self.config_manager.save_devices(fresh_devices)
            
            room_map = {room.get("roomId"): room.get("name") for room in rooms}
            
            current_entity_ids = {e.id for e in self.api.available_entities}
            fresh_entity_ids = set()

            for device_data in fresh_devices:
                entity = self.factory.create_entity(device_data, self.config, room_map.get(device_data.get("roomId")))
                if not entity:
                    continue

                fresh_entity_ids.add(entity.id)
                if entity.id in current_entity_ids:
                    self.api.available_entities.update(entity)
                else:
                    self.api.available_entities.add(entity)
                    _LOG.info(f"Discovered new entity: {entity.name} ({entity.id})")

            stale_entity_ids = current_entity_ids - fresh_entity_ids
            for entity_id in stale_entity_ids:
                self.api.available_entities.remove(entity_id)
                _LOG.info(f"Removed stale entity: {entity_id}")

            _LOG.info(f"Entity sync complete. Total entities: {len(self.api.available_entities)}")

        except Exception as e:
            _LOG.error(f"Failed to sync entities: {e}", exc_info=True)

    def _start_polling(self):
        if self.polling_task and not self.polling_task.done():
            _LOG.debug("Polling is already active.")
            return
        
        _LOG.info("Starting background polling loop.")
        self.polling_task = self.loop.create_task(self._polling_loop())
    
    async def _polling_loop(self):
        while True:
            try:
                # Give the system a moment to connect before the first poll
                await asyncio.sleep(5)
                await self._poll_entities()
                polling_interval = self.config.get("polling_interval", 30)
                await asyncio.sleep(polling_interval)
            except asyncio.CancelledError:
                _LOG.info("Polling loop cancelled.")
                break
            except Exception as e:
                _LOG.error(f"Error in polling loop: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def _poll_entities(self):
        if not self.subscribed_entities or not self.client:
            _LOG.debug("No subscribed entities to poll or client not ready.")
            return

        _LOG.debug(f"Polling status for {len(self.subscribed_entities)} entities...")
        tasks = []
        for entity_id in self.subscribed_entities:
            entity = self.api.configured_entities.get(entity_id)
            if entity:
                device_id = entity.id[3:]
                tasks.append(self._update_entity_status(entity, device_id))
        
        if tasks:
            await asyncio.gather(*tasks)

    async def _update_entity_status(self, entity: Entity, device_id: str):
        try:
            async with self.client:
                status = await self.client.get_device_status(device_id)
            if status:
                self.factory.update_entity_attributes(entity, status)
                self.api.configured_entities.update_attributes(entity.id, entity.attributes)
        except Exception as e:
            _LOG.warning(f"Failed to poll entity {entity.id}: {e}")

    async def _cleanup(self, soft=False):
        if self.polling_task and not self.polling_task.done():
            self.polling_task.cancel()
            try:
                await self.polling_task
            except asyncio.CancelledError:
                pass
            self.polling_task = None
        
        if self.client: 
            await self.client.close()
            self.client = None
        
        # On a soft cleanup (reconnect), don't clear subscribed entities
        if not soft:
            self.subscribed_entities.clear()

        _LOG.info("Integration cleanup completed")

async def main():
    loop = asyncio.get_event_loop()
    api = IntegrationAPI(loop)
    integration = SmartThingsIntegration(api, loop)

    await integration._load_entities_from_cache()
    
    await api.init("driver.json", integration.setup_handler)
    
    _LOG.info("SmartThings Integration is now running. Press Ctrl+C to stop.")
    try:
        await api.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        _LOG.info("Integration shutdown requested")
    finally:
        await integration._cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _LOG.info("Integration stopped by user")