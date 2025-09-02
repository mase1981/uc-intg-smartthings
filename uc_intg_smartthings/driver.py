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

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
API = IntegrationAPI(loop)  # Global, always available

# Global state variables
_client: Optional[SmartThingsClient] = None
_factory: Optional[SmartThingsEntityFactory] = None
_config_manager: Optional[ConfigManager] = None
_config: Dict[str, Any] = {}
_setup_flow: Optional[SmartThingsSetupFlow] = None
_status_update_task: Optional[asyncio.Task] = None

_entity_last_poll = {}
_subscribed_entities = set()
_polling_active = False
_devices_in_command = set()
_placeholder_entities_created = False

def track_device_command(entity_id: str):
    """Track when a device starts/stops command execution."""
    device_id = entity_id[3:] if entity_id.startswith("st_") else entity_id
    _devices_in_command.add(device_id)
    
    # Schedule removal after command timeout
    async def remove_device_from_command():
        await asyncio.sleep(3.0)
        _devices_in_command.discard(device_id)
    
    asyncio.create_task(remove_device_from_command())
    _LOG.debug(f"Tracking command for device {device_id}")

@API.listens_to(Events.CONNECT)
async def on_connect() -> None:
    """Handle connection events - recreate entities if missing."""
    global _client, _factory, _config_manager, _config, _placeholder_entities_created
    
    _LOG.info("Connected to UC Remote - checking entities")
    
    # Force reload configuration from disk
    if not _config_manager:
        _config_manager = ConfigManager(API.config_dir_path)
    
    _config_manager = ConfigManager(API.config_dir_path)  # Force fresh instance
    
    if not _config_manager.is_configured():
        _LOG.info("No configuration found - setting disconnected state")
        await API.set_device_state(DeviceStates.DISCONNECTED)
        return
    
    # Reload config from disk
    _config = _config_manager.load_config()
    
    # Check if entities exist, recreate if missing
    expected_entity_count = len(_subscribed_entities) if _subscribed_entities else 0
    current_entity_count = len(API.available_entities.get_all())
    
    _LOG.info(f"Entity check: expected={expected_entity_count}, current={current_entity_count}")
    
    if expected_entity_count == 0 or current_entity_count == 0:
        _LOG.info("Entities missing or never created - initializing integration")
        await _initialize_integration()
    else:
        _LOG.info("Entities exist - testing connection")
        await _test_and_connect()

@API.listens_to(Events.DISCONNECT)
async def on_disconnect() -> None:
    """Handle disconnect events."""
    await _cleanup()

@API.listens_to(Events.SUBSCRIBE_ENTITIES)
async def on_subscribe_entities(entity_ids: List[str]) -> None:
    """Handle entity subscription requests."""
    global _subscribed_entities
    
    _LOG.info(f"Remote requested subscription to {len(entity_ids)} entities")
    
    # Filter for SmartThings entities and store subscriptions
    st_entities = {eid for eid in entity_ids if eid.startswith("st_")}
    _subscribed_entities = st_entities
    
    if st_entities and _client and _factory:
        _LOG.info(f"Starting subscription for {len(st_entities)} entities")
        await _sync_initial_state_immediate(list(st_entities))
        await _start_monitoring_loop()
    else:
        _LOG.info("Subscription request stored - will process when initialization complete")

async def _initialize_integration():
    """Initialize integration from scratch."""
    global _client, _factory, _placeholder_entities_created
    
    try:
        await API.set_device_state(DeviceStates.CONNECTING)
        
        access_token = _config.get("access_token")
        if not access_token:
            _LOG.error("No access token found in configuration")
            await API.set_device_state(DeviceStates.ERROR)
            return
        
        # Create client and factory
        _client = SmartThingsClient(access_token)
        _factory = SmartThingsEntityFactory(_client, API)
        _factory.command_callback = track_device_command
        
        # Create entities
        await _create_entities()
        
        # Mark as connected
        await API.set_device_state(DeviceStates.CONNECTED)
        _LOG.info("SmartThings integration initialized successfully")
        
        # Start monitoring if we have subscriptions
        if _subscribed_entities:
            await _start_monitoring_loop()
            
    except Exception as e:
        _LOG.error(f"Failed to initialize integration: {e}", exc_info=True)
        await API.set_device_state(DeviceStates.ERROR)

async def _test_and_connect():
    """Test existing connection and recreate if needed."""
    global _client, _factory
    
    try:
        await API.set_device_state(DeviceStates.CONNECTING)
        
        access_token = _config.get("access_token")
        if not access_token:
            await _initialize_integration()
            return
        
        # Recreate client if needed
        if not _client:
            _client = SmartThingsClient(access_token)
        
        if not _factory:
            _factory = SmartThingsEntityFactory(_client, API)
            _factory.command_callback = track_device_command
        
        # Test connection
        location_id = _config.get("location_id")
        async with _client:
            locations = await _client.get_locations()
            if not any(loc["locationId"] == location_id for loc in locations):
                raise Exception("Location no longer accessible")
        
        await API.set_device_state(DeviceStates.CONNECTED)
        _LOG.info("SmartThings connection verified")
        
        # Start monitoring if we have subscriptions
        if _subscribed_entities:
            await _start_monitoring_loop()
            
    except Exception as e:
        _LOG.error(f"Connection test failed, reinitializing: {e}")
        await _initialize_integration()

async def _create_entities():
    """Create all entities from configuration."""
    global _placeholder_entities_created
    
    if not _client or not _factory:
        _LOG.error("Client or factory not available for entity creation")
        return
    
    try:
        location_id = _config.get("location_id")
        if not location_id:
            _LOG.error("No location_id found in configuration")
            return
        
        async with _client:
            devices_raw = await _client.get_devices(location_id)
            rooms = await _client.get_rooms(location_id)
        
        room_names = {room["roomId"]: room["name"] for room in rooms}
        
        # Clear existing entities
        API.available_entities.clear()
        created_count = 0
        
        _LOG.info(f"Processing {len(devices_raw)} devices from SmartThings...")
        
        for device_data in devices_raw:
            try:
                device_name = device_data.get("label") or device_data.get("name", "Unknown")
                
                entity = _factory.create_entity(device_data, _config, room_names.get(device_data.get("roomId")))
                if entity:
                    if API.available_entities.add(entity):
                        created_count += 1
                        _LOG.info(f"Successfully added entity: {entity.id} ({entity.name})")
                    else:
                        _LOG.warning(f"Failed to add entity to UC API: {entity.id}")
                else:
                    _LOG.warning(f"No entity created for device: {device_name}")
                    
            except Exception as e:
                device_name = device_data.get("label", device_data.get("name", "Unknown"))
                _LOG.error(f"Error creating entity for device {device_name}: {e}", exc_info=True)
        
        _LOG.info(f"Entity creation summary: {created_count} entities created from {len(devices_raw)} devices")
        _placeholder_entities_created = True
        
    except Exception as e:
        _LOG.error(f"Failed to create entities: {e}", exc_info=True)

async def _start_monitoring_loop():
    """Start monitoring loop."""
    global _status_update_task, _polling_active
    
    if _status_update_task and not _status_update_task.done():
        _LOG.debug("Monitoring already running")
        return
    
    if not _client or not _factory:
        _LOG.warning("Cannot start monitoring - client or factory not available")
        return
    
    if not _subscribed_entities:
        _LOG.info("No subscribed entities found - monitoring will start when entities are subscribed")
        return
    
    _LOG.info(f"Starting monitoring for {len(_subscribed_entities)} subscribed entities")
    
    # Sync initial state immediately
    await _sync_initial_state_immediate(list(_subscribed_entities))
    
    # Start background polling
    _polling_active = True
    _status_update_task = loop.create_task(_polling_loop())
    _LOG.info("Background monitoring started")

async def _sync_initial_state_immediate(entity_ids: List[str]):
    """Sync initial state for specified entities."""
    _LOG.info(f"Syncing initial state for {len(entity_ids)} entities...")
    
    import time
    start_time = time.time()
    synced_count = 0
    
    batch_size = 6
    for i in range(0, len(entity_ids), batch_size):
        batch = entity_ids[i:i + batch_size]
        
        tasks = []
        for entity_id in batch:
            entity = API.configured_entities.get(entity_id)
            if entity:
                device_id = entity_id[3:]
                tasks.append(_sync_single_entity(entity, device_id))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    synced_count += 1
        
        if i + batch_size < len(entity_ids):
            await asyncio.sleep(0.3)
    
    sync_time = time.time() - start_time
    _LOG.info(f"Initial state synced for {synced_count}/{len(entity_ids)} entities in {sync_time:.1f}s")

async def _sync_single_entity(entity, device_id: str) -> bool:
    """Sync a single entity's state."""
    try:
        async with _client:
            device_status = await _client.get_device_status(device_id)
        
        if device_status:
            old_attributes = dict(entity.attributes)
            _factory.update_entity_attributes(entity, device_status)
            
            API.configured_entities.update_attributes(entity.id, entity.attributes)
            
            if old_attributes != entity.attributes:
                _LOG.info(f"Initial sync: {entity.name} -> {entity.attributes}")
            else:
                _LOG.debug(f"Initial sync: {entity.name} (no change)")
            
            return True
    
    except Exception as e:
        _LOG.error(f"Failed to sync {entity.id}: {e}")
        return False

async def _polling_loop():
    """Background polling loop for entity state updates."""
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while _polling_active:
        try:
            if not _subscribed_entities:
                await asyncio.sleep(10)
                continue
            
            await _poll_entities_intelligently()
            
            consecutive_errors = 0
            
            # Smart sleep based on activity
            sleep_time = _calculate_polling_interval()
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
    
    global _polling_active
    _polling_active = False

async def _poll_entities_intelligently():
    """Poll entities with command awareness."""
    import time
    now = time.time()
    entities_to_poll = []
    
    for entity_id in _subscribed_entities:
        entity = API.configured_entities.get(entity_id)
        if not entity:
            continue
        
        device_id = entity_id[3:]
        
        # Skip devices currently executing commands
        if device_id in _devices_in_command:
            _LOG.debug(f"Skipping polling for {entity.name} - command in progress")
            continue
        
        last_poll = _entity_last_poll.get(entity_id, 0)
        
        # Determine polling interval based on device type and last activity
        required_interval = _get_entity_polling_interval(entity_id, now)
        
        if now - last_poll >= required_interval:
            entities_to_poll.append((entity_id, device_id, entity))
    
    if not entities_to_poll:
        _LOG.debug("No entities need polling at this time")
        return
    
    _LOG.debug(f"Polling {len(entities_to_poll)} entities")
    
    # Poll in batches to avoid overwhelming the API
    batch_size = 5
    changes_detected = 0
    
    for i in range(0, len(entities_to_poll), batch_size):
        batch = entities_to_poll[i:i + batch_size]
        batch_changes = await _poll_entity_batch(batch)
        changes_detected += batch_changes
        
        if i + batch_size < len(entities_to_poll):
            await asyncio.sleep(0.4)
    
    if changes_detected > 0:
        _LOG.info(f"Detected {changes_detected} state changes in polling")

async def _poll_entity_batch(entity_batch):
    """Poll a batch of entities."""
    import time
    now = time.time()
    changes_detected = 0
    
    for entity_id, device_id, entity in entity_batch:
        try:
            old_attributes = dict(entity.attributes)
            
            async with _client:
                device_status = await _client.get_device_status(device_id)
            
            if device_status:
                _factory.update_entity_attributes(entity, device_status)
                _entity_last_poll[entity_id] = now
                
                if old_attributes != entity.attributes:
                    changes_detected += 1
                    _LOG.info(f"State changed via polling: {entity.name} -> {entity.attributes}")
                
                API.configured_entities.update_attributes(entity.id, entity.attributes)
            else:
                _LOG.debug(f"No status data for {entity.name}")
        
        except Exception as e:
            _LOG.warning(f"Failed to poll {entity_id}: {e}")
    
    return changes_detected

def _get_entity_polling_interval(entity_id: str, now: float) -> float:
    """Get polling interval for entity based on type and activity."""
    base_interval = _config.get("polling_interval", 12)
    
    # Default intervals based on entity type
    entity = API.configured_entities.get(entity_id)
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

def _calculate_polling_interval() -> float:
    """Calculate dynamic polling interval based on rate limits and activity."""
    import time
    
    # Much slower polling to avoid rate limits
    if _devices_in_command:
        return 15.0
    
    # Check if we've hit rate limits recently
    if (hasattr(_client, '_last_rate_limit') and 
        time.time() - _client._last_rate_limit < 60):
        return 25.0
    
    # Normal slow polling to stay under rate limits
    base_config = _config.get("polling_interval", 12)
    entity_count = len(_subscribed_entities)
    
    # Much more conservative polling
    if entity_count <= 3:
        return max(base_config * 2, 15)
    elif entity_count <= 10:
        return max(base_config * 3, 20)
    else:
        return max(base_config * 4, 30)

async def _cleanup():
    """Clean up resources."""
    global _polling_active, _status_update_task, _client
    global _entity_last_poll, _subscribed_entities, _devices_in_command, _placeholder_entities_created
    
    _polling_active = False
    
    if _status_update_task and not _status_update_task.done():
        _status_update_task.cancel()
        try:
            await _status_update_task
        except asyncio.CancelledError:
            pass
    
    if _client:
        await _client.close()
    
    _entity_last_poll.clear()
    _subscribed_entities.clear()
    _devices_in_command.clear()
    _placeholder_entities_created = False
    
    _LOG.info("Integration cleanup completed")

async def setup_handler(msg: SetupDriver) -> Any:
    """Handle setup flow and initialize integration after completion."""
    global _setup_flow, _config_manager
    
    if not _setup_flow:
        if not _config_manager:
            _config_manager = ConfigManager(API.config_dir_path)
        _setup_flow = SmartThingsSetupFlow(API, _config_manager)
    
    setup_result = await _setup_flow.handle_setup_request(msg)
    
    if isinstance(setup_result, uc.SetupComplete):
        _LOG.info("Setup complete - initializing integration")
        
        # Force reload configuration
        _config_manager = ConfigManager(API.config_dir_path)
        global _config
        _config = _config_manager.load_config()
        
        # Initialize integration
        await _initialize_integration()
    
    return setup_result

async def main():
    """Main function - follows proven working pattern."""
    global _config_manager, _config
    
    _config_manager = ConfigManager(API.config_dir_path)
    
    await API.init("driver.json", setup_handler)
    
    # Create entities immediately if configured
    if _config_manager.is_configured():
        _LOG.info("Configuration found - creating entities immediately")
        try:
            _config = _config_manager.load_config()
            if _config.get("access_token") and _config.get("location_id"):
                await _initialize_integration()
                _LOG.info("Entities created successfully")
        except Exception as e:
            _LOG.error(f"Failed to create initial entities: {e}")
    
    _LOG.info("SmartThings Integration is now running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        _LOG.info("Integration shutdown requested")
    finally:
        await _cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _LOG.info("Integration stopped by user")