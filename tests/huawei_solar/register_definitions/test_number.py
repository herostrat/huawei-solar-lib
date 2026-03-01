"""Tests for number register decoding and encoding."""

from huawei_solar.register_definitions.number import (
    I16Register,
    I32Register,
    I64Register,
    U16Register,
    U32Register,
    U64Register,
)


class TestInvalidValueDetection:
    """Test that invalid/sentinel values are correctly detected during decode."""

    def test_u16_all_ones_is_invalid(self) -> None:
        """U16: 0xFFFF should decode to None (standard Huawei sentinel)."""
        reg = U16Register("kWh", 1, 30000)
        result = reg.decode((0xFFFF,))
        assert result.value is None

    def test_u32_all_ones_is_invalid(self) -> None:
        """U32: 0xFFFFFFFF should decode to None (standard Huawei sentinel)."""
        reg = U32Register("kWh", 1, 30000)
        result = reg.decode((0xFFFFFFFF,))
        assert result.value is None

    def test_u64_huawei_sentinel_is_invalid(self) -> None:
        """U64: 0x7FFFFFFFFFFFFFFF should decode to None (Huawei sentinel)."""
        reg = U64Register("kWh", 100, 30000)
        result = reg.decode((2**63 - 1,))
        assert result.value is None

    def test_u64_all_ones_is_invalid(self) -> None:
        """U64: 0xFFFFFFFFFFFFFFFF should decode to None.

        This value occurs during Modbus communication errors when all
        registers return 0xFFFF. Without this check, it decodes to
        ~1.84e17 kWh and permanently corrupts total_increasing statistics.
        """
        reg = U64Register("kWh", 100, 30000)
        result = reg.decode((2**64 - 1,))
        assert result.value is None

    def test_u64_valid_value_passes(self) -> None:
        """U64: Normal values should decode correctly with gain applied."""
        reg = U64Register("kWh", 100, 30000)
        result = reg.decode((123456,))
        assert result.value == 1234.56

    def test_u64_zero_is_valid(self) -> None:
        """U64: Zero should decode to 0."""
        reg = U64Register("kWh", 100, 30000)
        result = reg.decode((0,))
        assert result.value == 0

    def test_i16_sentinel_is_invalid(self) -> None:
        """I16: 0x7FFF should decode to None."""
        reg = I16Register("kWh", 1, 30000)
        result = reg.decode((2**15 - 1,))
        assert result.value is None

    def test_i32_sentinel_is_invalid(self) -> None:
        """I32: 0x7FFFFFFF should decode to None."""
        reg = I32Register("kWh", 1, 30000)
        result = reg.decode((2**31 - 1,))
        assert result.value is None

    def test_i64_sentinel_is_invalid(self) -> None:
        """I64: 0x7FFFFFFFFFFFFFFF should decode to None."""
        reg = I64Register("kWh", 100, 30000)
        result = reg.decode((2**63 - 1,))
        assert result.value is None

    def test_u16_ignore_invalid(self) -> None:
        """U16 with ignore_invalid: 0xFFFF should pass through as valid."""
        reg = U16Register("kWh", 1, 30000, ignore_invalid=True)
        result = reg.decode((0xFFFF,))
        assert result.value == 0xFFFF


class TestGainApplication:
    """Test that gain is correctly applied during decode."""

    def test_gain_divides_value(self) -> None:
        reg = U32Register("kWh", 100, 30000)
        result = reg.decode((50000,))
        assert result.value == 500.0

    def test_gain_one_no_division(self) -> None:
        reg = U32Register("W", 1, 30000)
        result = reg.decode((1234,))
        assert result.value == 1234
