"""Huawei SmartLogger device support."""

from huawei_solar import register_names as rn

from .base import HuaweiSolarDevice


class SmartLoggerDevice(HuaweiSolarDevice):
    """An SmartLogger device."""

    model_name: str

    @classmethod
    def supports_device(cls, model_name: str) -> bool:
        """Check if this class support the given device."""
        return model_name.startswith("SmartLogger")

    async def _populate_additional_fields(self) -> None:
        self.model_name = (await self.get(rn.MODEL_NAME)).value
