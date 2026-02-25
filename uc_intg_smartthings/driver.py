"""
SmartThings Integration driver for Unfolded Circle Remote Two/3.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import logging

import ucapi
from ucapi import DeviceStates, api_definitions

from uc_intg_smartthings.config import SmartThingsConfig, SmartThingsConfigManager
from uc_intg_smartthings.device import SmartThingsDevice, DeviceEvents
from uc_intg_smartthings.entities import SmartThingsEntityFactory
from uc_intg_smartthings.setup_flow import SmartThingsSetupFlow

_LOG = logging.getLogger(__name__)

api = ucapi.IntegrationAPI(loop=asyncio.get_event_loop())

config_manager: SmartThingsConfigManager | None = None
devices: dict[str, SmartThingsDevice] = {}
entity_factories: dict[str, SmartThingsEntityFactory] = {}
entities_ready: bool = False
initialization_lock = asyncio.Lock()
setup_flow: SmartThingsSetupFlow | None = None


async def on_token_update(config: SmartThingsConfig) -> None:
    """Handle token update callback from device."""
    if config_manager:
        config_manager.update(config)
        _LOG.debug("Updated tokens in configuration")


async def setup_device(config: SmartThingsConfig) -> bool:
    """Set up a SmartThings device from configuration."""
    global entities_ready

    identifier = config.identifier
    _LOG.info("Setting up SmartThings device: %s", config.name)

    device = SmartThingsDevice(config, on_token_update=on_token_update)

    if not await device.connect():
        _LOG.error("Failed to connect to SmartThings for: %s", config.name)
        return False

    factory = SmartThingsEntityFactory(device)
    entities = factory.create_entities(
        include_lights=config.include_lights,
        include_switches=config.include_switches,
        include_sensors=config.include_sensors,
        include_climate=config.include_climate,
        include_covers=config.include_covers,
        include_media_players=config.include_media_players,
        include_buttons=config.include_buttons,
    )

    for entity in entities:
        api.available_entities.add(entity)

    device.events.on(DeviceEvents.UPDATE, lambda did, status: on_device_update(factory, did, status))

    devices[identifier] = device
    entity_factories[identifier] = factory
    entities_ready = True

    _LOG.info(
        "SmartThings device %s setup complete with %d entities",
        config.name,
        len(entities),
    )
    return True


def on_device_update(factory: SmartThingsEntityFactory, device_id: str, status: dict) -> None:
    """Handle device status update events."""
    updates = factory.update_entity_states(device_id, status)

    for entity_id, attrs in updates.items():
        if api.configured_entities.contains(entity_id):
            api.configured_entities.update_attributes(entity_id, attrs)
            _LOG.debug("Updated entity %s: %s", entity_id, attrs)


async def on_setup_complete(config: SmartThingsConfig) -> None:
    """Handle setup completion."""
    if config_manager:
        config_manager.add(config)

    await setup_device(config)


async def driver_setup_handler(request: ucapi.SetupDriver) -> ucapi.SetupAction:
    """Handle driver setup requests."""
    global setup_flow

    if isinstance(request, ucapi.DriverSetupRequest):
        setup_flow = SmartThingsSetupFlow(on_setup_complete=on_setup_complete)

    if setup_flow is None:
        setup_flow = SmartThingsSetupFlow(on_setup_complete=on_setup_complete)

    return await setup_flow.handle_setup_request(request)


@api.listens_to(api_definitions.Events.CONNECT)
async def on_connect() -> None:
    """Handle Remote connection."""
    global entities_ready

    _LOG.info("Remote connected")

    if config_manager:
        config_manager.load()

    if entities_ready and devices:
        await api.set_device_state(DeviceStates.CONNECTED)
    else:
        await api.set_device_state(DeviceStates.DISCONNECTED)


@api.listens_to(api_definitions.Events.DISCONNECT)
async def on_disconnect() -> None:
    """Handle Remote disconnection."""
    _LOG.info("Remote disconnected. Keeping devices running for reconnection.")


@api.listens_to(api_definitions.Events.SUBSCRIBE_ENTITIES)
async def on_subscribe_entities(entity_ids: list[str]) -> None:
    """Handle entity subscription requests."""
    global entities_ready

    _LOG.info("Entities subscribed: %s", entity_ids)

    if not entities_ready:
        _LOG.warning("Entities not ready yet, subscription may fail")
        return

    for entity_id in entity_ids:
        for factory in entity_factories.values():
            entity = factory.get_entity(entity_id)
            if entity:
                _LOG.debug("Subscribed to entity: %s", entity_id)
                break


@api.listens_to(api_definitions.Events.UNSUBSCRIBE_ENTITIES)
async def on_unsubscribe_entities(entity_ids: list[str]) -> None:
    """Handle entity unsubscription requests."""
    _LOG.info("Entities unsubscribed: %s", entity_ids)


def add_device_from_config(device_config: SmartThingsConfig) -> None:
    """Add device from configuration (called during startup)."""
    asyncio.create_task(setup_device(device_config))


async def cleanup() -> None:
    """Clean up resources on shutdown."""
    _LOG.info("Shutting down SmartThings driver...")
    for device in devices.values():
        await device.disconnect()


async def main() -> None:
    """Main entry point for the SmartThings integration."""
    global config_manager, entities_ready

    _LOG.info("Starting SmartThings integration v3.0.2")

    config_manager = SmartThingsConfigManager(
        api.config_dir_path,
        on_add=None,
        on_remove=None,
    )

    await api.init("driver.json", driver_setup_handler)

    existing_configs = config_manager.all()
    if existing_configs:
        _LOG.info("Found %d existing configuration(s)", len(existing_configs))

        for config in existing_configs:
            success = await setup_device(config)
            if success:
                _LOG.info("Pre-configured device: %s", config.name)
            else:
                _LOG.warning("Failed to pre-configure device: %s", config.name)

        if devices:
            entities_ready = True
            _LOG.info("SmartThings integration ready with %d device(s)", len(devices))
    else:
        entities_ready = True
        _LOG.info("No existing configurations, waiting for setup")

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await cleanup()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(name)-40s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    asyncio.run(main())
