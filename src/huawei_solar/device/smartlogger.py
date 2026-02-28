"""Huawei SmartLogger device support."""

from huawei_solar import register_names as rn

from .base import HuaweiSolarDevice


class SmartLoggerDevice(HuaweiSolarDevice):
    """An SmartLogger device."""

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith("SmartLogger")

    async def _populate_additional_fields(self) -> None:
        model_name_result, serial_number_result = await self.client.get_multiple([rn.MODEL_NAME, rn.SERIAL_NUMBER])

        self.model_name = model_name_result.value
        self.serial_number = serial_number_result.value
