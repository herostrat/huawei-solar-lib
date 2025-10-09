"""String register definition."""

from typing import Any

from huawei_solar.exceptions import DecodeError

from .base import RegisterDefinition, Result, TargetDevice


class StringRegister(RegisterDefinition[str]):
    """A string register."""

    def __init__(
        self,
        register: int,
        length: int,
        *,
        writeable: bool = False,
        readable: bool = True,
        target_device: TargetDevice = TargetDevice.SUN2000,
    ) -> None:
        """Create StringRegister."""
        super().__init__(
            register,
            writeable=writeable,
            readable=readable,
            target_device=target_device,
        )
        self.length = length
        self.format = f"{length * 2}s"  # every register has two bytes

    def encode(self, data: str) -> tuple[Any, ...]:
        """Encode string into registers."""
        return (data.encode("utf-8"),)

    def decode(self, values: tuple[Any, ...]) -> Result[str]:
        """Decode string."""
        value = values[0]
        # Strip any output after the first null-byte
        null_byte_index = value.find(b"\x00")
        if null_byte_index != -1:
            value = value[:null_byte_index]

        try:
            return Result(value.decode("utf-8"), None)
        except UnicodeDecodeError as err:
            raise DecodeError from err
