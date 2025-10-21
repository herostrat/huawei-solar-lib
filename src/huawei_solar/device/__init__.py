"""Definitions of the devices supported by this library."""

from logging import getLogger

from huawei_solar import register_names as rn
from huawei_solar.modbus_client import AsyncHuaweiSolarClient

from .base import HuaweiSolarDevice, HuaweiSolarDeviceWithLogin
from .emma import EMMADevice
from .scharger import SChargerDevice
from .sdongle import SDongleDevice
from .smartlogger import SmartLoggerDevice
from .sun2000 import SUN2000Device

_LOGGER = getLogger(__name__)


def get_device_class_for_model(model_name: str) -> type[HuaweiSolarDevice]:
    """Get the device class for the given model name."""
    for candidate_bridge_class in [SUN2000Device, EMMADevice, SChargerDevice, SDongleDevice, SmartLoggerDevice]:
        if candidate_bridge_class.supports_device(model_name):
            return candidate_bridge_class

    _LOGGER.warning("Unknown product model '%s'. Defaulting to a SUN2000 device.", model_name)

    # Default to SUN2000Bridge if no specific match is found
    return SUN2000Device


async def create_device_instance(client: AsyncHuaweiSolarClient) -> HuaweiSolarDevice:
    """Detect the connected device and create the appropriate instance."""
    model_name: str = (await client.get(rn.MODEL_NAME)).value
    device_class = get_device_class_for_model(model_name)
    return await device_class.create(
        client,
        model_name=model_name,
        primary_device=None,  # we are creating the primary device!
    )


async def create_sub_device_instance(
    primary_device: HuaweiSolarDevice,
    unit_id: int,
) -> HuaweiSolarDevice:
    """Create a HuaweiSolarDevice instance for extra servers accessible as subdevices via an existing device."""
    if primary_device.client.unit_id == unit_id:
        msg = "The unit_id for the sub-device must be different from the primary device's unit_id."
        raise ValueError(msg)

    sub_client = primary_device.client.for_unit_id(unit_id)
    model_name = (await sub_client.get(rn.MODEL_NAME)).value
    device_class = get_device_class_for_model(model_name)
    return await device_class.create(
        sub_client,
        model_name=model_name,
        primary_device=primary_device,
    )


__all__ = [
    "EMMADevice",
    "HuaweiSolarDevice",
    "HuaweiSolarDeviceWithLogin",
    "SChargerDevice",
    "SDongleDevice",
    "SUN2000Device",
    "SmartLoggerDevice",
    "create_device_instance",
    "create_sub_device_instance",
]
