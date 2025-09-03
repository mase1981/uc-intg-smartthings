"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, List

from ucapi import IntegrationAPI
from ucapi.api_definitions import Events, DeviceStates, SetupDriver
import ucapi.api_definitions as uc

from uc_intg_smartthings.client import SmartThingsClient
from uc_intg_smartthings.entities import SmartThingsEntityFactory
from uc_intg_smartthings.setup_flow import SmartThingsSetupFlow
from uc_intg_smartthings.config import ConfigManager

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
        self.status_update_task: Optional[asyncio.Task] = None

        self.entity_last_poll = {}
        self.subscribed_entities = set()
        self.polling_active = False
        self.devices_in_command = set()
        
        # CRITICAL FIX: Track initialization state
        self.entities_ready = False
        self.initialization_lock = asyncio.Lock()

        self._register_event_handlers()

    def _register_event_handlers(self):
        @self.api.listens_to(Events.CONNECT)
        async def on_connect():
            _LOG.info("UC Remote connected - checking if entities are ready")
            
            if self.config_manager.is_configured():
                if not self.entities_ready:
                    _LOG.info("Entities not ready yet - initializing now")
                    await self._initialize_integration()
                else:
                    _LOG.info("Entities already ready - setting state to CONNECTED")
                    await self.api.set_device_state(DeviceStates.CONNECTED)
                    await self._start_polling()
            else:
                await self.api.set_device_state(DeviceStates.AWAITING_SETUP)

        @self.api.listens_to(Events.DISCONNECT)
        async def on_disconnect():
            await self._cleanup()

        @self.api.listens_to(Events.SUBSCRIBE_ENTITIES)
        async def on_subscribe_entities(entity_ids: List[str]):
            _LOG.info(f"Subscription request for {len(entity_ids)} entities")
            
            if not self.entities_ready:
                _LOG.error("CRITICAL: Subscription attempted before entities are ready!")
                # Try to initialize immediately
                await self._initialize_integration()
                
            if not self.client or not self.factory:
                _LOG.error("Client or factory not available during subscription")
                return

            self.subscribed_entities = {eid for eid in entity_ids if eid.startswith("st_")}
            _LOG.info(f"Tracking {len(self.subscribed_entities)} subscribed entities")
            
            await self._sync_initial_state_immediate(list(self.subscribed_entities))

    async def setup_handler(self, msg: SetupDriver) -> Any:
        setup_result = await self.setup_flow.handle_setup_request(msg)
        if isinstance(setup_result, uc.SetupComplete):
            _LOG.info("Setup complete. Pre-initializing entities before UC Remote connects")

            await self._initialize_integration()
        return setup_result

    async def _initialize_integration(self):
        """Initialize integration and ensure entities are ready"""
        async with self.initialization_lock:
            if self.entities_ready:
                _LOG.debug("Entities already initialized")
                return
                
            try:
                await self.api.set_device_state(DeviceStates.CONNECTING)
                _LOG.info("=== STARTING INTEGRATION INITIALIZATION ===")
                
                # Load config and create client
                self.config = self.config_manager.load_config()
                access_token = self.config.get("access_token")
                if not access_token:
                    _LOG.error("No access token found in configuration")
                    await self.api.set_device_state(DeviceStates.ERROR)
                    return

                self.client = SmartThingsClient(access_token)
                self.factory = SmartThingsEntityFactory(self.client, self.api)
                self.factory.command_callback = self.track_device_command

                # CRITICAL FIX: Create ALL entities FIRST, before setting CONNECTED
                await self._create_all_entities()
                
                # Mark entities as ready BEFORE setting CONNECTED state
                self.entities_ready = True
                _LOG.info("=== ENTITIES READY - UC Remote can now safely connect ===")
                
                await self.api.set_device_state(DeviceStates.CONNECTED)
                _LOG.info("SmartThings integration initialized successfully")

            except Exception as e:
                _LOG.error(f"Failed to initialize integration: {e}", exc_info=True)
                await self.api.set_device_state(DeviceStates.ERROR)

    async def _create_all_entities(self):
        """Create all entities and add them to available_entities"""
        try:
            location_id = self.config.get("location_id")
            if not location_id:
                _LOG.error("No location_id found in configuration")
                return

            # Clear any existing entities to prevent duplicates
            self.api.available_entities.clear()
            _LOG.info("Cleared existing available entities")

            # Fetch devices and rooms
            async with self.client:
                devices_raw = await self.client.get_devices(location_id)
                rooms = await self.client.get_rooms(location_id)

            room_names = {room["roomId"]: room["name"] for room in rooms}
            created_count = 0
            total_devices = len(devices_raw)

            _LOG.info(f"Processing {total_devices} devices from SmartThings...")

            # Create all entities in one go
            for i, device_data in enumerate(devices_raw, 1):
                try:
                    device_name = device_data.get("label") or device_data.get("name", "Unknown")
                    area = room_names.get(device_data.get("roomId"))
                    
                    entity = self.factory.create_entity(device_data, self.config, area)
                    if entity:
                        if self.api.available_entities.add(entity):
                            created_count += 1
                            _LOG.debug(f"[{i}/{total_devices}] Created entity: {entity.id} ({device_name})")
                        else:
                            _LOG.warning(f"Failed to add entity {entity.id} to available_entities")

                except Exception as e:
                    device_name = device_data.get("label", device_data.get("name", "Unknown"))
                    _LOG.error(f"Error creating entity for device {device_name}: {e}")

            _LOG.info(f"=== ENTITY CREATION COMPLETE: {created_count}/{total_devices} entities ready ===")
            
            # Verify entities are actually available
            available_count = len(self.api.available_entities.get_all())
            _LOG.info(f"Verification: {available_count} entities in available_entities store")
            
            if available_count != created_count:
                _LOG.error(f"MISMATCH: Created {created_count} but only {available_count} in store!")
            
            return created_count > 0

        except Exception as e:
            _LOG.error(f"Failed to create entities: {e}", exc_info=True)
            return False

    async def _sync_initial_state_immediate(self, entity_ids: List[str]):
        _LOG.info(f"Starting initial state sync for {len(entity_ids)} entities")

        # Wait a moment for entities to settle in configured_entities
        await asyncio.sleep(0.5)
        
        configured_entities = list(self.api.configured_entities._storage.keys())
        _LOG.info(f"Configured entities available: {len(configured_entities)}")

        if len(configured_entities) == 0:
            _LOG.error("No configured entities found - subscription likely failed")
            return

        import time
        start_time = time.time()
        synced_count = 0

        # Sync in smaller batches to be gentle on the API
        batch_size = 5
        for i in range(0, len(entity_ids), batch_size):
            batch = entity_ids[i:i + batch_size]
            batch_results = await asyncio.gather(
                *[self._sync_single_entity_safe(entity_id) for entity_id in batch],
                return_exceptions=True
            )
            
            for result in batch_results:
                if result is True:
                    synced_count += 1

            # Small delay between batches
            if i + batch_size < len(entity_ids):
                await asyncio.sleep(0.2)

        sync_time = time.time() - start_time
        _LOG.info(f"Initial state sync completed: {synced_count}/{len(entity_ids)} entities in {sync_time:.1f}s")

    async def _sync_single_entity_safe(self, entity_id: str) -> bool:
        """Safely sync a single entity with error handling"""
        try:
            entity = self.api.configured_entities.get(entity_id)
            if not entity:
                _LOG.warning(f"Entity {entity_id} not found in configured_entities")
                return False

            device_id = entity_id[3:]  # Remove 'st_' prefix
            
            async with self.client:
                device_status = await self.client.get_device_status(device_id)

            if device_status:
                self.factory.update_entity_attributes(entity, device_status)
                self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                _LOG.debug(f"Synced state for {entity.name}")
                return True
            else:
                _LOG.warning(f"No status data for {entity_id}")
                return False

        except Exception as e:
            _LOG.error(f"Failed to sync entity {entity_id}: {e}")
            return False

    async def _start_polling(self):
        if self.status_update_task and not self.status_update_task.done():
            _LOG.debug("Polling already running")
            return

        self.polling_active = True
        self.status_update_task = self.loop.create_task(self._polling_loop())
        _LOG.info("Background polling started")

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
                _LOG.info("Polling loop cancelled")
                break
            except Exception as e:
                consecutive_errors += 1
                _LOG.error(f"Error in polling loop (#{consecutive_errors}): {e}")

                if consecutive_errors >= max_consecutive_errors:
                    _LOG.error(f"Too many consecutive errors ({consecutive_errors}), stopping polling")
                    break

                await asyncio.sleep(min(30, 5 * consecutive_errors))

        self.polling_active = False

    async def _poll_entities_intelligently(self):
        """Poll entities intelligently based on activity"""
        import time
        now = time.time()
        entities_to_poll = []

        for entity_id in self.subscribed_entities:
            entity = self.api.configured_entities.get(entity_id)
            if not entity:
                continue

            device_id = entity_id[3:]
            if device_id in self.devices_in_command:
                continue

            last_poll = self.entity_last_poll.get(entity_id, 0)
            required_interval = self._get_entity_polling_interval(entity_id, now)

            if now - last_poll >= required_interval:
                entities_to_poll.append((entity_id, device_id, entity))

        if entities_to_poll:
            _LOG.debug(f"Polling {len(entities_to_poll)} entities")
            changes = await self._poll_entity_batch(entities_to_poll)
            if changes > 0:
                _LOG.info(f"Detected {changes} state changes")

    async def _poll_entity_batch(self, entity_batch):
        """Poll a batch of entities"""
        import time
        now = time.time()
        changes_detected = 0

        batch_size = 5
        for i in range(0, len(entity_batch), batch_size):
            batch = entity_batch[i:i + batch_size]
            
            for entity_id, device_id, entity in batch:
                try:
                    old_attributes = dict(entity.attributes)

                    async with self.client:
                        device_status = await self.client.get_device_status(device_id)

                    if device_status:
                        self.factory.update_entity_attributes(entity, device_status)
                        self.entity_last_poll[entity_id] = now

                        if old_attributes != entity.attributes:
                            changes_detected += 1
                            _LOG.debug(f"State change: {entity.name}")

                        self.api.configured_entities.update_attributes(entity.id, entity.attributes)

                except Exception as e:
                    _LOG.warning(f"Failed to poll {entity_id}: {e}")
            
            # Small delay between batches
            if i + batch_size < len(entity_batch):
                await asyncio.sleep(0.3)

        return changes_detected

    def _get_entity_polling_interval(self, entity_id: str, now: float) -> float:
        """Get polling interval for entity based on type"""
        base_interval = self.config.get("polling_interval", 12)
        entity = self.api.configured_entities.get(entity_id)
        
        if not entity:
            return base_interval

        entity_type = getattr(entity, 'entity_type', None)
        if entity_type in ['light', 'switch']:
            return max(base_interval * 0.8, 6)
        elif entity_type == 'sensor':
            return base_interval * 2
        elif entity_type in ['climate', 'cover']:
            return max(base_interval * 1.2, 10)
        else:
            return base_interval

    def _calculate_polling_interval(self) -> float:
        """Calculate dynamic polling interval"""
        import time

        if self.devices_in_command:
            return 15.0

        if (hasattr(self.client, '_last_rate_limit') and
            time.time() - self.client._last_rate_limit < 60):
            return 25.0

        base_config = self.config.get("polling_interval", 12)
        entity_count = len(self.subscribed_entities)

        if entity_count <= 3:
            return max(base_config * 2, 15)
        elif entity_count <= 10:
            return max(base_config * 3, 20)
        else:
            return max(base_config * 4, 30)

    def track_device_command(self, entity_id: str):
        """Track device commands to avoid polling conflicts"""
        device_id = entity_id[3:] if entity_id.startswith("st_") else entity_id
        self.devices_in_command.add(device_id)

        async def remove_device_from_command():
            await asyncio.sleep(3.0)
            self.devices_in_command.discard(device_id)

        asyncio.create_task(remove_device_from_command())

    async def _cleanup(self):
        """Clean up integration resources"""
        self.polling_active = False
        self.entities_ready = False

        if self.status_update_task and not self.status_update_task.done():
            self.status_update_task.cancel()
            try:
                await self.status_update_task
            except asyncio.CancelledError:
                pass

        if self.client:
            await self.client.close()

        self.entity_last_poll.clear()
        self.subscribed_entities.clear()
        self.devices_in_command.clear()

        _LOG.info("Integration cleanup completed")


async def main():
    """Main entry point - initialize integration on startup"""
    loop = asyncio.get_event_loop()
    api = IntegrationAPI(loop)
    integration = SmartThingsIntegration(api, loop)
    
    if integration.config_manager.is_configured():
        _LOG.info("Integration is configured - pre-initializing entities")
        loop.create_task(integration._initialize_integration())
    
    await api.init("driver.json", integration.setup_handler)

    _LOG.info("SmartThings Integration is running")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _LOG.info("Integration shutdown requested")
    finally:
        await integration._cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _LOG.info("Integration stopped by user")