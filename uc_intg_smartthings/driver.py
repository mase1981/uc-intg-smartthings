"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details.

Final corrected version for persistence, lifecycle, and bug fixes.
"""

import asyncio
import logging
import json
import os
import time
from typing import Any, Dict, Optional, List, Set

from ucapi import IntegrationAPI, api_definitions
from ucapi.entity import Entity
from ucapi.api_definitions import Events, DeviceStates, SetupDriver
import ucapi.api_definitions as uc

# --- Helper Classes (included for a self-contained example) ---
# In a real project, these would be in separate files.

class ConfigManager:
    """Manages loading and saving of configuration files."""
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        os.makedirs(config_dir, exist_ok=True)
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
        self._last_rate_limit = 0
        _LOG.info("SmartThingsClient initialized.")

    async def get_devices(self, location_id: str) -> List[Dict]:
        _LOG.info(f"Fetching devices for location {location_id} from SmartThings API...")
        # In a real implementation, this would make an HTTP request.
        # This is placeholder data.
        return []

    async def get_rooms(self, location_id: str) -> List[Dict]:
        _LOG.info(f"Fetching rooms for location {location_id} from SmartThings API...")
        # This is placeholder data.
        return [{"roomId": "room1", "name": "Living Room"}]

    async def get_device_status(self, device_id: str) -> Dict:
        return {"components": {"main": {}}}

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

    def create_entity(self, device_data: Dict, config: Dict, room_name: Optional[str]) -> Optional[Entity]:
        # This factory would contain the logic to convert SmartThings device data
        # into Unfolded Circle entity objects (e.g., uc.Light, uc.Switch).
        # This part needs the original implementation.
        return None

    def update_entity_attributes(self, entity: Entity, status: Dict):
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
            final_config = msg.user_input
            # Make sure minimum required config is present
            if "access_token" in final_config and "location_id" in final_config:
                self._config_manager.save_config(final_config)
                return uc.SetupComplete()
            else:
                return uc.SetupError("Missing access_token or location_id.")
        # Placeholder for other setup steps
        return uc.SetupError("Unknown setup step.")


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
        
        # Restored attributes for intelligent polling from original code
        self.status_update_task: Optional[asyncio.Task] = None
        self.entity_last_poll = {}
        self.subscribed_entities = set()
        self.polling_active = False
        self.devices_in_command = set()
        
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

        # **FIX**: Corrected WsMsgEvents to Events
        @self.api.listens_to(Events.SUBSCRIBE_ENTITIES)
        async def on_subscribe_entities(entity_ids: List[str]):
            _LOG.info(f"Remote subscribed to {len(entity_ids)} entities. Starting initial sync...")
            self.subscribed_entities = {eid for eid in entity_ids if eid.startswith("st_")}
            await self._sync_initial_state_immediate(list(self.subscribed_entities))
            
    async def setup_handler(self, msg: SetupDriver) -> Any:
        setup_result = await self.setup_flow.handle_setup_request(msg)
        if isinstance(setup_result, uc.SetupComplete):
            _LOG.info("Setup complete. Initializing integration immediately.")
            await self._initialize_integration()
        return setup_result
    
    async def _load_entities_from_cache(self):
        """Load entities from a cached file on startup to prevent race conditions."""
        _LOG.info("Loading entities from cache...")
        cached_devices = self.config_manager.load_devices()
        if not cached_devices:
            _LOG.info("No cached devices found.")
            return

        # Lazily create a factory with no client for placeholder creation
        if not self.factory:
            self.factory = SmartThingsEntityFactory(None, self.api)
        
        for device_data in cached_devices:
            try:
                # Room name and config are not critical for placeholder creation
                entity = self.factory.create_entity(device_data, {}, None)
                if entity:
                    self.api.available_entities.add(entity)
            except Exception as e:
                _LOG.error(f"Error creating cached entity for device {device_data.get('deviceId')}: {e}")
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
                # Ensure the factory has the live client
                self.factory._client = self.client

            # Set up command callback from original code
            self.factory.command_callback = self.track_device_command
            
            await self._sync_entities()
            
            await self.api.set_device_state(DeviceStates.CONNECTED)
            _LOG.info("SmartThings integration initialized successfully")
            
            # Start the main polling loop
            await self._start_polling()
            
        except Exception as e:
            _LOG.error(f"Failed to initialize integration: {e}", exc_info=True)
            await self.api.set_device_state(DeviceStates.ERROR)
    
    async def _sync_entities(self):
        """Fetch fresh device data, compare with cache, and update/add/remove entities."""
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

    # --- Polling and State Sync Logic (Restored from Original) ---
    async def _sync_initial_state_immediate(self, entity_ids: List[str]):
        _LOG.info(f"Syncing initial state for {len(entity_ids)} entities...")
        start_time = time.time()
        synced_count = 0
        batch_size = 6
        for i in range(0, len(entity_ids), batch_size):
            batch = entity_ids[i:i + batch_size]
            tasks = [self._sync_single_entity(eid) for eid in batch]
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if result is True:
                        synced_count += 1
            if i + batch_size < len(entity_ids):
                await asyncio.sleep(0.3)
        sync_time = time.time() - start_time
        _LOG.info(f"Initial state synced for {synced_count}/{len(entity_ids)} entities in {sync_time:.1f}s")

    async def _sync_single_entity(self, entity_id: str) -> bool:
        entity = self.api.configured_entities.get(entity_id)
        if not entity:
            return False
        try:
            device_id = entity_id[3:]
            async with self.client:
                device_status = await self.client.get_device_status(device_id)
            if device_status:
                self.factory.update_entity_attributes(entity, device_status)
                self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                _LOG.info(f"Initial sync: {entity.name} -> {entity.attributes}")
                return True
        except Exception as e:
            _LOG.error(f"Failed to sync {entity_id}: {e}")
        return False

    async def _start_polling(self):
        if self.status_update_task and not self.status_update_task.done():
            _LOG.debug("Polling already running.")
            return
        self.polling_active = True
        self.status_update_task = self.loop.create_task(self._polling_loop())
        _LOG.info("Background polling started.")
    
    async def _polling_loop(self):
        consecutive_errors = 0
        max_consecutive_errors = 5
        while self.polling_active:
            try:
                if not self.subscribed_entities:
                    await asyncio.sleep(10)
                    continue
                await self._poll_entities_intelligently()
                consecutive_errors = 0
                sleep_time = self._calculate_polling_interval()
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                _LOG.info("Polling loop cancelled.")
                break
            except Exception as e:
                consecutive_errors += 1
                _LOG.error(f"Error in polling loop (#{consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    _LOG.error("Too many errors, stopping polling.")
                    break
                await asyncio.sleep(min(30, 5 * consecutive_errors))
        self.polling_active = False

    async def _poll_entities_intelligently(self):
        now = time.time()
        entities_to_poll = []
        for entity_id in self.subscribed_entities:
            entity = self.api.configured_entities.get(entity_id)
            if not entity: continue
            device_id = entity_id[3:]
            if device_id in self.devices_in_command:
                _LOG.debug(f"Skipping poll for {entity.name} (command in progress)")
                continue
            last_poll = self.entity_last_poll.get(entity_id, 0)
            required_interval = self._get_entity_polling_interval(entity)
            if now - last_poll >= required_interval:
                entities_to_poll.append((entity_id, device_id, entity))
        
        if not entities_to_poll: return
        _LOG.debug(f"Polling {len(entities_to_poll)} entities.")
        
        batch_size = 5
        for i in range(0, len(entities_to_poll), batch_size):
            batch = entities_to_poll[i:i + batch_size]
            await self._poll_entity_batch(batch)
            if i + batch_size < len(entities_to_poll):
                await asyncio.sleep(0.4)

    async def _poll_entity_batch(self, entity_batch):
        now = time.time()
        for entity_id, device_id, entity in entity_batch:
            try:
                old_attributes = dict(entity.attributes)
                async with self.client:
                    device_status = await self.client.get_device_status(device_id)
                if device_status:
                    self.factory.update_entity_attributes(entity, device_status)
                    self.entity_last_poll[entity_id] = now
                    if old_attributes != entity.attributes:
                        _LOG.info(f"State changed via polling: {entity.name} -> {entity.attributes}")
                    self.api.configured_entities.update_attributes(entity.id, entity.attributes)
            except Exception as e:
                _LOG.warning(f"Failed to poll {entity_id}: {e}")

    def _get_entity_polling_interval(self, entity: Entity) -> float:
        base_interval = self.config.get("polling_interval", 12)
        entity_type = getattr(entity, 'entity_type', None)
        if entity_type in ['light', 'switch']: return max(base_interval * 0.8, 6)
        elif entity_type == 'sensor': return base_interval * 2
        elif entity_type in ['climate', 'cover']: return max(base_interval * 1.2, 10)
        return base_interval

    def _calculate_polling_interval(self) -> float:
        if self.devices_in_command: return 15.0
        if hasattr(self.client, '_last_rate_limit') and time.time() - self.client._last_rate_limit < 60:
            return 25.0
        base_config = self.config.get("polling_interval", 12)
        entity_count = len(self.subscribed_entities)
        if entity_count <= 3: return max(base_config * 2, 15)
        elif entity_count <= 10: return max(base_config * 3, 20)
        else: return max(base_config * 4, 30)

    def track_device_command(self, entity_id: str):
        device_id = entity_id[3:] if entity_id.startswith("st_") else entity_id
        self.devices_in_command.add(device_id)
        async def remove_after_timeout():
            await asyncio.sleep(3.0)
            self.devices_in_command.discard(device_id)
        asyncio.create_task(remove_after_timeout())
        _LOG.debug(f"Tracking command for device {device_id}")

    async def _cleanup(self, soft: bool = False):
        self.polling_active = False
        if self.status_update_task and not self.status_update_task.done():
            self.status_update_task.cancel()
            try: await self.status_update_task
            except asyncio.CancelledError: pass
        self.status_update_task = None
        
        if self.client: 
            await self.client.close()
            self.client = None
            
        if not soft:
            self.entity_last_poll.clear()
            self.subscribed_entities.clear()
            self.devices_in_command.clear()
            
        _LOG.info(f"Integration cleanup completed (Soft: {soft})")

async def main():
    loop = asyncio.get_event_loop()
    api = IntegrationAPI(loop)
    integration = SmartThingsIntegration(api, loop)

    # Pre-load entities from cache before starting the API connection
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