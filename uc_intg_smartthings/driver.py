"""
SmartThings Integration Driver for Unfolded Circle Remote 2/3

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
        self.entity_last_change = {}
        self.entity_last_command = {}
        self.subscribed_entities = set()
        self.polling_active = False
        
        self._register_event_handlers()
        
    def _register_event_handlers(self):
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
            _LOG.info(f"Remote subscribed to {len(entity_ids)} entities. Starting enhanced polling...")
            
            if not self.client or not self.factory:
                _LOG.error("Client or factory not available during subscription")
                return
            
            self.subscribed_entities = {eid for eid in entity_ids if eid.startswith("st_")}
            
            await self._sync_initial_state_immediate(list(self.subscribed_entities))
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
            
            self.factory.command_callback = self.track_entity_command
            
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

    async def _sync_initial_state_immediate(self, entity_ids: List[str]):
        _LOG.info(f"Syncing initial state for {len(entity_ids)} entities...")
        
        import time
        start_time = time.time()
        synced_count = 0
        
        batch_size = 4
        for i in range(0, len(entity_ids), batch_size):
            batch = entity_ids[i:i + batch_size]
            
            tasks = []
            for entity_id in batch:
                entity = self.api.configured_entities.get(entity_id)
                if entity:
                    device_id = entity_id[3:]
                    tasks.append(self._sync_single_entity(entity, device_id))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if result is True:
                        synced_count += 1
            
            if i + batch_size < len(entity_ids):
                await asyncio.sleep(0.2)
        
        sync_time = time.time() - start_time
        _LOG.info(f"Initial state synced for {synced_count}/{len(entity_ids)} entities in {sync_time:.1f}s")

    async def _sync_single_entity(self, entity, device_id: str) -> bool:
        try:
            async with self.client:
                device_status = await self.client.get_device_status(device_id)
                
            if device_status:
                old_attributes = dict(entity.attributes)
                self.factory.update_entity_attributes(entity, device_status)
                
                self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                
                if old_attributes != entity.attributes:
                    _LOG.info(f"Initial sync: {entity.name} -> {entity.attributes}")
                else:
                    _LOG.debug(f"Initial sync: {entity.name} (no change)")
                
                return True
                
        except Exception as e:
            _LOG.error(f"Failed to sync {entity.id}: {e}")
            return False

    async def _start_enhanced_polling(self):
        if self.status_update_task and not self.status_update_task.done():
            _LOG.debug("Enhanced polling already running")
            return
        
        self.polling_active = True
        self.status_update_task = self.loop.create_task(self._enhanced_polling_loop())
        _LOG.info("Enhanced polling started with command priority")
    
    async def _enhanced_polling_loop(self):
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.polling_active:
            try:
                if not self.subscribed_entities:
                    await asyncio.sleep(10)
                    continue
                
                await self._smart_poll_entities_with_priority()
                
                consecutive_errors = 0
                
                sleep_time = self._calculate_dynamic_sleep_with_commands()
                await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                _LOG.info("Enhanced polling loop cancelled")
                break
            except Exception as e:
                consecutive_errors += 1
                _LOG.error(f"Error in enhanced polling loop (#{consecutive_errors}): {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    _LOG.error(f"Too many consecutive errors ({consecutive_errors}), stopping polling")
                    break
                
                error_sleep = min(30, 5 * consecutive_errors)
                await asyncio.sleep(error_sleep)
        
        self.polling_active = False

    async def _smart_poll_entities_with_priority(self):
        """⚡ OPTIMIZED: Priority polling with command awareness"""
        import time
        now = time.time()
        entities_to_poll = []
        
        # ⚡ Separate entities by command activity
        high_priority_entities = []  # Recently commanded
        normal_priority_entities = []  # Regular polling
        
        for entity_id in self.subscribed_entities:
            entity = self.api.configured_entities.get(entity_id)
            if not entity:
                continue
            
            device_id = entity_id[3:]
            
            last_poll = self.entity_last_poll.get(entity_id, 0)
            last_change = self.entity_last_change.get(entity_id, 0)
            last_command = self.entity_last_command.get(entity_id, 0)
            
            if now - last_command < 30:
                required_interval = 1.0  # Very fast polling for user commands
                if now - last_poll >= required_interval:
                    high_priority_entities.append((entity_id, device_id, entity, "HIGH"))
            
            # Normal priority logic
            elif now - last_command < 30:
                required_interval = 2
            elif now - last_change < 60:
                required_interval = 4
            elif now - last_change < 300:
                required_interval = 8
            else:
                required_interval = 20
            
            if now - last_poll >= required_interval and entity_id not in [e[0] for e in high_priority_entities]:
                normal_priority_entities.append((entity_id, device_id, entity, "NORMAL"))
        
        if high_priority_entities:
            _LOG.debug(f"⚡ Priority polling {len(high_priority_entities)} recently commanded entities")
            changes = await self._poll_entity_batch_priority(high_priority_entities)
            if changes > 0:
                _LOG.info(f"⚡ High priority changes detected: {changes}")
        
        # Process normal entities
        if normal_priority_entities:
            batch_size = 5
            total_changes = 0
            
            for i in range(0, len(normal_priority_entities), batch_size):
                batch = normal_priority_entities[i:i + batch_size]
                batch_changes = await self._poll_entity_batch_priority(batch)
                total_changes += batch_changes
                
                if i + batch_size < len(normal_priority_entities):
                    await asyncio.sleep(0.3)
            
            if total_changes > 0:
                _LOG.info(f"Detected {total_changes} state changes in batch")

    async def _poll_entity_batch_priority(self, entity_batch):
        """⚡ OPTIMIZED: Batch polling with priority handling"""
        import time
        now = time.time()
        changes_detected = 0
        
        for entity_id, device_id, entity, priority in entity_batch:
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
                        
                        if priority == "HIGH":
                            _LOG.info(f"⚡ Priority state changed: {entity.name}")
                        else:
                            _LOG.info(f"State changed: {entity.name}")
                    
                    self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                    
                else:
                    _LOG.debug(f"No status data for {entity.name}")
                        
            except Exception as e:
                _LOG.warning(f"Failed to poll {entity_id}: {e}")
        
        return changes_detected

    def _calculate_dynamic_sleep_with_commands(self) -> float:
        """⚡ OPTIMIZED: Dynamic sleep with command awareness"""
        import time
        now = time.time()
        
        # ⚡ Count recent commands (higher weight than changes)
        recent_commands = sum(1 for last_cmd in self.entity_last_command.values() 
                             if now - last_cmd < 60)  # Extended window
        
        recent_changes = sum(1 for last_change in self.entity_last_change.values() 
                            if now - last_change < 300)
        
        # ⚡ Commands get priority in sleep calculation
        if recent_commands > 0:
            return 0.2  # Very fast for active commanding
        elif recent_changes > 8:
            return 1.0
        elif recent_changes > 4:
            return 2.0
        elif recent_changes > 1:
            return 3.0
        else:
            return 5.0

    def track_entity_command(self, entity_id: str):
        """⚡ Track user commands for priority polling"""
        import time
        self.entity_last_command[entity_id] = time.time()
        _LOG.debug(f"⚡ Tracked priority command for {entity_id}")

    async def _cleanup(self):
        self.polling_active = False
        
        if self.status_update_task and not self.status_update_task.done():
            self.status_update_task.cancel()
            try:
                await self.status_update_task
            except asyncio.CancelledError:
                pass
        
        if self.factory:
            for task in self.factory.state_sync_tasks.values():
                if not task.done():
                    task.cancel()
            self.factory.state_sync_tasks.clear()
                
        if self.client: 
            await self.client.close()
        
        self.entity_last_poll.clear()
        self.entity_last_change.clear()
        self.entity_last_command.clear()
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