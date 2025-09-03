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
        self.devices_in_command = set()  # Track devices currently executing commands

        self._register_event_handlers()

    def _register_event_handlers(self):
        @self.api.listens_to(Events.CONNECT)
        async def on_connect():
            _LOG.info("Connected to UC Remote")
            if self.config_manager.is_configured():
                # Check if we need to recreate entities (they're missing after reboot)
                existing_entities = len(self.api.available_entities.get_all())
                _LOG.info(f"Found {existing_entities} existing entities")
                
                if existing_entities == 0:
                    _LOG.info("No entities found after reboot - recreating...")
                    await self._initialize_integration()
                else:
                    _LOG.info("Entities exist - reconnecting clients only...")
                    # Just reconnect without clearing entities - CRITICAL for reboot survival
                    self.config = self.config_manager.load_config()
                    access_token = self.config.get("access_token")
                    
                    if access_token:
                        if not self.client:
                            self.client = SmartThingsClient(access_token)
                            self.factory = SmartThingsEntityFactory(self.client, self.api)
                            self.factory.command_callback = self.track_device_command
                        
                        await self.api.set_device_state(DeviceStates.CONNECTED)
                        await self._start_polling()
                    else:
                        _LOG.error("No access token found in configuration")
                        await self.api.set_device_state(DeviceStates.ERROR)
            else:
                await self.api.set_device_state(DeviceStates.AWAITING_SETUP)

        @self.api.listens_to(Events.DISCONNECT)
        async def on_disconnect():
            await self._cleanup()

        @self.api.listens_to(Events.SUBSCRIBE_ENTITIES)
        async def on_subscribe_entities(entity_ids: List[str]):
            _LOG.info(f"Remote subscribed to {len(entity_ids)} entities. Starting polling...")

            if not self.client or not self.factory:
                _LOG.error("Client or factory not available during subscription")
                return

            self.subscribed_entities = {eid for eid in entity_ids if eid.startswith("st_")}

            await self._sync_initial_state_immediate(list(self.subscribed_entities))
            
            # ## CHANGE 1 of 3 ##
            # The polling loop is no longer started here. This was unreliable.
            # It's now started from a stable point after initialization.
            # await self._start_polling()

    async def setup_handler(self, msg: SetupDriver) -> Any:
        setup_result = await self.setup_flow.handle_setup_request(msg)
        if isinstance(setup_result, uc.SetupComplete):
            # ## CHANGE 2 of 3 ##
            # Initialize immediately after setup instead of waiting for a reconnect.
            # This makes the user experience much smoother.
            _LOG.info("Setup complete. Initializing integration immediately.")
            self.loop.create_task(self._initialize_integration())
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

            self.factory.command_callback = self.track_device_command

            await self._create_entities()

            await self.api.set_device_state(DeviceStates.CONNECTED)
            _LOG.info("SmartThings integration initialized successfully")

            # ## CHANGE 3 of 3 ##
            # The polling loop is now started here. This is the most reliable
            # place, as it runs only after the client is ready and entities exist.
            await self._start_polling()

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
                    device_name = device_data.get("label") or device_data.get("name", "Unknown")
                    device_type = device_data.get("deviceTypeName", "")
                    capabilities = set()

                    for component in device_data.get("components", []):
                        for cap in component.get("capabilities", []):
                            cap_id = cap.get("id", "")
                            if cap_id:
                                capabilities.add(cap_id)

                    _LOG.info(f"Processing device: {device_name}")
                    _LOG.info(f"  - Device Type: {device_type}")
                    _LOG.info(f"  - Capabilities ({len(capabilities)}): {list(capabilities)}")

                    entity = self.factory.create_entity(device_data, self.config, room_names.get(device_data.get("roomId")))
                    if entity:
                        if self.api.available_entities.add(entity):
                            created_count += 1
                            _LOG.info(f"✅ Successfully added entity: {entity.id} ({entity.name})")
                        else:
                            _LOG.warning(f"❌ Failed to add entity to UC API: {entity.id}")
                    else:
                        _LOG.warning(f"⚠️  No entity created for device: {device_name}")
                        _LOG.warning(f"    This device may not be supported yet or lacks required capabilities")

                except Exception as e:
                    device_name = device_data.get("label", device_data.get("name", "Unknown"))
                    _LOG.error(f"Error creating entity for device {device_name}: {e}", exc_info=True)

            _LOG.info(f"Entity creation summary: {created_count} entities created from {len(devices_raw)} devices")

            if created_count == 0:
                _LOG.error("❌ No entities were created! This indicates:")
                _LOG.error("   - Devices may not be supported yet")
                _LOG.error("   - Device capabilities don't match known patterns")
                _LOG.error("   - Configuration may exclude all device types")
                _LOG.error("   Please run the device analyzer script to get device details")
            else:
                _LOG.info(f"✅ Successfully created {created_count} entities")

        except Exception as e:
            _LOG.error(f"Failed to create entities: {e}", exc_info=True)

    async def _sync_initial_state_immediate(self, entity_ids: List[str]):
        _LOG.info(f"Syncing initial state for {len(entity_ids)} entities...")

        import time
        start_time = time.time()
        synced_count = 0

        batch_size = 6
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
                await asyncio.sleep(0.3)

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

                error_sleep = min(30, 5 * consecutive_errors)
                await asyncio.sleep(error_sleep)

        self.polling_active = False

    async def _poll_entities_intelligently(self):
        """Poll entities with command awareness - skip devices currently executing commands"""
        import time
        now = time.time()
        entities_to_poll = []

        for entity_id in self.subscribed_entities:
            entity = self.api.configured_entities.get(entity_id)
            if not entity:
                continue

            device_id = entity_id[3:]

            if device_id in self.devices_in_command:
                _LOG.debug(f"Skipping polling for {entity.name} - command in progress")
                continue

            last_poll = self.entity_last_poll.get(entity_id, 0)

            required_interval = self._get_entity_polling_interval(entity_id, now)

            if now - last_poll >= required_interval:
                entities_to_poll.append((entity_id, device_id, entity))

        if not entities_to_poll:
            _LOG.debug("No entities need polling at this time")
            return

        _LOG.debug(f"Polling {len(entities_to_poll)} entities")

        batch_size = 5
        changes_detected = 0

        for i in range(0, len(entities_to_poll), batch_size):
            batch = entities_to_poll[i:i + batch_size]
            batch_changes = await self._poll_entity_batch(batch)
            changes_detected += batch_changes

            if i + batch_size < len(entities_to_poll):
                await asyncio.sleep(0.4)

        if changes_detected > 0:
            _LOG.info(f"Detected {changes_detected} state changes in polling")

    async def _poll_entity_batch(self, entity_batch):
        """Poll a batch of entities"""
        import time
        now = time.time()
        changes_detected = 0

        for entity_id, device_id, entity in entity_batch:
            try:
                old_attributes = dict(entity.attributes)

                async with self.client:
                    device_status = await self.client.get_device_status(device_id)

                if device_status:
                    self.factory.update_entity_attributes(entity, device_status)
                    self.entity_last_poll[entity_id] = now

                    if old_attributes != entity.attributes:
                        changes_detected += 1
                        _LOG.info(f"State changed via polling: {entity.name} -> {entity.attributes}")

                    self.api.configured_entities.update_attributes(entity.id, entity.attributes)

                else:
                    _LOG.debug(f"No status data for {entity.name}")

            except Exception as e:
                _LOG.warning(f"Failed to poll {entity_id}: {e}")

        return changes_detected

    def _get_entity_polling_interval(self, entity_id: str, now: float) -> float:
        """Get polling interval for entity based on type and activity"""
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
        """Calculate dynamic polling interval based on rate limits and activity"""
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
        """Track when a device starts/stops command execution"""
        device_id = entity_id[3:] if entity_id.startswith("st_") else entity_id
        self.devices_in_command.add(device_id)

        async def remove_device_from_command():
            await asyncio.sleep(3.0)
            self.devices_in_command.discard(device_id)

        asyncio.create_task(remove_device_from_command())
        _LOG.debug(f"Tracking command for device {device_id}")

    async def _cleanup(self):
        self.polling_active = False

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
    loop = asyncio.get_event_loop()
    api = IntegrationAPI(loop)
    integration = SmartThingsIntegration(api, loop)
    await api.init("driver.json", integration.setup_handler)

    _LOG.info("SmartThings Integration is now running. Press Ctrl+C to stop.")
    try:
        # This is the original, correct way to keep the script alive
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