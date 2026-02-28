"""Tests for peak period register validation and encoding/decoding."""

import huawei_solar.register_names as rn
import pytest
from huawei_solar.exceptions import PeakPeriodsValidationError
from huawei_solar.register_definitions.periods import PeakSettingPeriod
from huawei_solar.registers import REGISTERS

ppr = REGISTERS[rn.STORAGE_CAPACITY_CONTROL_PERIODS]


def test_simple() -> None:
    pp_valid = [
        PeakSettingPeriod(
            start_time=0,
            end_time=1440,
            power=2500,
            days_effective=(True, True, True, True, True, True, True),
        ),
    ]

    ppr._validate(pp_valid)


def test_invalid_start_time() -> None:
    pp = [
        PeakSettingPeriod(
            start_time=60 * 24 + 1,
            end_time=15,
            power=2500,
            days_effective=(True, True, True, True, True, True, True),
        ),
    ]

    with pytest.raises(
        expected_exception=PeakPeriodsValidationError,
        match="Every day must be covered from 00:00",
    ):
        ppr._validate(pp)


def test_invalid_end_time() -> None:
    pp = [
        PeakSettingPeriod(
            start_time=0,
            end_time=15,
            power=2500,
            days_effective=(True, True, True, True, True, True, True),
        ),
    ]

    with pytest.raises(
        expected_exception=PeakPeriodsValidationError,
        match="Every day must be covered until 23:59",
    ):
        ppr._validate(pp)

    pp2 = [
        PeakSettingPeriod(
            start_time=0,
            end_time=1441,
            power=2500,
            days_effective=(True, True, True, True, True, True, True),
        ),
    ]

    with pytest.raises(
        expected_exception=PeakPeriodsValidationError,
        match="Every day must be covered until 23:59",
    ):
        ppr._validate(pp2)


def test_all_days_of_week_covered() -> None:
    pp = [
        PeakSettingPeriod(
            start_time=0,
            end_time=15,
            power=2500,
            days_effective=(False, True, True, True, True, True, True),
        ),
    ]

    with pytest.raises(
        expected_exception=PeakPeriodsValidationError,
        match="All days of the week need to be covered",
    ):
        ppr._validate(pp)


def test_multiple_periods_on_a_day() -> None:
    pp = [
        PeakSettingPeriod(
            start_time=0,
            end_time=1439,
            power=2500,
            days_effective=(False, True, True, True, True, True, True),
        ),
        PeakSettingPeriod(
            start_time=0,
            end_time=600,
            power=2500,
            days_effective=(True, False, False, False, False, False, False),
        ),
        PeakSettingPeriod(
            start_time=600,
            end_time=1439,
            power=2500,
            days_effective=(True, False, False, False, False, False, False),
        ),
    ]

    ppr._validate(pp)

    encoded = ppr.encode(pp)
    assert ppr.decode(encoded).value == pp

    pp2 = [
        PeakSettingPeriod(
            start_time=0,
            end_time=1439,
            power=2500,
            days_effective=(False, True, True, True, True, True, True),
        ),
        PeakSettingPeriod(
            start_time=0,
            end_time=600,
            power=2500,
            days_effective=(True, False, False, False, False, False, False),
        ),
        PeakSettingPeriod(
            start_time=601,
            end_time=1439,
            power=2500,
            days_effective=(True, False, False, False, False, False, False),
        ),
    ]

    ppr._validate(pp2)

    pp3 = [
        PeakSettingPeriod(
            start_time=0,
            end_time=1439,
            power=2500,
            days_effective=(False, True, True, True, True, True, True),
        ),
        PeakSettingPeriod(
            start_time=0,
            end_time=600,
            power=2500,
            days_effective=(True, False, False, False, False, False, False),
        ),
        PeakSettingPeriod(
            start_time=602,
            end_time=1439,
            power=2500,
            days_effective=(True, False, False, False, False, False, False),
        ),
    ]

    with pytest.raises(
        expected_exception=PeakPeriodsValidationError,
        match="All moments of each day need to be covered",
    ):
        ppr._validate(pp3)


def test_capacity_control_register() -> None:
    value = [
        PeakSettingPeriod(0, 1439, 2551, (True, True, True, True, True, True, False)),
        PeakSettingPeriod(
            0,
            200,
            2550,
            (False, False, False, False, False, False, True),
        ),
        PeakSettingPeriod(
            200,
            1439,
            2449,
            (False, False, False, False, False, False, True),
        ),
    ]

    pspr = REGISTERS[rn.STORAGE_CAPACITY_CONTROL_PERIODS]

    payload = pspr.encode(value)

    decoded_result = pspr.decode(payload).value

    assert decoded_result == value
