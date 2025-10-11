"""Test file for SUN2000Device."""

import asyncio
import logging

from huawei_solar import (
    SUN2000Device,
    create_device_instance,
    create_tcp_client,
    get_device_identifiers,
    get_device_infos,
)
from huawei_solar import register_names as rn

loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.DEBUG)


async def test() -> None:
    """Run test."""
    client = create_tcp_client(host="192.168.1.1", port=503)

    print(await get_device_identifiers(client))
    print(await get_device_infos(client))

    device = await create_device_instance(client)

    assert isinstance(device, SUN2000Device)
    await device.login("installer", "00000a")
    print(
        await device.batch_update(
            [
                rn.ACTIVE_POWER_FIXED_VALUE_DERATING,
                rn.ACTIVE_POWER_PERCENTAGE_DERATING,
                rn.STORAGE_CAPACITY_CONTROL_MODE,
                rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING,
                rn.STORAGE_CAPACITY_CONTROL_PERIODS,
            ],
        ),
    )
    print(await device.get(rn.ACTIVE_POWER_FIXED_VALUE_DERATING))
    print(await device.get(rn.ACTIVE_POWER_PERCENTAGE_DERATING))

    print(await device.get(rn.STORAGE_CAPACITY_CONTROL_MODE))
    print(await device.get(rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING))
    print(await device.get(rn.STORAGE_CAPACITY_CONTROL_PERIODS))

    print(await device.get_optimizer_system_information_data())
    print(await device.get_latest_optimizer_history_data())

    await device.stop()


loop.run_until_complete(test())
