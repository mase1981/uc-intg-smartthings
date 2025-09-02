"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details.

Corrected version to ensure persistence across reboots.
"""

import asyncio
import logging
import json
import os
from typing import Any, Dict, Optional, List, Set

from ucapi import IntegrationAPI, api_definitions
from ucapi.api_definitions import Events, DeviceStates, SetupDriver, WsMsgEvents
import ucapi.api_definitions as uc

# --- Helper Classes (included for a self-contained example) ---
# In a real project, these would be in separate files.

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
        with open(self.devices_path, 'r') as f:
            return json.load(f)

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
        # Returning an empty list to allow the flow to work.
        return []

    async def get_rooms(self, location_id: str) -> List[Dict]:
        _LOG.info("Fetching rooms from SmartThings API...")
        return []

    async def get_device_status(self, device_id: str) -> Dict:
        # Placeholder for fetching live status.
        return {}

    async def close(self):
        _LOG.info("SmartThingsClient closed.")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class SmartThingsEntityFactory:
    """A placeholder for the entity factory."""
    def __init__(self, client: SmartThingsClient, api: IntegrationAPI):
        self._client = client
        self._api = api
        self.command_callback = None

    def create_entity(self, device_data: Dict, config: Dict, room_name: Optional[str]) -> Optional[api_definitions.Entity]:
        # This factory would contain the logic to convert SmartThings device data
        # into Unfolded Circle entity objects.
        pass

    def update_entity_attributes(self, entity: api_definitions.Entity, status: Dict):
        # This would update an entity's attributes based on new status data.
        pass

class SmartThingsSetupFlow:
    """A placeholder for the setup flow handler."""
    def __init__(self, api: IntegrationAPI, config_manager: ConfigManager):
        self._api = api
        self._config_manager = config_manager

    async def handle_setup_request(self, msg: SetupDriver) -> Any:
        # This would handle the multi-step setup process.
        # On the final step, it saves the config and returns SetupComplete.
        if msg.step_id == "finalize":
             # Example: final configuration is received and saved
            final_config = msg.user_input
            self._config_manager.save_config(final_config)
            return uc.SetupComplete()
        pass


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
                # Configuration exists, proceed with initialization
                await self._initialize_integration()
            else:
                # Not configured, wait for setup
                await self.api.set_device_state(DeviceStates.AWAITING_SETUP)
                
        @self.api.listens_to(Events.DISCONNECT)
        async def on_disconnect():
            await self._cleanup()

        @self.api.listens_to(WsMsgEvents.SUBSCRIBE_ENTITIES)
        async def on_subscribe_entities(entity_ids: List[str]):
            _LOG.info(f"Remote subscribed to entities: {entity_ids}")
            self.subscribed_entities = set(entity_ids)
            # Perform an immediate poll of subscribed entities for quick feedback
            await self._poll_entities()

    async def setup_handler(self, msg: SetupDriver) -> Any:
        setup_result = await self.setup_flow.handle_setup_request(msg)
        if isinstance(setup_result, uc.SetupComplete):
            _LOG.info("Setup complete. Initializing integration immediately.")
            # **FIX**: Initialize immediately after setup is complete
            await self._initialize_integration()
        return setup_result
    
    async def _load_entities_from_cache(self):
        """
        **FIX**: Load entities from a cached file on startup.
        This pre-populates `api.available_entities` to prevent race conditions.
        """
        _LOG.info("Loading entities from cache...")
        cached_devices = self.config_manager.load_devices()
        if not cached_devices:
            _LOG.info("No cached devices found.")
            return

        # Lazily create the factory if it doesn't exist yet
        if not self.factory:
            self.factory = SmartThingsEntityFactory(None, self.api)
        
        # This assumes config is not needed to create placeholder entities
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
        await self._cleanup()
        try:
            await self.api.set_device_state(DeviceStates.CONNECTING)
            
            # **FIX**: Ensure config is freshly loaded on each connect
            self.config = self.config_manager.load_config()
            access_token = self.config.get("access_token")
            if not access_token: 
                _LOG.error("No access token found in configuration.")
                await self.api.set_device_state(DeviceStates.ERROR)
                return

            self.client = SmartThingsClient(access_token)
            self.factory = SmartThingsEntityFactory(self.client, self.api)
            
            await self._sync_entities()
            
            await self.api.set_device_state(DeviceStates.CONNECTED)
            _LOG.info("SmartThings integration initialized successfully")

            # **FIX**: Start the monitoring loop from a reliable location
            self._start_polling()
            
        except Exception as e:
            _LOG.error(f"Failed to initialize integration: {e}", exc_info=True)
            await self.api.set_device_state(DeviceStates.ERROR)
    
    async def _sync_entities(self):
        """
        **FIX**: Fetch fresh device data, compare with cache, and update entities.
        Saves the new device list to the cache for the next restart.
        """
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
            
            # Save the fresh list to cache for the next run
            self.config_manager.save_devices(fresh_devices)
            
            room_map = {room["roomId"]: room["name"] for room in rooms}
            
            # Sync logic
            current_entity_ids = {e.id for e in self.api.available_entities}
            fresh_device_ids = set()

            for device_data in fresh_devices:
                entity = self.factory.create_entity(device_data, self.config, room_map.get(device_data.get("roomId")))
                if not entity:
                    continue

                fresh_device_ids.add(entity.id)
                if entity.id in current_entity_ids:
                    # Update existing entity if needed (e.g., name change)
                    self.api.available_entities.update(entity)
                else:
                    # Add new entity
                    self.api.available_entities.add(entity)
                    _LOG.info(f"Discovered new entity: {entity.name} ({entity.id})")

            # Remove entities that no longer exist
            stale_entity_ids = current_entity_ids - fresh_device_ids
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
                await self._poll_entities()
                polling_interval = self.config.get("polling_interval", 30)
                await asyncio.sleep(polling_interval)
            except asyncio.CancelledError:
                _LOG.info("Polling loop cancelled.")
                break
            except Exception as e:
                _LOG.error(f"Error in polling loop: {e}", exc_info=True)
                await asyncio.sleep(60) # Wait longer after an error
    
    async def _poll_entities(self):
        if not self.subscribed_entities:
            _LOG.debug("No subscribed entities to poll.")
            return

        _LOG.debug(f"Polling status for {len(self.subscribed_entities)} entities...")
        tasks = []
        for entity_id in self.subscribed_entities:
            entity = self.api.configured_entities.get(entity_id)
            if entity:
                device_id = entity.id[3:] # Remove "st_" prefix
                tasks.append(self._update_entity_status(entity, device_id))
        
        if tasks:
            await asyncio.gather(*tasks)

    async def _update_entity_status(self, entity, device_id: str):
        try:
            async with self.client:
                status = await self.client.get_device_status(device_id)
            if status:
                self.factory.update_entity_attributes(entity, status)
                self.api.configured_entities.update_attributes(entity.id, entity.attributes)
        except Exception as e:
            _LOG.warning(f"Failed to poll entity {entity.id}: {e}")

    async def _cleanup(self):
        if self.polling_task and not self.polling_task.done():
            self.polling_task.cancel()
            try:
                await self.polling_task
            except asyncio.CancelledError:
                pass
        
        if self.client: 
            await self.client.close()
            
        _LOG.info("Integration cleanup completed")

async def main():
    loop = asyncio.get_event_loop()
    api = IntegrationAPI(loop)
    integration = SmartThingsIntegration(api, loop)

    # **FIX**: Pre-load entities from cache before starting the API connection
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