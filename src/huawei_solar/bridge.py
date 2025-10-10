# """Higher-level access to Huawei Solar inverters."""

# from __future__ import annotations

# import asyncio
# import logging
# from abc import ABC, abstractmethod
# from contextlib import suppress
# from datetime import UTC, datetime, timedelta
# from typing import Any, Self

# from . import register_names as rn
# from . import register_values as rv
# from .const import (
#     MAX_BATCHED_REGISTERS_COUNT,
#     MAX_BATCHED_REGISTERS_GAP,
#     MAX_NUMBER_OF_PV_STRINGS,
# )
# from .exceptions import (
#     HuaweiSolarException,
#     InvalidCredentials,
#     ReadException,
# )
# from .files import (
#     OptimizerRealTimeData,
#     OptimizerRealTimeDataFile,
#     OptimizerSystemInformation,
#     OptimizerSystemInformationDataFile,
# )
# from .modbus_client import (
#     DEFAULT_BAUDRATE,
#     DEFAULT_SLAVE_ID,
#     DEFAULT_TCP_PORT,
#     AsyncHuaweiSolarClient,
#     Result,
# )
# from .modbus_pdu import PermissionDeniedError
# from .register_definitions import TimestampRegister
# from .register_values import StorageProductModel
# from .registers import METER_REGISTERS, REGISTERS

# _LOGGER = logging.getLogger(__name__)

# HEARTBEAT_INTERVAL = 15


# BRIDGE_CLASSES: list[type[HuaweiSolarBridge]] = [HuaweiSUN2000Bridge, HuaweiEMMABridge, HuaweiChargerBridge]


# async def create_tcp_bridge(
#     host: str,
#     port: int = DEFAULT_TCP_PORT,
#     slave_id: int = DEFAULT_SLAVE_ID,
# ) -> HuaweiSolarBridge:
#     """Connect to the device via Modbus TCP and create the appropriate bridge."""
#     return await _create(await AsyncHuaweiSolarClient.create(host, port, slave_id), slave_id)


# async def create_rtu_bridge(
#     port: str,
#     baudrate: int = DEFAULT_BAUDRATE,
#     slave_id: int = DEFAULT_SLAVE_ID,
# ) -> HuaweiSolarBridge:
#     """Connect to the device via Modbus RTU and create the appropriate bridge."""
#     return await _create(await AsyncHuaweiSolarClient.create_rtu(port, baudrate=baudrate, slave_id=slave_id), slave_id)


# async def create_sub_bridge(
#     primary_bridge: HuaweiSolarBridge,
#     slave_id: int,
# ) -> HuaweiSolarBridge:
#     """Create a HuaweiSolarBridge instance for extra servers accessible as subdevices via an existing Bridge."""
#     assert primary_bridge.slave_id != slave_id
#     return await _create(
#         primary_bridge.client.for_slave_id(slave_id),
#         slave_id,
#         primary_bridge.update_lock,
#         connected_via_emma=isinstance(primary_bridge, HuaweiEMMABridge),
#     )


# async def _create(
#     client: AsyncHuaweiSolarClient,
#     slave_id: int,
#     update_lock: asyncio.Lock | None = None,
#     *,
#     connected_via_emma: bool = False,
# ) -> HuaweiSolarBridge:
#     model_name_result = await client.get(rn.MODEL_NAME)
#     model_name = model_name_result.value

#     for candidate_bridge_class in BRIDGE_CLASSES:
#         if candidate_bridge_class.supports_device(model_name):
#             return await candidate_bridge_class.create(
#                 client,
#                 slave_id,
#                 model_name,
#                 update_lock,
#                 connected_via_emma=connected_via_emma,
#             )

#     _LOGGER.warning("Unknown product model '%s'. Defaulting to a SUN2000 device.", model_name)
#     return await HuaweiSUN2000Bridge.create(
#         client,
#         slave_id,
#         model_name,
#         update_lock,
#     )
