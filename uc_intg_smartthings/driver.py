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
    """SmartThings Integration - handles ONLY commands and state updates, NOT entity creation"""

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

        self._register_event_handlers()

    def _register_event_handlers(self):
        @self.api.listens_to(Events.CONNECT)
        async def on_connect():
            _LOG.info("UC Remote connected")
            if self.config_manager.is_configured():
                await self._connect_smartthings_api()
            else:
                await self.api.set_device_state(DeviceStates.AWAITING_SETUP)

        @self.api.listens_to(Events.DISCONNECT)
        async def on_disconnect():
            _LOG.info("UC Remote disconnected")
            await self._disconnect_smartthings_api()

        @self.api.listens_to(Events.SUBSCRIBE_ENTITIES)
        async def on_subscribe_entities(entity_ids: List[str]):
            smartthings_entities = [eid for eid in entity_ids if eid.startswith("st_")]
            _LOG.info(f"UC Remote subscribed to {len(smartthings_entities)} SmartThings entities")
            
            self.subscribed_entities = set(smartthings_entities)
            
            if smartthings_entities and self.client:
                await self._sync_entity_states(smartthings_entities)
                await self._start_polling()

        @self.api.listens_to(Events.UNSUBSCRIBE_ENTITIES)
        async def on_unsubscribe_entities(entity_ids: List[str]):
            for entity_id in entity_ids:
                self.subscribed_entities.discard(entity_id)
            _LOG.info(f"UC Remote unsubscribed from {len(entity_ids)} entities")

    async def _connect_smartthings_api(self):
        """Connect to SmartThings API - NO entity creation here"""
        try:
            await self.api.set_device_state(DeviceStates.CONNECTING)
            
            self.config = self.config_manager.load_config()
            access_token = self.config.get("access_token")
            
            if not access_token:
                _LOG.error("No SmartThings access token found")
                await self.api.set_device_state(DeviceStates.ERROR)
                return

            # Create API client
            if self.client:
                await self.client.close()
            
            self.client = SmartThingsClient(access_token)
            
            # Test connection
            async with self.client:
                locations = await self.client.get_locations()
                if not locations:
                    _LOG.error("No SmartThings locations accessible")
                    await self.api.set_device_state(DeviceStates.ERROR)
                    return

            # Create entity factory for state updates and commands
            self.factory = SmartThingsEntityFactory(self.client, self.api)
            self.factory.command_callback = self.track_device_command

            await self.api.set_device_state(DeviceStates.CONNECTED)
            _LOG.info("SmartThings API connection established")

        except Exception as e:
            _LOG.error(f"Failed to connect to SmartThings API: {e}", exc_info=True)
            await self.api.set_device_state(DeviceStates.ERROR)

    async def _disconnect_smartthings_api(self):
        """Disconnect from SmartThings API"""
        self.polling_active = False
        
        if self.status_update_task:
            self.status_update_task.cancel()
            try:
                await self.status_update_task
            except asyncio.CancelledError:
                pass
            self.status_update_task = None

        if self.client:
            await self.client.close()
            self.client = None
            
        self.factory = None
        self.subscribed_entities.clear()
        self.entity_last_poll.clear()
        self.devices_in_command.clear()
        
        _LOG.info("SmartThings API disconnected")

    async def setup_handler(self, msg: SetupDriver) -> Any:
        """Handle setup - this is where entities get created"""
        return await self.setup_flow.handle_setup_request(msg)

    async def _sync_entity_states(self, entity_ids: List[str]):
        """Sync states for existing entities"""
        if not self.client or not self.factory:
            return

        _LOG.info(f"Syncing states for {len(entity_ids)} entities")
        
        for entity_id in entity_ids:
            try:
                entity = self.api.configured_entities.get(entity_id)
                if not entity:
                    _LOG.warning(f"Entity {entity_id} not found - may need reconfiguration")
                    continue

                device_id = entity_id[3:]  # Remove 'st_' prefix
                
                async with self.client:
                    device_status = await self.client.get_device_status(device_id)

                if device_status:
                    old_attributes = dict(entity.attributes)
                    self.factory.update_entity_attributes(entity, device_status)
                    
                    if old_attributes != entity.attributes:
                        self.api.configured_entities.update_attributes(entity_id, entity.attributes)
                        _LOG.info(f"Synced {entity.name}: {entity.attributes}")

            except Exception as e:
                _LOG.error(f"Failed to sync {entity_id}: {e}")

    async def _start_polling(self):
        """Start polling for state changes"""
        if self.status_update_task and not self.status_update_task.done():
            return

        self.polling_active = True
        self.status_update_task = self.loop.create_task(self._polling_loop())
        _LOG.info("State polling started")

    async def _polling_loop(self):
        """Poll entities for state changes"""
        consecutive_errors = 0
        max_errors = 5

        while self.polling_active:
            try:
                if not self.subscribed_entities or not self.client or not self.factory:
                    await asyncio.sleep(15)
                    continue

                changes = 0
                
                for entity_id in list(self.subscribed_entities):
                    device_id = entity_id[3:]
                    
                    # Skip devices with active commands
                    if device_id in self.devices_in_command:
                        continue
                    
                    try:
                        entity = self.api.configured_entities.get(entity_id)
                        if not entity:
                            continue

                        async with self.client:
                            device_status = await self.client.get_device_status(device_id)

                        if device_status:
                            old_attributes = dict(entity.attributes)
                            self.factory.update_entity_attributes(entity, device_status)

                            if old_attributes != entity.attributes:
                                changes += 1
                                self.api.configured_entities.update_attributes(entity_id, entity.attributes)
                                _LOG.info(f"State change: {entity.name} -> {entity.attributes}")

                    except Exception as e:
                        _LOG.warning(f"Failed to poll {entity_id}: {e}")

                if changes > 0:
                    _LOG.debug(f"Polling round completed: {changes} changes detected")

                consecutive_errors = 0
                
                # Dynamic sleep based on activity
                sleep_time = 20 if self.devices_in_command else 15
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                _LOG.error(f"Polling error #{consecutive_errors}: {e}")
                
                if consecutive_errors >= max_errors:
                    _LOG.error("Too many polling errors - stopping")
                    break
                    
                await asyncio.sleep(min(30, consecutive_errors * 5))

        self.polling_active = False

    def track_device_command(self, entity_id: str):
        """Track command execution to pause polling"""
        device_id = entity_id[3:] if entity_id.startswith("st_") else entity_id
        self.devices_in_command.add(device_id)

        async def clear_command_flag():
            await asyncio.sleep(3.0)
            self.devices_in_command.discard(device_id)

        asyncio.create_task(clear_command_flag())

async def main():
    loop = asyncio.get_event_loop()
    api = IntegrationAPI(loop)
    integration = SmartThingsIntegration(api, loop)
    
    await api.init("driver.json", integration.setup_handler)
    
    _LOG.info("SmartThings Integration running")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _LOG.info("Integration shutdown requested")
    finally:
        await integration._disconnect_smartthings_api()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _LOG.info("Integration stopped")