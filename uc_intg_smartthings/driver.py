"""
Main SmartThings Integration Driver for Unfolded Circle Remote 2/3

:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details
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
    """Main SmartThings integration class with enhanced polling."""
    
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
        self.entity_last_change = {}
        self.subscribed_entities = set()
        
        self._register_event_handlers()
        
    def _register_event_handlers(self):
        """Register event handlers for UC Remote events."""
        @self.api.listens_to(Events.CONNECT)
        async def on_connect():
            _LOG.info("Connected to UC Remote")
            if self.config_manager.is_configured():
                await self._initialize_integration()
            else:
                await self.api.set_device_state(DeviceStates.DISCONNECTED)
                
        @self.api.listens_to(Events.DISCONNECT)
        async def on_disconnect():
            await self._cleanup()

        @self.api.listens_to(Events.SUBSCRIBE_ENTITIES)
        async def on_subscribe_entities(entity_ids: List[str]):
            """Enhanced handler with smart polling and initial state sync."""
            _LOG.info(f"Remote subscribed to {len(entity_ids)} entities. Starting enhanced polling...")
            
            if not self.client or not self.factory:
                _LOG.error("Client or factory not available during subscription")
                return
            
            self.subscribed_entities = {eid for eid in entity_ids if eid.startswith("st_")}
            
            await self._sync_initial_state_batch(list(self.subscribed_entities))
            await self._start_enhanced_polling()
            
    async def setup_handler(self, msg: SetupDriver) -> Any:
        setup_result = await self.setup_flow.handle_setup_request(msg)
        if isinstance(setup_result, uc.SetupComplete):
            _LOG.info("Setup complete. Initializing on next connect.")
        return setup_result
    
    async def _initialize_integration(self):
        await self._cleanup()
        try:
            await self.api.set_device_state(DeviceStates.CONNECTING)
            self.config = self.config_manager.load_config()
            access_token = self.config.get("access_token")
            if not access_token: 
                _LOG.error("No access token found in configuration")
                return

            self.client = SmartThingsClient(access_token)
            self.factory = SmartThingsEntityFactory(self.client, self.api)
            
            await self._create_entities()
            
            await self.api.set_device_state(DeviceStates.CONNECTED)
            _LOG.info("SmartThings integration initialized successfully")
            
        except Exception as e:
            _LOG.error(f"Failed to initialize integration: {e}", exc_info=True)
            await self.api.set_device_state(DeviceStates.ERROR)
    
    async def _create_entities(self):
        if not self.client or not self.factory: 
            _LOG.error("Client or factory not available for entity creation")
            return
            
        try:
            location_id = self.config.get("location_id")
            if not location_id: 
                _LOG.error("No location_id found in configuration")
                return
                
            async with self.client:
                devices_raw = await self.client.get_devices(location_id)
                rooms = await self.client.get_rooms(location_id)
            
            room_names = {room["roomId"]: room["name"] for room in rooms}
            self.api.available_entities.clear()
            created_count = 0
            
            _LOG.info(f"Processing {len(devices_raw)} devices from SmartThings...")
            
            for device_data in devices_raw:
                try:
                    entity = self.factory.create_entity(device_data, self.config, room_names.get(device_data.get("roomId")))
                    if entity:
                        if self.api.available_entities.add(entity):
                            created_count += 1
                            _LOG.debug(f"Added entity: {entity.id} ({entity.name})")
                        else:
                            _LOG.warning(f"Failed to add entity: {entity.id}")
                except Exception as e:
                    device_name = device_data.get("label", device_data.get("name", "Unknown"))
                    _LOG.error(f"Error creating entity for device {device_name}: {e}")

            _LOG.info(f"Created {created_count} entities from {len(devices_raw)} devices")

        except Exception as e:
            _LOG.error(f"Failed to create entities: {e}", exc_info=True)

    async def _sync_initial_state_batch(self, entity_ids: List[str]):
        """Sync initial state for subscribed entities using batch processing."""
        _LOG.info(f"Syncing initial state for {len(entity_ids)} entities...")
        
        device_ids = [eid[3:] for eid in entity_ids]
        
        synced_count = 0
        for device_id in device_ids:
            entity_id = f"st_{device_id}"
            entity = self.api.configured_entities.get(entity_id)
            if not entity:
                continue
                
            try:
                async with self.client:
                    device_status = await self.client.get_device_status(device_id)
                    if device_status:
                        self.factory.update_entity_attributes(entity, device_status)
                        self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                        synced_count += 1
                        _LOG.debug(f"Initial sync: {entity.name} -> {entity.attributes}")
            except Exception as e:
                _LOG.error(f"Failed to sync initial state for {entity_id}: {e}")
        
        _LOG.info(f"Initial state synced for {synced_count} entities")

    async def _start_enhanced_polling(self):
        """Start enhanced polling with adaptive intervals."""
        if self.status_update_task and not self.status_update_task.done():
            _LOG.debug("Enhanced polling already running")
            return
        
        self.status_update_task = self.loop.create_task(self._enhanced_polling_loop())
        _LOG.info("Enhanced polling started with adaptive intervals")
    
    async def _enhanced_polling_loop(self):
        """Enhanced polling loop with smart intervals based on entity activity."""
        while True:
            try:
                if not self.subscribed_entities:
                    await asyncio.sleep(10)
                    continue
                
                await self._smart_poll_entities()
                
                sleep_time = self._calculate_dynamic_sleep()
                await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                _LOG.info("Enhanced polling loop cancelled")
                break
            except Exception as e:
                _LOG.error(f"Error in enhanced polling loop: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def _smart_poll_entities(self):
        """Smart polling with priority-based intervals."""
        import time
        now = time.time()
        entities_to_poll = []
        
        for entity_id in self.subscribed_entities:
            entity = self.api.configured_entities.get(entity_id)
            if not entity:
                continue
            
            device_id = entity_id[3:]
            
            last_poll = self.entity_last_poll.get(entity_id, 0)
            last_change = self.entity_last_change.get(entity_id, 0)
            
            if now - last_change < 60:
                required_interval = 3
            elif now - last_change < 300:
                required_interval = 8
            else:
                required_interval = 20
            
            if now - last_poll >= required_interval:
                entities_to_poll.append((entity_id, device_id))
        
        if not entities_to_poll:
            return
        
        _LOG.debug(f"Smart polling {len(entities_to_poll)} entities")
        
        batch_size = 8
        for i in range(0, len(entities_to_poll), batch_size):
            batch = entities_to_poll[i:i + batch_size]
            await self._poll_entity_batch(batch)
            
            if i + batch_size < len(entities_to_poll):
                await asyncio.sleep(0.5)

    async def _poll_entity_batch(self, entity_batch):
        """Poll a batch of entities efficiently."""
        import time
        now = time.time()
        changes_detected = 0
        
        for entity_id, device_id in entity_batch:
            entity = self.api.configured_entities.get(entity_id)
            if not entity:
                continue
            
            try:
                old_attributes = dict(entity.attributes)
                
                async with self.client:
                    device_status = await self.client.get_device_status(device_id)
                    
                if device_status:
                    self.factory.update_entity_attributes(entity, device_status)
                    
                    self.entity_last_poll[entity_id] = now
                    
                    if old_attributes != entity.attributes:
                        changes_detected += 1
                        self.entity_last_change[entity_id] = now
                        
                        self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                        _LOG.info(f"State changed: {entity.name}")
                    else:
                        _LOG.debug(f"No change: {entity.name}")
                        
            except Exception as e:
                _LOG.warning(f"Failed to poll {entity_id}: {e}")
        
        if changes_detected > 0:
            _LOG.info(f"Detected {changes_detected} state changes in batch")

    def _calculate_dynamic_sleep(self) -> float:
        """Calculate dynamic sleep based on recent activity."""
        import time
        now = time.time()
        
        recent_changes = sum(1 for last_change in self.entity_last_change.values() 
                           if now - last_change < 300)
        
        if recent_changes > 5:
            return 1.0
        elif recent_changes > 2:
            return 2.0
        else:
            return 4.0

    async def _cleanup(self):
        """Enhanced cleanup with better task management."""
        if self.status_update_task and not self.status_update_task.done():
            self.status_update_task.cancel()
            try:
                await self.status_update_task
            except asyncio.CancelledError:
                pass
                
        if self.client: 
            await self.client.close()
        
        self.entity_last_poll.clear()
        self.entity_last_change.clear()
        self.subscribed_entities.clear()
            
        _LOG.info("Integration cleanup completed")

async def main():
    loop = asyncio.get_event_loop()
    api = IntegrationAPI(loop)
    integration = SmartThingsIntegration(api, loop)
    await api.init("driver.json", integration.setup_handler)
    
    _LOG.info("SmartThings Integration is now running. Press Ctrl+C to stop.")
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