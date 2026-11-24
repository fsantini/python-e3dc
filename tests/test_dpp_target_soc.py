"""Unit tests for Dynamic Power Pricing target SoC support."""

from unittest.mock import Mock

import pytest

from e3dc._e3dc import E3DC
from e3dc._rscpTags import RscpTag, RscpType


@pytest.fixture
def device():
    instance = object.__new__(E3DC)
    instance.sendRequest = Mock()
    instance.sendRequestTag = Mock()
    return instance


def test_get_dpp_target_soc(device):
    device.sendRequestTag.return_value = 90
    assert device.get_dpp_target_soc() == 90
    device.sendRequestTag.assert_called_once_with(
        RscpTag.EMS_REQ_DPP_SOC_BATTERY, keepAlive=False
    )


def test_get_dpp_enabled(device):
    device.sendRequestTag.return_value = True
    assert device.get_dpp_price_based_charging_enabled() is True
    device.sendRequestTag.assert_called_once_with(
        RscpTag.EMS_REQ_DPP_PRICE_BASED_BATTERY_CHARGE_ENABLED, keepAlive=False
    )


def test_set_dpp_target_soc(device):
    device.sendRequest.return_value = (
        RscpTag.EMS_DPP_SET_SOC_BATTERY,
        RscpType.UChar8,
        89,
    )
    assert device.set_dpp_target_soc(89) == 89
    device.sendRequest.assert_called_once_with(
        (RscpTag.EMS_REQ_DPP_SET_SOC_BATTERY, RscpType.UChar8, 89),
        keepAlive=False,
    )


@pytest.mark.parametrize("invalid", [-1, 101, 90.5, True, "90", None])
def test_set_dpp_target_soc_rejects_invalid_values(device, invalid):
    with pytest.raises(ValueError):
        device.set_dpp_target_soc(invalid)
    device.sendRequest.assert_not_called()


def test_set_dpp_target_soc_rejects_unexpected_response(device):
    device.sendRequest.return_value = (RscpTag.EMS_BAT_SOC, RscpType.UChar8, 89)
    with pytest.raises(ValueError, match="Unexpected"):
        device.set_dpp_target_soc(89)
