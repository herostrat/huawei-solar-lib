"""Low-level Modbus logic."""

import logging
import struct
from dataclasses import dataclass
from typing import Any, Literal, Self, TypeVar, Unpack

import tenacity
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, stop_after_delay, wait_exponential
from tmodbus import AsyncModbusClient, create_async_rtu_client, create_async_tcp_client
from tmodbus.exceptions import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusResponseError,
    ServerDeviceBusyError,
    ServerDeviceFailureError,
    TModbusError,
)
from tmodbus.transport.async_rtu import PySerialOptions
from tmodbus.transport.async_smart import AsyncSmartTransport
from tmodbus.utils.crc import calculate_crc16

from .const import DEVICE_INFOS_START_OBJECT_ID, MAX_BATCHED_REGISTERS_COUNT
from .exceptions import (
    ConnectionException,
    ConnectionInterruptedException,
    ReadException,
    WriteException,
)
from .modbus import (
    CompleteUploadPDU,
    LoginPDU,
    LoginRequestChallengePDU,
    PermissionDeniedError,
    StartFileUploadPDU,
    UploadFileFramePDU,
)
from .register_definitions.base import RegisterDefinition, Result
from .registers import REGISTERS

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")
RT = TypeVar("RT")


DEFAULT_TCP_PORT = 502
DEFAULT_BAUDRATE = 9600

DEFAULT_SLAVE_ID = 0
DEFAULT_TIMEOUT = 10  # especially the SDongle can react quite slowly
DEFAULT_WAIT = 1
DEFAULT_COOLDOWN_TIME = 0.05
WAIT_FOR_CONNECTION_TIMEOUT = 5

HEARTBEAT_REGISTER = 49999

FILE_UPLOAD_MAX_RETRIES = 6
FILE_UPLOAD_RETRY_TIMEOUT = 10


@dataclass(frozen=True)
class DeviceInfo:
    """Device information."""

    model: str | None
    software_version: str | None
    interface_protocol_version: str | None
    esn: str | None
    device_id: int | None
    feature_version: str | None
    unknown_field: str | None
    product_type: str | None


@dataclass(frozen=True)
class DeviceIdentifier:
    """Device identifier information."""

    vendor: str
    product_code: str
    main_revision_version: str
    other_data: dict[int, bytes]


RECONNECT_RETRY_STRATEGY = AsyncRetrying(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    # Stop trying to reconnect if the connection has not been re-established within 1 minute
    stop=stop_after_delay(60),
    after=lambda retry_call_state: LOGGER.debug(
        "Backing off before reconnect for %0.1fs after %d tries",
        retry_call_state.upcoming_sleep,
        retry_call_state.attempt_number,
    ),
)


def log_invalid_response(retry_state: "tenacity.RetryCallState") -> None:
    """Log an invalid response."""
    if retry_state.outcome:
        if e := retry_state.outcome.exception():
            LOGGER.debug(
                "Backing off for %0.1fs after exception response %s",
                retry_state.upcoming_sleep,
                e,
            )
        else:
            LOGGER.debug(
                "Backing off for %0.1fs after invalid response %s",
                retry_state.upcoming_sleep,
                retry_state.outcome.result(),
            )
    else:
        LOGGER.debug(
            "Backing off for %0.1fs before retrying request",
            retry_state.upcoming_sleep,
        )


RESPONSE_RETRY_STRATEGY = AsyncRetrying(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    # Retry up to 3 times on invalid response
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(TimeoutError),
    reraise=True,
    after=log_invalid_response,
)


class AsyncHuaweiSolar:
    """Async interface to the Huawei solar inverter."""

    def __init__(
        self,
        client: AsyncModbusClient,
    ) -> None:
        """DO NOT USE THIS CONSTRUCTOR DIRECTLY. Use AsyncHuaweiSolar.create() instead."""
        self._client = client

    @classmethod
    async def create(
        cls,
        host: str,
        port: int = DEFAULT_TCP_PORT,
        slave_id: int = DEFAULT_SLAVE_ID,
        timeout: int = DEFAULT_TIMEOUT,  # noqa: ASYNC109
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
    ) -> Self:
        """Create an AsyncHuaweiSolar instance."""
        client = create_async_tcp_client(
            host,
            port,
            unit_id=slave_id,
            timeout=timeout,
            wait_between_requests=cooldown_time,
            wait_after_connect=1.0,
            auto_reconnect=RECONNECT_RETRY_STRATEGY,
            response_retry_strategy=RESPONSE_RETRY_STRATEGY,
            retry_on_device_busy=True,
            retry_on_device_failure=True,
        )

        try:
            await client.connect()
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            LOGGER.exception("Aborting client creation due to error")

            try:
                await client.disconnect()
            except Exception:
                LOGGER.exception("Error occurred while closing client. Ignoring")

            raise ConnectionException from err
        else:
            return cls(client)

    @classmethod
    async def create_rtu(
        cls,
        port: str,
        slave_id: int = DEFAULT_SLAVE_ID,
        *,
        cooldown_time: float = DEFAULT_COOLDOWN_TIME,
        **serial_kwargs: Unpack[PySerialOptions],
    ) -> Self:
        """Create a serial client."""
        if "baudrate" not in serial_kwargs:
            serial_kwargs["baudrate"] = DEFAULT_BAUDRATE

        client = create_async_rtu_client(port, unit_id=slave_id, wait_between_requests=cooldown_time, **serial_kwargs)
        try:
            await client.connect()
        except Exception as err:
            # if an error occurs, we need to make sure that the Modbus-client is stopped,
            # otherwise it can stay active and cause even more problems ...
            LOGGER.exception("Aborting client creation due to error")

            try:
                await client.disconnect()
            except Exception:
                LOGGER.exception("Error occurred while closing client. Ignoring")

            raise ConnectionException from err
        else:
            return cls(client)

    async def stop(self) -> None:
        """Stop the modbus client."""
        await self._client.disconnect()

    @property
    def slave_id(self) -> int:
        """Get the slave ID."""
        return self._client.unit_id

    def for_slave_id(self, slave_id: int) -> "AsyncHuaweiSolar":
        """Get a copy of this client for a different slave ID."""
        if slave_id == self.slave_id:
            return self
        return AsyncHuaweiSolar(self._client.for_unit_id(slave_id))

    async def get(self, name: str) -> Result:
        """Get named register from device."""
        return (await self.get_multiple([name]))[0]

    def _get_register_definitions(self, names: list[str]) -> list[RegisterDefinition]:
        """Get register definitions by name."""
        unknown_register_names = set(names) - REGISTERS.keys()
        if unknown_register_names:
            msg = f"Did not recognize register names: {', '.join(unknown_register_names)}"
            raise ValueError(msg)

        return [REGISTERS[name] for name in names]

    def _validate_registers_readable(self, names: list[str], registers: list[RegisterDefinition]) -> None:
        """Validate whether the requested registers are readable."""
        unreadable_register_names = [
            register_name for register, register_name in zip(registers, names, strict=False) if not register.readable
        ]
        if unreadable_register_names:
            msg = f"Trying to read unreadable registers: {', '.join(unreadable_register_names)}"
            raise ValueError(msg)

    def _construct_struct_format(self, registers: list[RegisterDefinition]) -> str:
        """Construct a struct format to interpret the registers content with."""
        struct_format = registers[0].format
        for idx in range(1, len(registers)):
            if registers[idx - 1].register + registers[idx - 1].length > registers[idx].register:
                msg = (
                    f"Requested registers must be in monotonically increasing order, "
                    f"but {registers[idx - 1].register} + {registers[idx - 1].length} > {registers[idx].register}!"
                )
                raise ValueError(msg)

            register_distance = registers[idx - 1].register + registers[idx - 1].length - registers[idx].register

            if register_distance > MAX_BATCHED_REGISTERS_COUNT:
                msg = "Gap between requested registers is too large. Split it in two requests"
                raise ValueError(msg)

            struct_format += f"{'x' * 2 * register_distance}{registers[idx].format}"

        return struct_format

    def _decode_response_tuple(
        self,
        registers: list[RegisterDefinition],
        response: tuple[Any, ...],
    ) -> list[Result]:
        """Decode response tuple."""
        result: list[Result] = []
        tuple_idx = 0
        for register in registers:
            register_values = register.decode(response[tuple_idx : tuple_idx + register.format_size])
            result.append(register_values)
            tuple_idx += register.format_size

        return result

    async def get_multiple(self, names: list[str], *, slave_id: int | None = None) -> list[Result]:
        """Read multiple registers at the same time.

        This is only possible if the registers are consecutively available in the
        inverters' memory.
        """
        if len(names) == 0:
            msg = "Expected at least one register name"
            raise ValueError(msg)

        registers = self._get_register_definitions(names)
        self._validate_registers_readable(names, registers)
        struct_format = self._construct_struct_format(registers)
        response_tuple = await self._read_registers(registers[0].register, struct_format, slave_id=slave_id)

        return self._decode_response_tuple(registers, response_tuple)

    async def _read_registers(
        self,
        start_address: int,
        struct_format: str,
        *,
        slave_id: int | None = None,
    ) -> tuple[Any, ...]:
        """Async read register from device.

        The device needs a bit of time between the connection and the first request
        and between requests if there is a long time between them, else it will fail.

        This is solved by sleeping between the first connection and a request,
        and up to 5 retries between following requests.

        It seems to only support connections from one device at the same time.
        """
        format_struct = struct.Struct(f">{struct_format}")
        LOGGER.debug(
            "Reading register %d with length %d from server %s",
            start_address,
            format_struct.size,
            self._client.unit_id,
        )

        client = self._client.for_unit_id(slave_id) if slave_id is not None else self._client

        return await client.read_struct_format(
            start_address,
            format_struct=format_struct,
        )

    async def _read_device_identifier_objects(
        self,
        read_dev_id_code: Literal[0x01, 0x03],
        object_id: int,
    ) -> dict[int, bytes]:
        """Read all the objects of a certain ReadDevId code."""
        try:
            return await self._client.read_device_identification(
                device_code=read_dev_id_code,
                object_id=object_id,
            )
        except (ServerDeviceBusyError, ServerDeviceFailureError, PermissionDeniedError) as e:
            LOGGER.debug(
                "Got a %s while reading device identification from server %d",
                type(e).__name__,
                self._client.unit_id,
            )
            raise
        except ModbusResponseError as e:
            msg = (
                f"Exception occurred while trying to read device infos "
                f"{hex(e.error_code) if e.error_code else 'no exception code'}"
            )
            raise ReadException(msg, modbus_exception_code=e.error_code) from e

    async def get_device_identifiers(self) -> DeviceIdentifier:
        """Read the device identifiers from the inverter."""
        objects = await self._read_device_identifier_objects(0x01, 0x00)

        return DeviceIdentifier(
            vendor=objects.pop(0x00).decode("ascii"),
            product_code=objects.pop(0x01).decode("ascii"),
            main_revision_version=objects.pop(0x02).decode("ascii"),
            other_data=objects,
        )

    async def get_device_infos(self) -> list[DeviceInfo]:
        """Read the device infos from the inverter."""
        objects = await self._read_device_identifier_objects(0x03, DEVICE_INFOS_START_OBJECT_ID)

        def _parse_device_entry(device_info_str: str) -> DeviceInfo:
            raw_device_info: dict[int, str] = {}
            for entry in device_info_str.split(";"):
                key, value = entry.split("=")
                raw_device_info[int(key)] = value

            return DeviceInfo(
                model=raw_device_info.get(1),
                software_version=raw_device_info.get(2),
                interface_protocol_version=raw_device_info.get(3),
                esn=raw_device_info.get(4),
                device_id=int(raw_device_info[5]) if 5 in raw_device_info else None,  # noqa: PLR2004
                feature_version=raw_device_info.get(6),
                unknown_field=raw_device_info.get(7),
                product_type=raw_device_info.get(8),
            )

        if DEVICE_INFOS_START_OBJECT_ID in objects:
            (number_of_devices,) = struct.unpack(">B", objects.pop(DEVICE_INFOS_START_OBJECT_ID))
        else:
            LOGGER.warning("No 0x87 entry with number of devices found in objects. Ignoring")
            number_of_devices = -1

        device_infos = [
            _parse_device_entry(device_info_bytes.decode("ascii")) for device_info_bytes in objects.values()
        ]

        if number_of_devices >= 0 and len(device_infos) != number_of_devices:
            LOGGER.warning(
                "Number of device infos does not match the number of devices: %d != %d",
                len(device_infos),
                number_of_devices,
            )

        return device_infos

    async def get_file(
        self,
        file_type: int,
        customized_data: bytes | None = None,
    ) -> bytes:
        """Read a 'file' via Modbus.

        As defined by the 'Uploading Files' process described in 6.3.7.1 of
        the Solar Inverter Modbus Interface Definitions PDF.
        """
        LOGGER.debug(
            "Reading file %#x from server %d",
            file_type,
            self._client.unit_id,
        )
        # Start the upload
        start_upload_response = await self._client.execute(
            StartFileUploadPDU(
                file_type=file_type,
                customised_data=customized_data or b"",
            ),
        )

        file_length = start_upload_response.file_length
        data_frame_length = start_upload_response.data_frame_length

        # Request the data in 'frames'

        file_data: bytes = b""
        next_frame_no = 0

        while (next_frame_no * data_frame_length) < file_length:
            data_upload_response = await self._client.execute(
                UploadFileFramePDU(file_type=file_type, frame_no=next_frame_no),
            )

            file_data += data_upload_response.frame_data
            next_frame_no += 1

        # Complete the upload and check the CRC
        file_crc = await self._client.execute(
            CompleteUploadPDU(file_type=file_type),
        )

        # swap upper and lower two bytes to match how computeCRC works
        swapped_crc = ((file_crc << 8) & 0xFF00) | ((file_crc >> 8) & 0x00FF)

        if (calculated_crc := int.from_bytes(calculate_crc16(file_data))) != swapped_crc:
            msg = (
                f"Computed CRC {calculated_crc:04x} for file {file_type} "
                f"does not match expected value {swapped_crc:04x}"
            )
            raise ReadException(msg)

        return file_data

    async def set(
        self,
        name: str,
        value: Any,  # noqa: ANN401
    ) -> bool:
        """Set named register on device."""
        try:
            reg = REGISTERS[name]
        except KeyError as err:
            msg = "Invalid Register Name"
            raise ValueError(msg) from err

        if not reg.writeable:
            msg = "Register is not writable"
            raise WriteException(msg)

        return await self._write_registers(reg, reg.encode(value))

    def _validate_data_to_write(self, register: RegisterDefinition, values: tuple[Any, ...]) -> None:
        """Validate if the data to write is valid."""
        encoded_value_to_write = struct.pack(f">{register.format}", *values)
        if len(encoded_value_to_write) != register.length * 2:  # 2 bytes per register
            msg = "Wrong number of registers to write"
            raise WriteException(msg)

    async def _write_registers(
        self,
        register: RegisterDefinition,
        values: tuple[Any, ...],
    ) -> bool:
        """Async write register to device."""
        self._validate_data_to_write(register, values)
        try:
            if register.length == 1:
                LOGGER.debug(
                    "Writing to %d: single value '%s' on server %d",
                    register.register,
                    values[0],
                    self._client.unit_id,
                )

                response = await self._client.write_single_register(register.register, values[0])

                success = response == values[0]
            else:
                LOGGER.debug(
                    "Writing to %d: values '%s' on server %d",
                    register.register,
                    values,
                    self._client.unit_id,
                )

                registers_written = await self._client.write_struct_format(
                    register.register,
                    values,
                    format_struct=f">{register.format}",
                )

                success = registers_written == register.length

        except PermissionDeniedError:
            raise
        except IllegalDataAddressError as e:
            msg = (
                f"Failed to write value {values} to register {register} due to IllegalDataAddress. "
                "Assuming permission problem."
            )
            raise PermissionDeniedError(PermissionDeniedError.error_code, e.function_code) from e
        except ModbusResponseError as e:
            msg = f"Failed to write value {values} to register {register}: {e.error_code:02x}"
            raise WriteException(msg, modbus_exception_code=e.error_code) from e
        except ModbusConnectionError as err:
            LOGGER.exception("Failed to connect to device, is the host correct?")
            raise ConnectionInterruptedException(err) from err
        return success

    async def login(self, username: str, password: str) -> bool:
        """Login onto the inverter."""
        LOGGER.debug("Logging in '%s'", username)
        inverter_challenge = await self._client.execute(
            LoginRequestChallengePDU(),
        )

        logged_in = await self._client.execute(
            LoginPDU(username, password, inverter_challenge),
        )
        if logged_in:
            # Make sure we re-login after a reconnect
            assert isinstance(self._client.transport, AsyncSmartTransport)

            async def login_on_reconnect() -> None:
                """Login again after a reconnect."""
                LOGGER.info("Reconnected to inverter, logging in again")
                logged_in_again = await self.login(username, password)
                if not logged_in_again:
                    LOGGER.error("Failed to login after reconnect. Will not try again.")
                    assert isinstance(self._client.transport, AsyncSmartTransport)
                    self._client.transport.on_reconnected = None

            self._client.transport.on_reconnected = login_on_reconnect

        return logged_in

    async def heartbeat(self) -> bool:
        """Perform the heartbeat command. Only useful when maintaining a session."""
        if not self._client.connected:
            return False
        try:
            # 49999 is the magic register used to keep the connection alive
            await self._client.write_single_register(
                HEARTBEAT_REGISTER,
                0x1,
            )
        except ModbusResponseError as e:
            LOGGER.warning("Received an error response when writing to the heartbeat register: %02x", e.error_code)
            return False
        except TModbusError:
            LOGGER.exception("Exception during heartbeat")
            return False
        else:
            LOGGER.debug("Heartbeat succeeded")
            return True
