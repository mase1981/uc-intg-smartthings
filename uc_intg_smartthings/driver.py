#!/usr/bin/env python3
"""
SmartThings integration driver for Unfolded Circle Remote.

:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os
import signal
from typing import Any, Dict, Optional, List

import ucapi

from uc_intg_smartthings.client import SmartThingsClient
from uc_intg_smartthings.config import ConfigManager
from uc_intg_smartthings.entities import SmartThingsEntityFactory
from uc_intg_smartthings.setup_flow import SmartThingsSetupFlow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)8s | %(name)s | %(message)s"
)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

_LOG = logging.getLogger(__name__)

# Global State - Following Bond integration pattern
loop = asyncio.get_event_loop()
api: Optional[ucapi.IntegrationAPI] = None
client: Optional[SmartThingsClient] = None
config_manager: Optional[ConfigManager] = None
factory: Optional[SmartThingsEntityFactory] = None
setup_complete_callback_set = False

async def on_setup_complete():
    """Callback executed when driver setup is complete."""
    global factory, client, api, config_manager
    _LOG.info("Setup complete. Creating entities...")

    if not api or not client:
        _LOG.error("Cannot create entities: API or client not initialized.")
        await api.set_device_state(ucapi.DeviceStates.ERROR)
        return

    try:
        if not client or not config_manager:
            _LOG.error("SmartThings client or config not available after setup")
            await api.set_device_state(ucapi.DeviceStates.ERROR)
            return

        config = config_manager.load_config()
        if not config.get("access_token") or not config.get("location_id"):
            _LOG.error("SmartThings not configured after setup")
            await api.set_device_state(ucapi.DeviceStates.ERROR)
            return

        # Test connection
        async with client:
            if not await client.health_check():
                _LOG.error("SmartThings connection test failed after setup")
                await api.set_device_state(ucapi.DeviceStates.ERROR)
                return

        await _create_entities()
        
        _LOG.info("SmartThings entities created successfully. Setting state to CONNECTED.")
        await api.set_device_state(ucapi.DeviceStates.CONNECTED)
        
    except Exception as e:
        _LOG.error(f"Error creating entities: {e}", exc_info=True)
        await api.set_device_state(ucapi.DeviceStates.ERROR)

async def on_r2_connect():
    """Handle Remote connection - Following Bond integration pattern."""
    global api, client, config_manager, factory
    _LOG.info("Remote connected.")
    
    if api and config_manager and config_manager.is_configured():
        _LOG.info("SmartThings integration is already configured")
        
        # Reload config from disk (critical for reboot survival)
        config = config_manager.load_config()
        
        if not client:
            client = SmartThingsClient(config.get("access_token"))
        
        # Test connection
        async with client:
            if await client.health_check():
                _LOG.info("SmartThings connection verified. Setting state to CONNECTED.")
                
                # Check if entities exist, recreate if missing (critical for reboot survival)
                if not api.available_entities.get_all():
                    _LOG.info("No entities found, recreating...")
                    await _create_entities()
                    
                await api.set_device_state(ucapi.DeviceStates.CONNECTED)
            else:
                _LOG.warning("SmartThings connection failed. Setting state to ERROR.")
                await api.set_device_state(ucapi.DeviceStates.ERROR)
    else:
        _LOG.info("Integration not configured yet.")

async def on_disconnect():
    """Handle Remote disconnection."""
    _LOG.info("Remote disconnected.")

async def on_subscribe_entities(entity_ids: List[str]):
    """Handle entity subscription from Remote."""
    _LOG.info(f"Remote subscribed to entities: {entity_ids}")
    
    if client and factory and config_manager and config_manager.is_configured():
        _LOG.info("Ensuring entities are properly initialized...")
        
        # Verify connection
        async with client:
            connection_ok = await client.health_check()
            _LOG.info(f"SmartThings connection test: {'OK' if connection_ok else 'FAILED'}")
            
            if not connection_ok:
                _LOG.error("SmartThings connection failed during entity subscription")
                await api.set_device_state(ucapi.DeviceStates.ERROR)

async def on_unsubscribe_entities(entity_ids: List[str]):
    """Handle entity unsubscription from Remote."""
    _LOG.info(f"Remote unsubscribed from entities: {entity_ids}")

async def _create_entities():
    """Create SmartThings entities."""
    global factory, client, api, config_manager
    
    if not client or not factory or not api or not config_manager:
        _LOG.error("Cannot create entities: missing dependencies")
        return
        
    try:
        config = config_manager.load_config()
        location_id = config.get("location_id")
        
        if not location_id:
            _LOG.error("No location_id found in configuration")
            return
            
        async with client:
            devices_raw = await client.get_devices(location_id)
            rooms = await client.get_rooms(location_id)
        
        room_names = {room["roomId"]: room["name"] for room in rooms}
        
        # Clear existing entities
        api.available_entities.clear()
        created_count = 0
        
        _LOG.info(f"Processing {len(devices_raw)} devices from SmartThings...")
        
        for device_data in devices_raw:
            try:
                entity = factory.create_entity(device_data, config, room_names.get(device_data.get("roomId")))
                if entity:
                    if api.available_entities.add(entity):
                        created_count += 1
                        _LOG.debug(f"Added entity: {entity.id} ({entity.name})")
                    else:
                        _LOG.warning(f"Failed to add entity to UC API: {entity.id}")
                        
            except Exception as e:
                device_name = device_data.get("label", "Unknown")
                _LOG.error(f"Error creating entity for device {device_name}: {e}", exc_info=True)

        _LOG.info(f"Entity creation complete: {created_count} entities created from {len(devices_raw)} devices")
        
        if created_count == 0:
            _LOG.error("No entities were created!")
        else:
            _LOG.info(f"Successfully created {created_count} entities")

    except Exception as e:
        _LOG.error(f"Failed to create entities: {e}", exc_info=True)

async def init_integration():
    """Initialize the integration objects and API - Following Bond integration pattern."""
    global api, client, config_manager, factory
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    driver_json_path = os.path.join(project_root, "driver.json")
    
    if not os.path.exists(driver_json_path):
        driver_json_path = "driver.json"
        if not os.path.exists(driver_json_path):
            _LOG.error(f"Cannot find driver.json at {driver_json_path}")
            raise FileNotFoundError("driver.json not found")
    
    _LOG.info(f"Using driver.json from: {driver_json_path}")

    api = ucapi.IntegrationAPI(loop)

    config_path = os.path.join(api.config_dir_path, "smartthings_config.json")
    _LOG.info(f"Using config file: {config_path}")
    config_manager = ConfigManager(api.config_dir_path)
    
    # Initialize client if config exists
    config = config_manager.load_config()
    if config.get("access_token"):
        client = SmartThingsClient(config.get("access_token"))
        factory = SmartThingsEntityFactory(client, api)

    setup_handler = SmartThingsSetupFlow(api, config_manager)
    
    await api.init(driver_json_path, setup_handler.handle_setup_request)
    
    # Use function references, not decorators (Bond pattern)
    api.add_listener(ucapi.Events.CONNECT, on_r2_connect)
    api.add_listener(ucapi.Events.DISCONNECT, on_disconnect)
    api.add_listener(ucapi.Events.SUBSCRIBE_ENTITIES, on_subscribe_entities)
    api.add_listener(ucapi.Events.UNSUBSCRIBE_ENTITIES, on_unsubscribe_entities)
    
    _LOG.info("Integration API initialized successfully")
    
async def main():
    """Main entry point - Following Bond integration pattern."""
    global setup_complete_callback_set
    _LOG.info("Starting SmartThings Integration Driver")
    
    try:
        await init_integration()
        
        # Set the setup complete callback
        if not setup_complete_callback_set:
            if hasattr(api, '_setup_flow'):
                api._setup_flow._setup_complete_callback = on_setup_complete
            setup_complete_callback_set = True
        
        if config_manager and config_manager.is_configured():
            _LOG.info("Integration is already configured")
            
            config = config_manager.load_config()
            if not client:
                client = SmartThingsClient(config.get("access_token"))
                factory = SmartThingsEntityFactory(client, api)
            
            async with client:
                if await client.health_check():
                    _LOG.info("SmartThings connection successful")
                    await _create_entities()
                    await api.set_device_state(ucapi.DeviceStates.CONNECTED)
                else:
                    _LOG.error("Cannot connect to SmartThings")
                    await api.set_device_state(ucapi.DeviceStates.ERROR)
        else:
            _LOG.warning("Integration is not configured. Waiting for setup...")
            await api.set_device_state(ucapi.DeviceStates.ERROR)

        _LOG.info("Integration is running. Press Ctrl+C to stop.")
        
    except Exception as e:
        _LOG.error(f"Failed to start integration: {e}", exc_info=True)
        if api:
            await api.set_device_state(ucapi.DeviceStates.ERROR)
        raise
    
def shutdown_handler(signum, frame):
    """Handle termination signals for graceful shutdown."""
    _LOG.warning(f"Received signal {signum}. Shutting down...")
    
    async def cleanup():
        try:
            if client:
                _LOG.info("Closing SmartThings client...")
                await client.close()
            
            _LOG.info("Cancelling remaining tasks...")
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            [task.cancel() for task in tasks]
            
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            _LOG.error(f"Error during cleanup: {e}")
        finally:
            _LOG.info("Stopping event loop...")
            loop.stop()

    loop.create_task(cleanup())

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        loop.run_until_complete(main())
        loop.run_forever()
    except (KeyboardInterrupt, asyncio.CancelledError):
        _LOG.info("Driver stopped.")
    except Exception as e:
        _LOG.error(f"Driver failed: {e}", exc_info=True)
    finally:
        if loop and not loop.is_closed():
            _LOG.info("Closing event loop...")
            loop.close()