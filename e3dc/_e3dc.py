#!/usr/bin/env python
# Python class to connect to an E3/DC system.
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details
from __future__ import annotations  # required for python < 3.9

import datetime
import hashlib
import time
import uuid
from calendar import monthrange
from typing import Any, Dict, List, Literal, Tuple

from ._e3dc_rscp_local import (
    E3DC_RSCP_local,
    RSCPAuthenticationError,
    RSCPKeyError,
    RSCPNotAvailableError,
)
from ._e3dc_rscp_web import E3DC_RSCP_web
from ._rscpLib import rscpFindTag, rscpFindTagIndex
from ._rscpTags import RscpTag, RscpType, getStrPowermeterType, getStrPviType

REMOTE_ADDRESS = "https://s10.e3dc.com/s10/phpcmd/cmd.php"
REQUEST_INTERVAL_SEC = 10  # minimum interval between requests
REQUEST_INTERVAL_SEC_LOCAL = 1  # minimum interval between requests


class AuthenticationError(Exception):
    """Class for Authentication Error Exception."""

    pass


class NotAvailableError(Exception):
    """Class for Not Available Error Exception."""

    pass


class PollError(Exception):
    """Class for Poll Error Exception."""

    pass


class SendError(Exception):
    """Class for Send Error Exception."""

    pass


class E3DC:
    """A class describing an E3DC system."""

    CONNECT_LOCAL = 1
    CONNECT_WEB = 2

    _IDLE_TYPE = {"idleCharge": 0, "idleDischarge": 1}

    def __init__(self, connectType: int, **kwargs: Any) -> None:
        """Constructor of an E3DC object.

        Args:
            connectType: can be one of the following
                E3DC.CONNECT_LOCAL use local rscp connection
                E3DC.CONNECT_WEB use web connection
            **kwargs: Arbitrary keyword argument

        Keyword Args:
            username (str): username
            password (str): password (plain text)
            ipAddress (str): IP address of the E3DC system - required for CONNECT_LOCAL
            key (str): encryption key as set in the E3DC settings - required for CONNECT_LOCAL
            serialNumber (str): the serial number of the system to monitor - required for CONNECT_WEB
            isPasswordMd5 (Optional[bool]): indicates whether the password is already md5 digest (recommended, default = True) - required for CONNECT_WEB
            configuration (Optional[dict]): dict containing details of the E3DC configuration. {"pvis": [{"index": 0, "strings": 2, "phases": 3}], "powermeters": [{"index": 0}], "batteries": [{"index": 0, "dcbs": 1}]}
        """
        self.connectType = connectType
        self.username = kwargs["username"]
        self.serialNumber = None
        self.serialNumberPrefix = None

        self.jar = None
        self.guid = "GUID-" + str(uuid.uuid1())
        self.lastRequestTime = -1
        self.lastRequest = None
        self.connected = False

        # static values
        self.deratePercent = None
        self.deratePower = None
        self.installedPeakPower = None
        self.installedBatteryCapacity = None
        self.externalSourceAvailable = None
        self.macAddress = None
        self.model = None
        self.maxAcPower = None
        self.maxBatChargePower = None
        self.maxBatDischargePower = None
        self.startDischargeDefault = None
        self.powermeters: List[Dict[str, Any]] = []
        self.pvis: List[Dict[str, Any]] = []
        self.batteries: List[Dict[str, Any]] = []
        self.pmIndexExt = None

        if "configuration" in kwargs:
            configuration = kwargs["configuration"]
            if "pvis" in configuration and isinstance(configuration["pvis"], list):
                self.pvis = configuration["pvis"]
            if "powermeters" in configuration and isinstance(
                configuration["powermeters"], list
            ):
                self.powermeters = configuration["powermeters"]
            if "batteries" in configuration and isinstance(
                configuration["batteries"], list
            ):
                self.batteries = configuration["batteries"]

        if connectType == self.CONNECT_LOCAL:
            self.ip = kwargs["ipAddress"]
            self.key = kwargs["key"]
            self.password = kwargs["password"]
            self.rscp = E3DC_RSCP_local(self.username, self.password, self.ip, self.key)
        else:
            self._set_serial(kwargs["serialNumber"])
            if "isPasswordMd5" in kwargs and not kwargs["isPasswordMd5"]:
                self.password = kwargs["password"]
            else:
                self.password = hashlib.md5(
                    kwargs["password"].encode("utf-8")
                ).hexdigest()
            self.rscp = E3DC_RSCP_web(
                self.username,
                self.password,
                "{}{}".format(self.serialNumberPrefix, self.serialNumber),
            )

        self.get_system_info_static(keepAlive=True)

    def _set_serial(self, serial: str):
        self.batteries = self.batteries or [{"index": 0}]
        self.pmIndexExt = 1

        if serial[0].isdigit():
            self.serialNumber = serial
        else:
            self.serialNumber = serial[4:]
            self.serialNumberPrefix = serial[:4]

        if self.serialNumber.startswith("4") or self.serialNumber.startswith("72"):
            self.model = "S10E"
            self.powermeters = self.powermeters or [{"index": 0}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "S10-"
        elif self.serialNumber.startswith("74"):
            self.model = "S10E_Compact"
            self.powermeters = self.powermeters or [{"index": 0}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "S10-"
        elif self.serialNumber.startswith("5"):
            self.model = "S10_Mini"
            self.powermeters = self.powermeters or [{"index": 6}]
            self.pvis = self.pvis or [{"index": 0, "phases": 1}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "S10-"
        elif self.serialNumber.startswith("6"):
            self.model = "Quattroporte"
            self.powermeters = self.powermeters or [{"index": 6}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "Q10-"
        elif self.serialNumber.startswith("70"):
            self.model = "S10E_Pro"
            self.powermeters = self.powermeters or [{"index": 0}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "P10-"
        elif self.serialNumber.startswith("75"):
            self.model = "S10E_Pro_Compact"
            self.powermeters = self.powermeters or [{"index": 0}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "P10-"
        elif self.serialNumber.startswith("8"):
            self.model = "S10X"
            self.powermeters = self.powermeters or [{"index": 0}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "H20-"
        else:
            self.model = "NA"
            self.powermeters = self.powermeters or [{"index": 0}]
            self.pvis = self.pvis or [{"index": 0}]

    def sendRequest(
        self,
        request: Tuple[str | int | RscpTag, str | int | RscpType, Any],
        retries: int = 3,
        keepAlive: bool = False,
    ) -> Tuple[str | int | RscpTag, str | int | RscpType, Any]:
        """This function uses the RSCP interface to make a request.

        Does make retries in case of exceptions like Socket.Error

        Args:
            request: the request to send
            retries (Optional[int]): number of retries
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            An object with the received data

        Raises:
            e3dc.AuthenticationError: login error
            e3dc.SendError: if retries are reached
        """
        retry = 0
        while True:
            try:
                if not self.rscp.isConnected():
                    self.rscp.connect()
                result = self.rscp.sendRequest(request)
                break
            except RSCPAuthenticationError:
                raise AuthenticationError()
            except RSCPNotAvailableError:
                raise NotAvailableError()
            except RSCPKeyError:
                raise
            except Exception:
                retry += 1
                if retry > retries:
                    raise SendError("Max retries reached")

        if not keepAlive:
            self.rscp.disconnect()

        return result

    def sendRequestTag(
        self, tag: str | int | RscpTag, retries: int = 3, keepAlive: bool = False
    ):
        """This function uses the RSCP interface to make a request for a single tag.

        Does make retries in case of exceptions like Socket.Error

        Args:
            tag (str): the request to send
            retries (Optional[int]): number of retries
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            An object with the received data

        Raises:
            e3dc.AuthenticationError: login error
            e3dc.SendError: if retries are reached
        """
        return self.sendRequest(
            (tag, RscpType.NoneType, None), retries=retries, keepAlive=keepAlive
        )[2]

    def disconnect(self):
        """This function does disconnect the connection."""
        self.rscp.disconnect()

    def poll(self, keepAlive: bool = False):
        """Polls via rscp protocol.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the condensed status information structured as follows::

                {
                    "autarky": <autarky in %>,
                    "consumption": {
                        "battery": <power entering battery (positive: charging, negative: discharging)>,
                        "house": <house consumption>,
                        "wallbox": <wallbox consumption>
                    }
                    "production": {
                        "solar" : <production from solar in W>,
                        "add" : <additional external power in W>,
                        "grid" : <absorption from grid in W>
                    }
                    "stateOfCharge": <battery charge status in %>,
                    "selfConsumption": <self consumed power in %>,
                    "time": <datetime object containing the timestamp>
                }
        """
        if (
            self.lastRequest is not None
            and (time.time() - self.lastRequestTime) < REQUEST_INTERVAL_SEC_LOCAL
        ):
            return self.lastRequest

        ts = self.sendRequestTag(RscpTag.INFO_REQ_UTC_TIME, keepAlive=True)
        soc = self.sendRequestTag(RscpTag.EMS_REQ_BAT_SOC, keepAlive=True)
        solar = self.sendRequestTag(RscpTag.EMS_REQ_POWER_PV, keepAlive=True)
        add = self.sendRequestTag(RscpTag.EMS_REQ_POWER_ADD, keepAlive=True)
        bat = self.sendRequestTag(RscpTag.EMS_REQ_POWER_BAT, keepAlive=True)
        home = self.sendRequestTag(RscpTag.EMS_REQ_POWER_HOME, keepAlive=True)
        grid = self.sendRequestTag(RscpTag.EMS_REQ_POWER_GRID, keepAlive=True)
        wb = self.sendRequestTag(RscpTag.EMS_REQ_POWER_WB_ALL, keepAlive=True)
        sc = self.sendRequestTag(RscpTag.EMS_REQ_SELF_CONSUMPTION, keepAlive=True)
        # last call, use keepAlive value
        autarky = self.sendRequestTag(RscpTag.EMS_REQ_AUTARKY, keepAlive=keepAlive)

        outObj = {
            "autarky": autarky,
            "consumption": {"battery": bat, "house": home, "wallbox": wb},
            "production": {"solar": solar, "add": -add, "grid": grid},
            "selfConsumption": sc,
            "stateOfCharge": soc,
            "time": datetime.datetime.utcfromtimestamp(ts).replace(
                tzinfo=datetime.timezone.utc
            ),
        }

        self.lastRequest = outObj
        self.lastRequestTime = time.time()
        return outObj

    def poll_switches(self, keepAlive: bool = False):
        """This function uses the RSCP interface to poll the switch status.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            list[dict]: list of the switches::

                [
                    {
                        "id": <id>,
                        "type": <type>,
                        "name": <name>,
                        "status": <status>
                    }
                ]
        """
        if not self.rscp.isConnected():
            self.rscp.connect()

        switchDesc = self.sendRequest(
            (RscpTag.HA_REQ_DATAPOINT_LIST, RscpType.NoneType, None), keepAlive=True
        )
        switchStatus = self.sendRequest(
            (RscpTag.HA_REQ_ACTUATOR_STATES, RscpType.NoneType, None),
            keepAlive=keepAlive,
        )

        descList = switchDesc[2]  # get the payload of the container
        statusList = switchStatus[2]

        switchList = []

        for switch in range(len(descList)):
            switchID = rscpFindTagIndex(descList[switch], RscpTag.HA_DATAPOINT_INDEX)
            switchType = rscpFindTagIndex(descList[switch], RscpTag.HA_DATAPOINT_TYPE)
            switchName = rscpFindTagIndex(descList[switch], RscpTag.HA_DATAPOINT_NAME)
            switchStatus = rscpFindTagIndex(
                statusList[switch], RscpTag.HA_DATAPOINT_STATE
            )
            switchList.append(
                {
                    "id": switchID,
                    "type": switchType,
                    "name": switchName,
                    "status": switchStatus,
                }
            )

        return switchList

    def set_switch_onoff(
        self, switchID: int, value: Literal["on", "off"], keepAlive: bool = False
    ):
        """This function uses the RSCP interface to turn a switch on or off.

        Args:
            switchID (int): id of the switch
            value (str): value
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            True/False

        """
        cmd = "on" if value else "off"

        result = self.sendRequest(
            (
                RscpTag.HA_REQ_COMMAND_ACTUATOR,
                RscpType.Container,
                [
                    (RscpTag.HA_DATAPOINT_INDEX, RscpType.Uint16, switchID),
                    (RscpTag.HA_REQ_COMMAND, RscpType.CString, cmd),
                ],
            ),
            keepAlive=keepAlive,
        )

        if result[0] == RscpTag.HA_COMMAND_ACTUATOR and result[2]:
            return True
        else:
            return False  # operation did not succeed

    def get_idle_periods(self, keepAlive: bool = False):
        """Poll via rscp protocol to get idle periods.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the idle periods structured as follows::

                {
                    "idleCharge":
                    [
                        {
                            "day": <the week day from 0 to 6>,
                            "start":
                            [
                                <hour from 0 to 23>,
                                <minute from 0 to 59>
                            ],
                            "end":
                            [
                                <hour from 0 to 23>,
                                <minute from 0 to 59>
                            ],
                            "active": <boolean of state>
                        }
                    ],
                    "idleDischarge":
                    [
                        {
                            "day": <the week day from 0 to 6>,
                            "start":
                            [
                                <hour from 0 to 23>,
                                <minute from 0 to 59>
                            ],
                            "end":
                            [
                                <hour from 0 to 23>,
                                <minute from 0 to 59>
                            ],
                            "active": <boolean of state>
                        }
                    ]
                }
        """
        idlePeriodsRaw = self.sendRequest(
            (RscpTag.EMS_REQ_GET_IDLE_PERIODS, RscpType.NoneType, None),
            keepAlive=keepAlive,
        )
        if idlePeriodsRaw[0] != RscpTag.EMS_GET_IDLE_PERIODS:
            return None

        idlePeriods = {"idleCharge": [{}] * 7, "idleDischarge": [{}] * 7}

        # initialize
        for period in idlePeriodsRaw[2]:
            active = rscpFindTagIndex(period, RscpTag.EMS_IDLE_PERIOD_ACTIVE)
            typ = rscpFindTagIndex(period, RscpTag.EMS_IDLE_PERIOD_TYPE)
            day = rscpFindTagIndex(period, RscpTag.EMS_IDLE_PERIOD_DAY)
            start = rscpFindTag(period, RscpTag.EMS_IDLE_PERIOD_START)
            startHour = rscpFindTagIndex(start, RscpTag.EMS_IDLE_PERIOD_HOUR)
            startMin = rscpFindTagIndex(start, RscpTag.EMS_IDLE_PERIOD_MINUTE)
            end = rscpFindTag(period, RscpTag.EMS_IDLE_PERIOD_END)
            endHour = rscpFindTagIndex(end, RscpTag.EMS_IDLE_PERIOD_HOUR)
            endMin = rscpFindTagIndex(end, RscpTag.EMS_IDLE_PERIOD_MINUTE)
            periodObj = {
                "day": day,
                "start": [startHour, startMin],
                "end": [endHour, endMin],
                "active": active,
            }

            if typ == self._IDLE_TYPE["idleCharge"]:
                idlePeriods["idleCharge"][day] = periodObj
            else:
                idlePeriods["idleDischarge"][day] = periodObj

        return idlePeriods

    def set_idle_periods(
        self, idlePeriods: Dict[str, List[Dict[str, Any]]], keepAlive: bool = False
    ):
        """Set idle periods via rscp protocol.

        Args:
            idlePeriods (dict): Dictionary containing one or many idle periods::

                {
                    "idleCharge":
                    [
                        {
                            "day": <the week day from 0 to 6>,
                            "start":
                            [
                                <hour from 0 to 23>,
                                <minute from 0 to 59>
                            ],
                            "end":
                            [
                                <hour from 0 to 23>,
                                <minute from 0 to 59>
                            ],
                            "active": <boolean of state>
                        }
                    ],
                    "idleDischarge":
                    [
                        {
                            "day": <the week day from 0 to 6>,
                            "start":
                            [
                                <hour from 0 to 23>,
                                <minute from 0 to 59>
                            ],
                            "end":
                            [
                                <hour from 0 to 23>,
                                <minute from 0 to 59>
                            ],
                            "active": <boolean of state>
                        }
                    ]
                }
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            True if success
            False if error
        """
        periodList = []

        if "idleCharge" not in idlePeriods and "idleDischarge" not in idlePeriods:
            raise ValueError("neither key idleCharge nor idleDischarge in object")

        for idle_type in ["idleCharge", "idleDischarge"]:
            if idle_type in idlePeriods:
                for idlePeriod in idlePeriods[idle_type]:
                    if "day" not in idlePeriod:
                        raise ValueError("day key in " + idle_type + " missing")
                    elif isinstance(idlePeriod["day"], bool):
                        raise TypeError("day in " + idle_type + " not a bool")
                    elif not (0 <= idlePeriod["day"] <= 6):
                        raise ValueError("day in " + idle_type + " out of range")

                    if idlePeriod.keys() & ["active", "start", "end"]:
                        if "active" in idlePeriod:
                            if isinstance(idlePeriod["active"], bool):
                                idlePeriod["active"] = idlePeriod["active"]
                            else:
                                raise TypeError(
                                    "period "
                                    + str(idlePeriod["day"])
                                    + " in "
                                    + idle_type
                                    + " not a bool"
                                )

                        for key in ["start", "end"]:
                            if key in idlePeriod:
                                if (
                                    isinstance(idlePeriod[key], list)
                                    and len(idlePeriod[key]) == 2
                                ):
                                    for i in range(2):
                                        if isinstance(idlePeriod[key][i], int):
                                            if idlePeriod[key][i] >= 0 and (
                                                (i == 0 and idlePeriod[key][i] < 24)
                                                or (i == 1 and idlePeriod[key][i] < 60)
                                            ):
                                                idlePeriod[key][i] = idlePeriod[key][i]
                                            else:
                                                raise ValueError(
                                                    key
                                                    in " period "
                                                    + str(idlePeriod["day"])
                                                    + " in "
                                                    + idle_type
                                                    + " is not between 00:00 and 23:59"
                                                )
                        if (idlePeriod["start"][0] * 60 + idlePeriod["start"][1]) < (
                            idlePeriod["end"][0] * 60 + idlePeriod["end"][1]
                        ):
                            periodList.append(
                                (
                                    RscpTag.EMS_IDLE_PERIOD,
                                    RscpType.Container,
                                    [
                                        (
                                            RscpTag.EMS_IDLE_PERIOD_TYPE,
                                            RscpType.UChar8,
                                            self._IDLE_TYPE[idle_type],
                                        ),
                                        (
                                            RscpTag.EMS_IDLE_PERIOD_DAY,
                                            RscpType.UChar8,
                                            idlePeriod["day"],
                                        ),
                                        (
                                            RscpTag.EMS_IDLE_PERIOD_ACTIVE,
                                            RscpType.Bool,
                                            idlePeriod["active"],
                                        ),
                                        (
                                            RscpTag.EMS_IDLE_PERIOD_START,
                                            RscpType.Container,
                                            [
                                                (
                                                    RscpTag.EMS_IDLE_PERIOD_HOUR,
                                                    RscpType.UChar8,
                                                    idlePeriod["start"][0],
                                                ),
                                                (
                                                    RscpTag.EMS_IDLE_PERIOD_MINUTE,
                                                    RscpType.UChar8,
                                                    idlePeriod["start"][1],
                                                ),
                                            ],
                                        ),
                                        (
                                            RscpTag.EMS_IDLE_PERIOD_END,
                                            RscpType.Container,
                                            [
                                                (
                                                    RscpTag.EMS_IDLE_PERIOD_HOUR,
                                                    RscpType.UChar8,
                                                    idlePeriod["end"][0],
                                                ),
                                                (
                                                    RscpTag.EMS_IDLE_PERIOD_MINUTE,
                                                    RscpType.UChar8,
                                                    idlePeriod["end"][1],
                                                ),
                                            ],
                                        ),
                                    ],
                                )
                            )
                        else:
                            raise ValueError(
                                "end time is smaller than start time in period "
                                + str(idlePeriod["day"])
                                + " in "
                                + idle_type
                                + " is not between 00:00 and 23:59"
                            )

                    else:
                        raise TypeError("period in " + idle_type + " is not a dict")

                else:
                    raise TypeError(idle_type + " is not a dict")

        result = self.sendRequest(
            (RscpTag.EMS_REQ_SET_IDLE_PERIODS, RscpType.Container, periodList),
            keepAlive=keepAlive,
        )

        if result[0] != RscpTag.EMS_SET_IDLE_PERIODS or result[2] != 1:
            return False
        return True

    def get_db_data_timestamp(
        self, startTimestamp: int, timespanSeconds: int, keepAlive: bool = False
    ):
        """Reads DB data and summed up values for the given timespan via rscp protocol.

        Args:
            startTimestamp (int): UNIX timestampt from where the db data should be collected
            timespanSeconds (int): number of seconds for which the data should be collected
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the stored db information structured as follows::

                {
                    "autarky": <autarky in the period in %>,
                    "bat_power_in": <power entering battery, charging>,
                    "bat_power_out": <power leaving battery, discharging>,
                    "consumed_production": <power directly consumed in %>,
                    "consumption": <self consumed power>,
                    "grid_power_in": <power sent into the grid (production)>,
                    "grid_power_out": <power taken from the grid (consumption)>,
                    "startTimestamp": <timestamp from which db data is fetched of>,
                    "stateOfCharge": <battery charge level in %>,
                    "solarProduction": <power production>,
                    "timespanSeconds": <timespan in seconds of which db data is collected>
                }
        """
        if timespanSeconds == 0:
            return None

        response = self.sendRequest(
            (
                RscpTag.DB_REQ_HISTORY_DATA_DAY,
                RscpType.Container,
                [
                    (
                        RscpTag.DB_REQ_HISTORY_TIME_START,
                        RscpType.Uint64,
                        startTimestamp,
                    ),
                    (
                        RscpTag.DB_REQ_HISTORY_TIME_INTERVAL,
                        RscpType.Uint64,
                        timespanSeconds,
                    ),
                    (
                        RscpTag.DB_REQ_HISTORY_TIME_SPAN,
                        RscpType.Uint64,
                        timespanSeconds,
                    ),
                ],
            ),
            keepAlive=keepAlive,
        )

        outObj = {
            "autarky": rscpFindTagIndex(response[2][0], RscpTag.DB_AUTARKY),
            "bat_power_in": rscpFindTagIndex(response[2][0], RscpTag.DB_BAT_POWER_IN),
            "bat_power_out": rscpFindTagIndex(response[2][0], RscpTag.DB_BAT_POWER_OUT),
            "consumed_production": rscpFindTagIndex(
                response[2][0], RscpTag.DB_CONSUMED_PRODUCTION
            ),
            "consumption": rscpFindTagIndex(response[2][0], RscpTag.DB_CONSUMPTION),
            "grid_power_in": rscpFindTagIndex(response[2][0], RscpTag.DB_GRID_POWER_IN),
            "grid_power_out": rscpFindTagIndex(
                response[2][0], RscpTag.DB_GRID_POWER_OUT
            ),
            "startTimestamp": startTimestamp,
            "stateOfCharge": rscpFindTagIndex(
                response[2][0], RscpTag.DB_BAT_CHARGE_LEVEL
            ),
            "solarProduction": rscpFindTagIndex(response[2][0], RscpTag.DB_DC_POWER),
            "timespanSeconds": timespanSeconds,
        }

        return outObj

    def get_db_data(
        self,
        startDate: datetime.date = datetime.date.today(),
        timespan: Literal["DAY", "MONTH", "YEAR"] = "DAY",
        keepAlive: bool = False,
    ):
        """Reads DB data and summed up values for the given timespan via rscp protocol.

        Args:
            startDate (datetime.date): start date for timespan, default today. Depending on timespan given,
                the startDate is automatically adjusted to the first of the month or the year
            timespan (str): string specifying the time span ["DAY", "MONTH", "YEAR"]
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the stored db information structured as follows::

                {
                    "autarky": <autarky in the period in %>,
                    "bat_power_in": <power entering battery, charging>,
                    "bat_power_out": <power leaving battery, discharging>,
                    "consumed_production": <power directly consumed in %>,
                    "consumption": <self consumed power>,
                    "grid_power_in": <power sent into the grid (production)>,
                    "grid_power_out": <power taken from the grid (consumption)>,
                    "startDate": <date from which db data is fetched of>,
                    "stateOfCharge": <battery charge level in %>,
                    "solarProduction": <power production>,
                    "timespan": <timespan of which db data is collected>,
                    "timespanSeconds": <timespan in seconds of which db data is collected>
                }
        """
        if "YEAR" == timespan:
            requestDate = startDate.replace(day=1, month=1)
            span = 365 * 24 * 60 * 60
        elif "MONTH" == timespan:
            requestDate = startDate.replace(day=1)
            num_days = monthrange(requestDate.year, requestDate.month)[1]
            span = num_days * 24 * 60 * 60
        else:
            requestDate = startDate
            span = 24 * 60 * 60

        startTimestamp = int(time.mktime(requestDate.timetuple()))

        outObj = self.get_db_data_timestamp(
            startTimestamp=startTimestamp, timespanSeconds=span, keepAlive=keepAlive
        )
        if outObj is not None:
            del outObj["startTimestamp"]
            outObj["startDate"] = requestDate
            outObj["timespan"] = timespan
            outObj = {k: v for k, v in sorted(outObj.items())}

        return outObj

    def get_system_info_static(self, keepAlive: bool = False):
        """Polls the static system info via rscp protocol.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive
        """
        self.deratePercent = (
            self.sendRequestTag(RscpTag.EMS_REQ_DERATE_AT_PERCENT_VALUE, keepAlive=True)
            * 100
        )

        self.deratePower = self.sendRequestTag(
            RscpTag.EMS_REQ_DERATE_AT_POWER_VALUE, keepAlive=True
        )
        self.installedPeakPower = self.sendRequestTag(
            RscpTag.EMS_REQ_INSTALLED_PEAK_POWER, keepAlive=True
        )
        self.externalSourceAvailable = self.sendRequestTag(
            RscpTag.EMS_REQ_EXT_SRC_AVAILABLE, keepAlive=True
        )
        self.macAddress = self.sendRequestTag(
            RscpTag.INFO_REQ_MAC_ADDRESS, keepAlive=True
        )
        if (
            not self.serialNumber
        ):  # do not send this for a web connection because it screws up the handshake!
            self._set_serial(
                self.sendRequestTag(RscpTag.INFO_REQ_SERIAL_NUMBER, keepAlive=True)
            )

        sys_specs = self.sendRequestTag(
            RscpTag.EMS_REQ_GET_SYS_SPECS, keepAlive=keepAlive
        )
        for item in sys_specs:
            if (
                rscpFindTagIndex(item, RscpTag.EMS_SYS_SPEC_NAME)
                == "installedBatteryCapacity"
            ):
                self.installedBatteryCapacity = rscpFindTagIndex(
                    item, RscpTag.EMS_SYS_SPEC_VALUE_INT
                )
            elif rscpFindTagIndex(item, RscpTag.EMS_SYS_SPEC_NAME) == "maxAcPower":
                self.maxAcPower = rscpFindTagIndex(item, RscpTag.EMS_SYS_SPEC_VALUE_INT)
            elif (
                rscpFindTagIndex(item, RscpTag.EMS_SYS_SPEC_NAME) == "maxBatChargePower"
            ):
                self.maxBatChargePower = rscpFindTagIndex(
                    item, RscpTag.EMS_SYS_SPEC_VALUE_INT
                )
            elif (
                rscpFindTagIndex(item, RscpTag.EMS_SYS_SPEC_NAME)
                == "maxBatDischargPower"
            ):
                self.maxBatDischargePower = rscpFindTagIndex(
                    item, RscpTag.EMS_SYS_SPEC_VALUE_INT
                )
            elif (
                rscpFindTagIndex(item, RscpTag.EMS_SYS_SPEC_NAME)
                == "startDischargeDefault"
            ):
                self.startDischargeDefault = rscpFindTagIndex(
                    item, RscpTag.EMS_SYS_SPEC_VALUE_INT
                )

        # EMS_REQ_SPECIFICATION_VALUES

        return True

    def get_system_info(self, keepAlive: bool = False):
        """Polls the system info via rscp protocol.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the system info structured as follows::

                {
                    "deratePercent": <% of installed peak power the feed in will be derated>,
                    "deratePower": <W at which the feed in will be derated>,
                    "externalSourceAvailable": <wether an additional power meter is installed>,
                    "installedBatteryCapacity": <installed Battery Capacity in W>,
                    "installedPeakPower": <installed peak power in W>,
                    "maxAcPower": <max AC power>,
                    "macAddress": <the mac address>,
                    "maxBatChargePower": <max Battery charge power>,
                    "maxBatDischargePower": <max Battery discharge power>,
                    "model": <model connected to>,
                    "release": <release version>,
                    "serial": <serial number of the system>
                }
        """
        # use keepAlive setting for last request
        sw = self.sendRequestTag(RscpTag.INFO_REQ_SW_RELEASE, keepAlive=keepAlive)

        # EMS_EMERGENCY_POWER_STATUS

        outObj = {
            "deratePercent": self.deratePercent,
            "deratePower": self.deratePower,
            "externalSourceAvailable": self.externalSourceAvailable,
            "installedBatteryCapacity": self.installedBatteryCapacity,
            "installedPeakPower": self.installedPeakPower,
            "maxAcPower": self.maxAcPower,
            "macAddress": self.macAddress,
            "maxBatChargePower": self.maxBatChargePower,
            "maxBatDischargePower": self.maxBatDischargePower,
            "model": self.model,
            "release": sw,
            "serial": self.serialNumber,
        }
        return outObj

    def get_system_status(self, keepAlive: bool = False):
        """Polls the system status via rscp protocol.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the system status structured as follows::

                {
                    "dcdcAlive": <dcdc alive>,
                    "powerMeterAlive": <power meter alive>,
                    "batteryModuleAlive": <battery module alive>,
                    "pvModuleAlive": <pv module alive>,
                    "pvInverterInited": <pv inverter inited>,
                    "serverConnectionAlive": <server connection alive>,
                    "pvDerated": <pv derated due to deratePower limit reached>,
                    "emsAlive": <emd alive>,
                    "acModeBlocked": <ad mode blocked>,
                    "sysConfChecked": <sys conf checked>,
                    "emergencyPowerStarted": <emergency power started>,
                    "emergencyPowerOverride": <emergency power override>,
                    "wallBoxAlive": <wall box alive>,
                    "powerSaveEnabled": <power save enabled>,
                    "chargeIdlePeriodActive": <charge idle period active>,
                    "dischargeIdlePeriodActive": <discharge idle period active>,
                    "waitForWeatherBreakthrough": <wait for weather breakthrouhgh>,
                    "rescueBatteryEnabled": <rescue battery enabled>,
                    "emergencyReserveReached": <emergencey reserve reached>,
                    "socSyncRequested": <soc sync requested>
                }
        """
        # use keepAlive setting for last request
        sw = self.sendRequestTag(RscpTag.EMS_REQ_SYS_STATUS, keepAlive=keepAlive)
        SystemStatusBools = [bool(int(i)) for i in reversed(list(f"{sw:022b}"))]

        outObj = {
            "dcdcAlive": 0,
            "powerMeterAlive": 1,
            "batteryModuleAlive": 2,
            "pvModuleAlive": 3,
            "pvInverterInited": 4,
            "serverConnectionAlive": 5,
            "pvDerated": 6,
            "emsAlive": 7,
            # "acCouplingMode:2;              // 8-9
            "acModeBlocked": 10,
            "sysConfChecked": 11,
            "emergencyPowerStarted": 12,
            "emergencyPowerOverride": 13,
            "wallBoxAlive": 14,
            "powerSaveEnabled": 15,
            "chargeIdlePeriodActive": 16,
            "dischargeIdlePeriodActive": 17,
            "waitForWeatherBreakthrough": 18,  # this status bit shows if weather regulated charge is active and the system is waiting for the sun power breakthrough. (PV power > derating power)
            "rescueBatteryEnabled": 19,
            "emergencyReserveReached": 20,
            "socSyncRequested": 21,
        }
        outObj = {k: SystemStatusBools[v] for k, v in outObj.items()}
        return outObj

    def get_batteries(self, keepAlive: bool = False):
        """Scans for installed batteries via rscp protocol.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive
        Returns:
            list[dict]: List containing the found batteries as follows.:
                [
                    {'index': 0, "dcbs": 3}
                ]
        """
        maxBatteries = 8
        outObj = []
        for batIndex in range(maxBatteries):
            try:
                req = self.sendRequest(
                    (
                        RscpTag.BAT_REQ_DATA,
                        RscpType.Container,
                        [
                            (RscpTag.BAT_INDEX, RscpType.Uint16, batIndex),
                            (RscpTag.BAT_REQ_DCB_COUNT, RscpType.NoneType, None),
                        ],
                    ),
                    keepAlive=True if batIndex < (maxBatteries - 1) else keepAlive,
                )
            except NotAvailableError:
                continue

            dcbCount = rscpFindTagIndex(req, RscpTag.BAT_DCB_COUNT)

            if dcbCount is not None:
                outObj.append(
                    {
                        "index": batIndex,
                        "dcbs": dcbCount,
                    }
                )

        return outObj

    def get_battery_data(
        self,
        batIndex: int | None = None,
        dcbs: List[int] | None = None,
        keepAlive: bool = False,
    ):
        """Polls the battery data via rscp protocol.

        Args:
            batIndex (Optional[int]): battery index
            dcbs (Optional[list]): dcb list
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the battery data structured as follows::

                {
                    "asoc": <absolute state of charge>,
                    "chargeCycles": <charge cycles>,
                    "current": <current>,
                    "dcbCount": <dcb count>,
                    "dcbs": {0:
                        {
                            "current": <current>,
                            "currentAvg30s": <current average 30s>,
                            "cycleCount": <cycle count>,
                            "designCapacity": <design capacity>,
                            "designVoltage": <design voltage>,
                            "deviceName": <device name>,
                            "endOfDischarge": <end of discharge>,
                            "error": <error>,
                            "fullChargeCapacity": <full charge capacity>,
                            "fwVersion": <firmware version>,
                            "manufactureDate": <manufacture date>,
                            "manufactureName": <manufacture name>,
                            "maxChargeCurrent": <max charge current>,
                            "maxChargeTemperature": <max charge temperature>,
                            "maxChargeVoltage": <max charge voltage>,
                            "maxDischargeCurrent": <max discharge current>,
                            "minChargeTemperature": <min charge temperature>,
                            "parallelCellCount": <parallel cell count>,
                            "sensorCount": <sensor countt>,
                            "seriesCellCount": <cells in series count>,
                            "pcbVersion": <pcb version>,
                            "protocolVersion": <protocol version>,
                            "remainingCapacity": <remaining capacity>,
                            "serialCode": <serial code>,
                            "serialNo": <serial no>,
                            "soc": <state of charge>,
                            "soh": <state of health>,
                            "status": <status>,
                            "temperatures": <temperatures>,
                            "voltage": <voltage>,
                            "voltageAvg30s": <voltage average 30s>,
                            "voltages": <voltages>,
                            "warning": <warning>
                        }
                    },
                    "designCapacity": <design capacity>,
                    "deviceConnected": <device connected>,
                    "deviceInService": <device in service>,
                    "deviceName": <device name>,
                    "deviceWorking": <device working>,
                    "eodVoltage": <eod voltage>,
                    "errorCode": <error code>,
                    "fcc": <full charge capacity>,
                    "index": <batIndex>,
                    "maxBatVoltage": <max battery voltage>,
                    "maxChargeCurrent": <max charge current>,
                    "maxDischargeCurrent": <max discharge current>,
                    "maxDcbCellTemp": <max DCB cell temp>,
                    "minDcbCellTemp": <min DCB cell temp>,
                    "moduleVoltage": <module voltage>,
                    "rc": <rc>,
                    "readyForShutdown": <ready for shutdown>,
                    "rsoc": <relative state of charge>,
                    "rsocReal": <real relative state of charge>,
                    "statusCode": <status code>,
                    "terminalVoltage": <terminal voltage>,
                    "totalUseTime": <total use time>,
                    "totalDischargeTime": <total discharge time>,
                    "trainingMode": <training mode>,
                    "usuableCapacity": <usuable capacity>
                    "usuableRemainingCapacity": <usuable remaining capacity>
                }
        """
        if batIndex is None:
            batIndex = self.batteries[0]["index"]

        req = self.sendRequest(
            (
                RscpTag.BAT_REQ_DATA,
                RscpType.Container,
                [
                    (RscpTag.BAT_INDEX, RscpType.Uint16, batIndex),
                    (RscpTag.BAT_REQ_ASOC, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_CHARGE_CYCLES, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_CURRENT, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_DCB_COUNT, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_DESIGN_CAPACITY, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_DEVICE_NAME, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_DEVICE_STATE, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_EOD_VOLTAGE, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_ERROR_CODE, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_FCC, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_MAX_BAT_VOLTAGE, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_MAX_CHARGE_CURRENT, RscpType.NoneType, None),
                    (
                        RscpTag.BAT_REQ_MAX_DISCHARGE_CURRENT,
                        RscpType.NoneType,
                        None,
                    ),
                    (
                        RscpTag.BAT_REQ_MAX_DCB_CELL_TEMPERATURE,
                        RscpType.NoneType,
                        None,
                    ),
                    (
                        RscpTag.BAT_REQ_MIN_DCB_CELL_TEMPERATURE,
                        RscpType.NoneType,
                        None,
                    ),
                    (RscpTag.BAT_REQ_INTERNALS, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_MODULE_VOLTAGE, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_RC, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_READY_FOR_SHUTDOWN, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_RSOC, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_RSOC_REAL, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_STATUS_CODE, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_TERMINAL_VOLTAGE, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_TOTAL_USE_TIME, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_TOTAL_DISCHARGE_TIME, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_TRAINING_MODE, RscpType.NoneType, None),
                    (RscpTag.BAT_REQ_USABLE_CAPACITY, RscpType.NoneType, None),
                    (
                        RscpTag.BAT_REQ_USABLE_REMAINING_CAPACITY,
                        RscpType.NoneType,
                        None,
                    ),
                ],
            ),
            keepAlive=True,
        )

        dcbCount = rscpFindTagIndex(req, RscpTag.BAT_DCB_COUNT)
        deviceStateContainer = rscpFindTag(req, RscpTag.BAT_DEVICE_STATE)

        outObj = {
            "asoc": rscpFindTagIndex(req, RscpTag.BAT_ASOC),
            "chargeCycles": rscpFindTagIndex(req, RscpTag.BAT_CHARGE_CYCLES),
            "current": rscpFindTagIndex(req, RscpTag.BAT_CURRENT),
            "dcbCount": dcbCount,
            "dcbs": {},
            "designCapacity": rscpFindTagIndex(req, RscpTag.BAT_DESIGN_CAPACITY),
            "deviceConnected": rscpFindTagIndex(
                deviceStateContainer, RscpTag.BAT_DEVICE_CONNECTED
            ),
            "deviceInService": rscpFindTagIndex(
                deviceStateContainer, RscpTag.BAT_DEVICE_IN_SERVICE
            ),
            "deviceName": rscpFindTagIndex(req, RscpTag.BAT_DEVICE_NAME),
            "deviceWorking": rscpFindTagIndex(
                deviceStateContainer, RscpTag.BAT_DEVICE_WORKING
            ),
            "eodVoltage": rscpFindTagIndex(req, RscpTag.BAT_EOD_VOLTAGE),
            "errorCode": rscpFindTagIndex(req, RscpTag.BAT_ERROR_CODE),
            "fcc": rscpFindTagIndex(req, RscpTag.BAT_FCC),
            "index": batIndex,
            "maxBatVoltage": rscpFindTagIndex(req, RscpTag.BAT_MAX_BAT_VOLTAGE),
            "maxChargeCurrent": rscpFindTagIndex(req, RscpTag.BAT_MAX_CHARGE_CURRENT),
            "maxDischargeCurrent": rscpFindTagIndex(
                req, RscpTag.BAT_MAX_DISCHARGE_CURRENT
            ),
            "maxDcbCellTemp": rscpFindTagIndex(
                req, RscpTag.BAT_MAX_DCB_CELL_TEMPERATURE
            ),
            "minDcbCellTemp": rscpFindTagIndex(
                req, RscpTag.BAT_MIN_DCB_CELL_TEMPERATURE
            ),
            "moduleVoltage": rscpFindTagIndex(req, RscpTag.BAT_MODULE_VOLTAGE),
            "rc": rscpFindTagIndex(req, RscpTag.BAT_RC),
            "readyForShutdown": rscpFindTagIndex(req, RscpTag.BAT_READY_FOR_SHUTDOWN),
            "rsoc": rscpFindTagIndex(req, RscpTag.BAT_RSOC),
            "rsocReal": rscpFindTagIndex(req, RscpTag.BAT_RSOC_REAL),
            "statusCode": rscpFindTagIndex(req, RscpTag.BAT_STATUS_CODE),
            "terminalVoltage": rscpFindTagIndex(req, RscpTag.BAT_TERMINAL_VOLTAGE),
            "totalUseTime": rscpFindTagIndex(req, RscpTag.BAT_TOTAL_USE_TIME),
            "totalDischargeTime": rscpFindTagIndex(
                req, RscpTag.BAT_TOTAL_DISCHARGE_TIME
            ),
            "trainingMode": rscpFindTagIndex(req, RscpTag.BAT_TRAINING_MODE),
            "usuableCapacity": rscpFindTagIndex(req, RscpTag.BAT_USABLE_CAPACITY),
            "usuableRemainingCapacity": rscpFindTagIndex(
                req, RscpTag.BAT_USABLE_REMAINING_CAPACITY
            ),
        }

        if dcbs is None:
            dcbs = list(range(0, dcbCount))

        for dcb in dcbs:
            req = self.sendRequest(
                (
                    RscpTag.BAT_REQ_DATA,
                    RscpType.Container,
                    [
                        (RscpTag.BAT_INDEX, RscpType.Uint16, batIndex),
                        (
                            RscpTag.BAT_REQ_DCB_ALL_CELL_TEMPERATURES,
                            RscpType.Uint16,
                            dcb,
                        ),
                        (
                            RscpTag.BAT_REQ_DCB_ALL_CELL_VOLTAGES,
                            RscpType.Uint16,
                            dcb,
                        ),
                        (RscpTag.BAT_REQ_DCB_INFO, RscpType.Uint16, dcb),
                    ],
                ),
                keepAlive=True
                if dcb != dcbs[-1]
                else keepAlive,  # last request should honor keepAlive
            )

            info = rscpFindTag(req, RscpTag.BAT_DCB_INFO)
            # For some devices, no info for the DCBs exists. Skip those.
            if info is None or len(info) < 3 or info[1] == "Error":
                continue

            # Initialize default values for DCB
            sensorCount = 0
            temperatures = []
            seriesCellCount = 0
            voltages = []

            # Set temperatures, if available for the device
            temperatures_raw = rscpFindTag(req, RscpTag.BAT_DCB_ALL_CELL_TEMPERATURES)
            if (
                temperatures_raw is not None
                and len(temperatures_raw) == 3
                and temperatures_raw[1] != "Error"
            ):
                temperatures_data = rscpFindTagIndex(temperatures_raw, RscpTag.BAT_DATA)
                sensorCount = rscpFindTagIndex(info, RscpTag.BAT_DCB_NR_SENSOR)
                for sensor in range(0, sensorCount):
                    temperatures.append(temperatures_data[sensor][2])

            # Set voltages, if available for the device
            voltages_raw = rscpFindTag(req, RscpTag.BAT_DCB_ALL_CELL_VOLTAGES)
            if (
                voltages_raw is not None
                and len(voltages_raw) == 3
                and voltages_raw[1] != "Error"
            ):
                voltages_data = rscpFindTagIndex(voltages_raw, RscpTag.BAT_DATA)
                seriesCellCount = rscpFindTagIndex(info, RscpTag.BAT_DCB_NR_SERIES_CELL)
                for cell in range(0, seriesCellCount):
                    voltages.append(voltages_data[cell][2])

            dcbobj = {
                "current": rscpFindTagIndex(info, RscpTag.BAT_DCB_CURRENT),
                "currentAvg30s": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_CURRENT_AVG_30S
                ),
                "cycleCount": rscpFindTagIndex(info, RscpTag.BAT_DCB_CYCLE_COUNT),
                "designCapacity": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_DESIGN_CAPACITY
                ),
                "designVoltage": rscpFindTagIndex(info, RscpTag.BAT_DCB_DESIGN_VOLTAGE),
                "deviceName": rscpFindTagIndex(info, RscpTag.BAT_DCB_DEVICE_NAME),
                "endOfDischarge": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_END_OF_DISCHARGE
                ),
                "error": rscpFindTagIndex(info, RscpTag.BAT_DCB_ERROR),
                "fullChargeCapacity": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_FULL_CHARGE_CAPACITY
                ),
                "fwVersion": rscpFindTagIndex(info, RscpTag.BAT_DCB_FW_VERSION),
                "manufactureDate": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_MANUFACTURE_DATE
                ),
                "manufactureName": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_MANUFACTURE_NAME
                ),
                "maxChargeCurrent": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_MAX_CHARGE_CURRENT
                ),
                "maxChargeTemperature": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_CHARGE_HIGH_TEMPERATURE
                ),
                "maxChargeVoltage": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_MAX_CHARGE_VOLTAGE
                ),
                "maxDischargeCurrent": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_MAX_DISCHARGE_CURRENT
                ),
                "minChargeTemperature": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_CHARGE_LOW_TEMPERATURE
                ),
                "parallelCellCount": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_NR_PARALLEL_CELL
                ),
                "sensorCount": sensorCount,
                "seriesCellCount": seriesCellCount,
                "pcbVersion": rscpFindTagIndex(info, RscpTag.BAT_DCB_PCB_VERSION),
                "protocolVersion": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_PROTOCOL_VERSION
                ),
                "remainingCapacity": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_REMAINING_CAPACITY
                ),
                "serialCode": rscpFindTagIndex(info, RscpTag.BAT_DCB_SERIALCODE),
                "serialNo": rscpFindTagIndex(info, RscpTag.BAT_DCB_SERIALNO),
                "soc": rscpFindTagIndex(info, RscpTag.BAT_DCB_SOC),
                "soh": rscpFindTagIndex(info, RscpTag.BAT_DCB_SOH),
                "status": rscpFindTagIndex(info, RscpTag.BAT_DCB_STATUS),
                "temperatures": temperatures,
                "voltage": rscpFindTagIndex(info, RscpTag.BAT_DCB_VOLTAGE),
                "voltageAvg30s": rscpFindTagIndex(
                    info, RscpTag.BAT_DCB_VOLTAGE_AVG_30S
                ),
                "voltages": voltages,
                "warning": rscpFindTagIndex(info, RscpTag.BAT_DCB_WARNING),
            }
            outObj["dcbs"].update({dcb: dcbobj})  # type: ignore
        return outObj

    def get_batteries_data(
        self, batteries: List[Dict[str, Any]] | None = None, keepAlive: bool = False
    ):
        """Polls the batteries data via rscp protocol.

        Args:
            batteries (Optional[dict]): batteries dict
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            list[dict]: Returns a list of batteries data
        """
        if batteries is None:
            batteries = self.batteries

        outObj = []

        for battery in batteries:
            if "dcbs" in battery:
                dcbs = list(range(0, battery["dcbs"]))
            else:
                dcbs = None
            outObj.append(
                self.get_battery_data(
                    batIndex=battery["index"],
                    dcbs=dcbs,
                    keepAlive=True
                    if battery["index"] != batteries[-1]["index"]
                    else keepAlive,  # last request should honor keepAlive
                )
            )

        return outObj

    def get_pvis(self, keepAlive: bool = False):
        """Scans for installed pvis via rscp protocol.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive
        Returns:
            list[dict]: List containing the found pvis as follows.::
                [
                    {'index': 0, "phases": 3, "strings": 2, 'type': 3, 'typeName': 'PVI_TYPE_E3DC_E'}
                ]
        """
        maxPvis = 8
        outObj = []
        for pviIndex in range(maxPvis):
            req = self.sendRequest(
                (
                    RscpTag.PVI_REQ_DATA,
                    "Container",
                    [
                        (RscpTag.PVI_INDEX, RscpType.Uint16, pviIndex),
                        (RscpTag.PVI_REQ_TYPE, RscpType.NoneType, None),
                        (RscpTag.PVI_REQ_USED_STRING_COUNT, RscpType.NoneType, None),
                        (RscpTag.PVI_REQ_AC_MAX_PHASE_COUNT, RscpType.NoneType, None),
                    ],
                ),
                keepAlive=True if pviIndex < (maxPvis - 1) else keepAlive,
            )

            pviType = rscpFindTagIndex(req, RscpTag.PVI_TYPE)

            if pviType is not None:
                maxPhaseCount = int(
                    rscpFindTagIndex(req, RscpTag.PVI_AC_MAX_PHASE_COUNT)
                )
                usedStringCount = int(
                    rscpFindTagIndex(req, RscpTag.PVI_USED_STRING_COUNT)
                )
                outObj.append(
                    {
                        "index": pviIndex,
                        "phases": maxPhaseCount,
                        "strings": usedStringCount,
                        "type": pviType,
                        "typeName": getStrPviType(pviType),
                    }
                )

        return outObj

    def get_pvi_data(
        self,
        pviIndex: int | None = None,
        strings: List[int] | None = None,
        phases: List[int] | None = None,
        keepAlive: bool = False,
    ):
        """Polls the inverter data via rscp protocol.

        Args:
            pviIndex (int): pv inverter index
            strings (Optional[list]): string list
            phases (Optional[list]): phase list
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the pvi data structured as follows::

                {
                    "acMaxApparentPower": <max apparent AC power>,
                    "cosPhi": {
                        "active": <active>,
                        "value": <value>,
                        "excited": <excited>
                    },
                    "deviceState": {
                        "connected": <connected>,
                        "working": <working>,
                        "inService": <in service>
                    },
                    "frequency": {
                        "under": <frequency under>,
                        "over": <frequency over>
                    },
                    "index": <pviIndex>,
                    "lastError": <last error>,
                    "maxPhaseCount": <max phase count>,
                    "maxStringCount": <max string count>,
                    "onGrid": <on grid>,
                    "phases": { 0:
                        {
                            "power": <power>,
                            "voltage": <voltage>,
                            "current": <current>,
                            "apparentPower": <apparent power>,
                            "reactivePower": <reactive power>,
                            "energyAll": <energy all>,
                            "energyGridConsumption": <energy grid consumption>
                        }
                    },
                    "powerMode": <power mode>,
                    "serialNumber": <serial number>,
                    "state": <state>,
                    "strings": { 0:
                        {
                            "power": <power>,
                            "voltage": <voltage>,
                            "current": <current>,
                            "energyAll": <energy all>
                        }
                    },
                    "systemMode": <system mode>,
                    "temperature": {
                        "max": <max temperature>,
                        "min": <min temperature>,
                        "values": [<value>,<value>],
                    },
                    "type": <type>,
                    "version": <version>,
                    "voltageMonitoring": {
                        "thresholdTop": <voltage threshold top>,
                        "thresholdBottom": <voltage threshold bottom>,
                        "slopeUp": <voltage slope up>,
                        "slopeDown": <voltage slope down>,
                    }
                }
        """
        if pviIndex is None:
            pviIndex = self.pvis[0]["index"]
            if phases is None and "phases" in self.pvis[0]:
                phases = list(range(0, self.pvis[0]["phases"]))

        req = self.sendRequest(
            (
                RscpTag.PVI_REQ_DATA,
                RscpType.Container,
                [
                    (RscpTag.PVI_INDEX, RscpType.Uint16, pviIndex),
                    (RscpTag.PVI_REQ_AC_MAX_PHASE_COUNT, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_TEMPERATURE_COUNT, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_DC_MAX_STRING_COUNT, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_USED_STRING_COUNT, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_TYPE, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_SERIAL_NUMBER, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_VERSION, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_ON_GRID, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_STATE, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_LAST_ERROR, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_COS_PHI, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_VOLTAGE_MONITORING, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_POWER_MODE, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_SYSTEM_MODE, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_FREQUENCY_UNDER_OVER, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_MAX_TEMPERATURE, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_MIN_TEMPERATURE, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_AC_MAX_APPARENTPOWER, RscpType.NoneType, None),
                    (RscpTag.PVI_REQ_DEVICE_STATE, RscpType.NoneType, None),
                ],
            ),
            keepAlive=True,
        )

        maxPhaseCount = int(rscpFindTagIndex(req, RscpTag.PVI_AC_MAX_PHASE_COUNT))
        maxStringCount = int(rscpFindTagIndex(req, RscpTag.PVI_DC_MAX_STRING_COUNT))
        usedStringCount = int(rscpFindTagIndex(req, RscpTag.PVI_USED_STRING_COUNT))

        voltageMonitoring = rscpFindTag(req, RscpTag.PVI_VOLTAGE_MONITORING)
        cosPhi = rscpFindTag(req, RscpTag.PVI_COS_PHI)
        frequency = rscpFindTag(req, RscpTag.PVI_FREQUENCY_UNDER_OVER)
        deviceState = rscpFindTag(req, RscpTag.PVI_DEVICE_STATE)

        outObj = {
            "acMaxApparentPower": rscpFindTagIndex(
                rscpFindTag(req, RscpTag.PVI_AC_MAX_APPARENTPOWER), RscpTag.PVI_VALUE
            ),
            "cosPhi": {
                "active": rscpFindTagIndex(cosPhi, RscpTag.PVI_COS_PHI_IS_AKTIV),
                "value": rscpFindTagIndex(cosPhi, RscpTag.PVI_COS_PHI_VALUE),
                "excited": rscpFindTagIndex(cosPhi, RscpTag.PVI_COS_PHI_EXCITED),
            },
            "deviceState": {
                "connected": rscpFindTagIndex(
                    deviceState, RscpTag.PVI_DEVICE_CONNECTED
                ),
                "working": rscpFindTagIndex(deviceState, RscpTag.PVI_DEVICE_WORKING),
                "inService": rscpFindTagIndex(
                    deviceState, RscpTag.PVI_DEVICE_IN_SERVICE
                ),
            },
            "frequency": {
                "under": rscpFindTagIndex(frequency, RscpTag.PVI_FREQUENCY_UNDER),
                "over": rscpFindTagIndex(frequency, RscpTag.PVI_FREQUENCY_OVER),
            },
            "index": pviIndex,
            "lastError": rscpFindTagIndex(req, RscpTag.PVI_LAST_ERROR),
            "maxPhaseCount": maxPhaseCount,
            "maxStringCount": maxStringCount,
            "onGrid": rscpFindTagIndex(req, RscpTag.PVI_ON_GRID),
            "phases": {},
            "powerMode": rscpFindTagIndex(req, RscpTag.PVI_POWER_MODE),
            "serialNumber": rscpFindTagIndex(req, RscpTag.PVI_SERIAL_NUMBER),
            "state": rscpFindTagIndex(req, RscpTag.PVI_STATE),
            "strings": {},
            "systemMode": rscpFindTagIndex(req, RscpTag.PVI_SYSTEM_MODE),
            "temperature": {
                "max": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_MAX_TEMPERATURE), RscpTag.PVI_VALUE
                ),
                "min": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_MIN_TEMPERATURE), RscpTag.PVI_VALUE
                ),
                "values": [],
            },
            "type": rscpFindTagIndex(req, RscpTag.PVI_TYPE),
            "version": rscpFindTagIndex(
                rscpFindTag(req, RscpTag.PVI_VERSION), RscpTag.PVI_VERSION_MAIN
            ),
            "voltageMonitoring": {
                "thresholdTop": rscpFindTagIndex(
                    voltageMonitoring, RscpTag.PVI_VOLTAGE_MONITORING_THRESHOLD_TOP
                ),
                "thresholdBottom": rscpFindTagIndex(
                    voltageMonitoring, RscpTag.PVI_VOLTAGE_MONITORING_THRESHOLD_BOTTOM
                ),
                "slopeUp": rscpFindTagIndex(
                    voltageMonitoring, RscpTag.PVI_VOLTAGE_MONITORING_SLOPE_UP
                ),
                "slopeDown": rscpFindTagIndex(
                    voltageMonitoring, RscpTag.PVI_VOLTAGE_MONITORING_SLOPE_DOWN
                ),
            },
        }

        temperatures = range(
            0, int(rscpFindTagIndex(req, RscpTag.PVI_TEMPERATURE_COUNT))
        )
        for temperature in temperatures:
            req = self.sendRequest(
                (
                    RscpTag.PVI_REQ_DATA,
                    RscpType.Container,
                    [
                        (RscpTag.PVI_INDEX, RscpType.Uint16, pviIndex),
                        (RscpTag.PVI_REQ_TEMPERATURE, RscpType.Uint16, temperature),
                    ],
                ),
                keepAlive=True,
            )
            outObj["temperature"]["values"].append(  # type: ignore
                rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_TEMPERATURE), RscpTag.PVI_VALUE
                )
            )

        if phases is None:
            phases = list(range(0, maxPhaseCount))

        for phase in phases:
            req = self.sendRequest(
                (
                    RscpTag.PVI_REQ_DATA,
                    RscpType.Container,
                    [
                        (RscpTag.PVI_INDEX, RscpType.Uint16, pviIndex),
                        (RscpTag.PVI_REQ_AC_POWER, RscpType.Uint16, phase),
                        (RscpTag.PVI_REQ_AC_VOLTAGE, RscpType.Uint16, phase),
                        (RscpTag.PVI_REQ_AC_CURRENT, RscpType.Uint16, phase),
                        (RscpTag.PVI_REQ_AC_APPARENTPOWER, RscpType.Uint16, phase),
                        (RscpTag.PVI_REQ_AC_REACTIVEPOWER, RscpType.Uint16, phase),
                        (RscpTag.PVI_REQ_AC_ENERGY_ALL, RscpType.Uint16, phase),
                        (
                            RscpTag.PVI_REQ_AC_ENERGY_GRID_CONSUMPTION,
                            RscpType.Uint16,
                            phase,
                        ),
                    ],
                ),
                keepAlive=True,
            )
            phaseobj = {
                "power": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_AC_POWER), RscpTag.PVI_VALUE
                ),
                "voltage": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_AC_VOLTAGE), RscpTag.PVI_VALUE
                ),
                "current": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_AC_CURRENT), RscpTag.PVI_VALUE
                ),
                "apparentPower": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_AC_APPARENTPOWER),
                    RscpTag.PVI_VALUE,
                ),
                "reactivePower": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_AC_REACTIVEPOWER),
                    RscpTag.PVI_VALUE,
                ),
                "energyAll": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_AC_ENERGY_ALL), RscpTag.PVI_VALUE
                ),
                "energyGridConsumption": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_AC_ENERGY_GRID_CONSUMPTION),
                    RscpTag.PVI_VALUE,
                ),
            }
            outObj["phases"].update({phase: phaseobj})  # type: ignore

        if strings is None:
            strings = list(range(0, usedStringCount))

        for string in strings:
            req = self.sendRequest(
                (
                    RscpTag.PVI_REQ_DATA,
                    RscpType.Container,
                    [
                        (RscpTag.PVI_INDEX, RscpType.Uint16, pviIndex),
                        (RscpTag.PVI_REQ_DC_POWER, RscpType.Uint16, string),
                        (RscpTag.PVI_REQ_DC_VOLTAGE, RscpType.Uint16, string),
                        (RscpTag.PVI_REQ_DC_CURRENT, RscpType.Uint16, string),
                        (
                            RscpTag.PVI_REQ_DC_STRING_ENERGY_ALL,
                            RscpType.Uint16,
                            string,
                        ),
                    ],
                ),
                keepAlive=True
                if string != strings[-1]
                else keepAlive,  # last request should honor keepAlive
            )
            stringobj = {
                "power": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_DC_POWER), RscpTag.PVI_VALUE
                ),
                "voltage": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_DC_VOLTAGE), RscpTag.PVI_VALUE
                ),
                "current": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_DC_CURRENT), RscpTag.PVI_VALUE
                ),
                "energyAll": rscpFindTagIndex(
                    rscpFindTag(req, RscpTag.PVI_DC_STRING_ENERGY_ALL),
                    RscpTag.PVI_VALUE,
                ),
            }
            outObj["strings"].update({string: stringobj})  # type: ignore
        return outObj

    def get_pvis_data(
        self, pvis: List[Dict[str, Any]] | None = None, keepAlive: bool = False
    ):
        """Polls the inverters data via rscp protocol.

        Args:
            pvis (Optional[dict]): pvis dict
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            list[dict]: Returns a list of pvi data
        """
        if pvis is None:
            pvis = self.pvis

        outObj = []

        for pvi in pvis:
            if "strings" in pvi:
                strings = list(range(0, pvi["strings"]))
            else:
                strings = None

            if "phases" in pvi:
                phases = list(range(0, pvi["phases"]))
            else:
                phases = None

            outObj.append(
                self.get_pvi_data(
                    pviIndex=pvi["index"],
                    strings=strings,
                    phases=phases,
                    keepAlive=True
                    if pvi["index"] != pvis[-1]["index"]
                    else keepAlive,  # last request should honor keepAlive
                )
            )

        return outObj

    def get_powermeters(self, keepAlive: bool = False):
        """Scans for installed power meters via rscp protocol.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            list[dict]: List containing the found powermeters as follows.::

                [
                    {'index': 0, 'type': 1, 'typeName': 'PM_TYPE_ROOT'},
                    {'index': 1, 'type': 4, 'typeName': 'PM_TYPE_ADDITIONAL_CONSUMPTION'}
                ]
        """
        maxPowermeters = 8
        outObj = []
        for pmIndex in range(
            maxPowermeters
        ):  # max 8 powermeters according to E3DC spec
            req = self.sendRequest(
                (
                    RscpTag.PM_REQ_DATA,
                    RscpType.Container,
                    [
                        (RscpTag.PM_INDEX, RscpType.Uint16, pmIndex),
                        (RscpTag.PM_REQ_TYPE, RscpType.NoneType, None),
                    ],
                ),
                keepAlive=True if pmIndex < (maxPowermeters - 1) else keepAlive,
            )

            pmType = rscpFindTagIndex(req, RscpTag.PM_TYPE)

            if pmType is not None:
                outObj.append(
                    {
                        "index": pmIndex,
                        "type": pmType,
                        "typeName": getStrPowermeterType(pmType),
                    }
                )

        return outObj

    def get_powermeter_data(self, pmIndex: int | None = None, keepAlive: bool = False):
        """Polls the power meter data via rscp protocol.

        Args:
            pmIndex (Optional[int]): power meter index
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the power data structured as follows::

                {
                    "activePhases": <active phases>,
                    "energy": {
                        "L1": <L1 energy>,
                        "L2": <L2 energy>,
                        "L3": <L3 energy>
                    },
                    "index": <pm index>,
                    "maxPhasePower": <max phase power>,
                    "mode": <mode>,
                    "power": {
                        "L1": <L1 power>,
                        "L2": <L2 power>,
                        "L3": <L3 power>
                    },
                    "type": <type>,
                    "voltage": {
                        "L1": <L1 voltage>,
                        "L2": <L1 voltage>,
                        "L3": <L1 voltage>
                    }
                }
        """
        if pmIndex is None:
            pmIndex = self.powermeters[0]["index"]

        res = self.sendRequest(
            (
                RscpTag.PM_REQ_DATA,
                RscpType.Container,
                [
                    (RscpTag.PM_INDEX, RscpType.Uint16, pmIndex),
                    (RscpTag.PM_REQ_POWER_L1, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_POWER_L2, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_POWER_L3, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_VOLTAGE_L1, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_VOLTAGE_L2, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_VOLTAGE_L3, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_ENERGY_L1, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_ENERGY_L2, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_ENERGY_L3, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_MAX_PHASE_POWER, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_ACTIVE_PHASES, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_TYPE, RscpType.NoneType, None),
                    (RscpTag.PM_REQ_MODE, RscpType.NoneType, None),
                ],
            ),
            keepAlive=keepAlive,
        )

        activePhasesChar = rscpFindTagIndex(res, RscpTag.PM_ACTIVE_PHASES)
        activePhases = f"{activePhasesChar:03b}"

        outObj = {
            "activePhases": activePhases,
            "energy": {
                "L1": rscpFindTagIndex(res, RscpTag.PM_ENERGY_L1),
                "L2": rscpFindTagIndex(res, RscpTag.PM_ENERGY_L2),
                "L3": rscpFindTagIndex(res, RscpTag.PM_ENERGY_L3),
            },
            "index": pmIndex,
            "maxPhasePower": rscpFindTagIndex(res, RscpTag.PM_MAX_PHASE_POWER),
            "mode": rscpFindTagIndex(res, RscpTag.PM_MODE),
            "power": {
                "L1": rscpFindTagIndex(res, RscpTag.PM_POWER_L1),
                "L2": rscpFindTagIndex(res, RscpTag.PM_POWER_L2),
                "L3": rscpFindTagIndex(res, RscpTag.PM_POWER_L3),
            },
            "type": rscpFindTagIndex(res, RscpTag.PM_TYPE),
            "voltage": {
                "L1": rscpFindTagIndex(res, RscpTag.PM_VOLTAGE_L1),
                "L2": rscpFindTagIndex(res, RscpTag.PM_VOLTAGE_L2),
                "L3": rscpFindTagIndex(res, RscpTag.PM_VOLTAGE_L3),
            },
        }
        return outObj

    def get_powermeters_data(
        self, powermeters: List[Dict[str, Any]] | None = None, keepAlive: bool = False
    ):
        """Polls the powermeters data via rscp protocol.

        Args:
            powermeters (Optional[dict]): powermeters dict
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            list[dict]: Returns a list of powermeters data
        """
        if powermeters is None:
            powermeters = self.powermeters

        outObj = []

        for powermeter in powermeters:
            outObj.append(
                self.get_powermeter_data(
                    pmIndex=powermeter["index"],
                    keepAlive=True
                    if powermeter["index"] != powermeters[-1]["index"]
                    else keepAlive,  # last request should honor keepAlive
                )
            )

        return outObj

    def get_power_settings(self, keepAlive: bool = False):
        """Polls the power settings via rscp protocol.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the power settings structured as follows::

                {
                    "discharge_start_power": <minimum power requested to enable discharge>,
                    "maxChargePower": <maximum charge power dependent on E3DC model>,
                    "maxDischargePower": <maximum discharge power dependent on E3DC model>,
                    "powerSaveEnabled": <status if power save is enabled>,
                    "powerLimitsUsed": <status if power limites are enabled>,
                    "weatherForecastMode": <Weather Forcast Mode>,
                    "weatherRegulatedChargeEnabled": <status if weather regulated charge is enabled>
                }
        """
        res = self.sendRequest(
            (RscpTag.EMS_REQ_GET_POWER_SETTINGS, RscpType.NoneType, None),
            keepAlive=keepAlive,
        )

        dischargeStartPower = rscpFindTagIndex(res, RscpTag.EMS_DISCHARGE_START_POWER)
        maxChargePower = rscpFindTagIndex(res, RscpTag.EMS_MAX_CHARGE_POWER)
        maxDischargePower = rscpFindTagIndex(res, RscpTag.EMS_MAX_DISCHARGE_POWER)
        powerLimitsUsed = rscpFindTagIndex(res, RscpTag.EMS_POWER_LIMITS_USED)
        powerSaveEnabled = rscpFindTagIndex(res, RscpTag.EMS_POWERSAVE_ENABLED)
        weatherForecastMode = rscpFindTagIndex(res, RscpTag.EMS_WEATHER_FORECAST_MODE)
        weatherRegulatedChargeEnabled = rscpFindTagIndex(
            res, RscpTag.EMS_WEATHER_REGULATED_CHARGE_ENABLED
        )

        outObj = {
            "dischargeStartPower": dischargeStartPower,
            "maxChargePower": maxChargePower,
            "maxDischargePower": maxDischargePower,
            "powerLimitsUsed": powerLimitsUsed,
            "powerSaveEnabled": powerSaveEnabled,
            "weatherForecastMode": weatherForecastMode,
            "weatherRegulatedChargeEnabled": weatherRegulatedChargeEnabled,
        }
        return outObj

    def set_power_limits(
        self,
        enable: bool,
        max_charge: int | None = None,
        max_discharge: int | None = None,
        discharge_start: int | None = None,
        keepAlive: bool = False,
    ):
        """Setting the SmartPower power limits via rscp protocol.

        Args:
            enable (bool): True/False
            max_charge (Optional[int]): maximum charge power
            max_discharge (Optional[int]: maximum discharge power
            discharge_start (Optional[int]: power where discharged is started
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            0 if success
            -1 if error
            1 if one value is nonoptimal
        """
        if max_charge is None:
            max_charge = self.maxBatChargePower

        if max_discharge is None:
            max_discharge = self.maxBatDischargePower

        if discharge_start is None:
            discharge_start = self.startDischargeDefault

        if enable:
            res = self.sendRequest(
                (
                    RscpTag.EMS_REQ_SET_POWER_SETTINGS,
                    RscpType.Container,
                    [
                        (RscpTag.EMS_POWER_LIMITS_USED, RscpType.Bool, True),
                        (
                            RscpTag.EMS_MAX_DISCHARGE_POWER,
                            RscpType.Uint32,
                            max_discharge,
                        ),
                        (RscpTag.EMS_MAX_CHARGE_POWER, RscpType.Uint32, max_charge),
                        (
                            RscpTag.EMS_DISCHARGE_START_POWER,
                            RscpType.Uint32,
                            discharge_start,
                        ),
                    ],
                ),
                keepAlive=keepAlive,
            )
        else:
            res = self.sendRequest(
                (
                    RscpTag.EMS_REQ_SET_POWER_SETTINGS,
                    RscpType.Container,
                    [(RscpTag.EMS_POWER_LIMITS_USED, RscpType.Bool, False)],
                ),
                keepAlive=keepAlive,
            )

        # validate all return codes for each limit to be 0 for success, 1 for nonoptimal value and -1 for failure
        return_code = 0
        for result in res[2]:
            if result[2] == -1:
                return_code = -1
            elif result[2] == 1 and return_code == 0:
                return_code = 1

        return return_code

    def set_powersave(self, enable: bool, keepAlive: bool = False):
        """Setting the SmartPower power save via rscp protocol.

        Args:
            enable (bool): True/False
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            0 if success
            -1 if error
        """
        res = self.sendRequest(
            (
                RscpTag.EMS_REQ_SET_POWER_SETTINGS,
                RscpType.Container,
                [(RscpTag.EMS_POWERSAVE_ENABLED, RscpType.UChar8, int(enable))],
            ),
            keepAlive=keepAlive,
        )

        # Returns value of EMS_REQ_SET_POWER_SETTINGS, we get a success flag here,
        # that we normalize and push outside.
        # [ RscpTag.EMS_SET_POWER_SETTINGS,
        #   RscpType.Container,
        #   [
        #       [RscpTag.EMS_RES_POWERSAVE_ENABLED, "Char8", 0]
        #   ]
        # ]

        if rscpFindTagIndex(res, RscpTag.EMS_RES_POWERSAVE_ENABLED) == 0:
            return 0
        else:
            return -1

    def set_weather_regulated_charge(self, enable: bool, keepAlive: bool = False):
        """Setting the SmartCharge weather regulated charge via rscp protocol.

        Args:
            enable (bool): True/False
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            0 if success
            -1 if error
        """
        if enable:
            res = self.sendRequest(
                (
                    RscpTag.EMS_REQ_SET_POWER_SETTINGS,
                    RscpType.Container,
                    [
                        (
                            RscpTag.EMS_WEATHER_REGULATED_CHARGE_ENABLED,
                            RscpType.UChar8,
                            1,
                        )
                    ],
                ),
                keepAlive=keepAlive,
            )
        else:
            res = self.sendRequest(
                (
                    RscpTag.EMS_REQ_SET_POWER_SETTINGS,
                    RscpType.Container,
                    [
                        (
                            RscpTag.EMS_WEATHER_REGULATED_CHARGE_ENABLED,
                            RscpType.UChar8,
                            0,
                        )
                    ],
                ),
                keepAlive=keepAlive,
            )

        # validate return code for EMS_RES_WEATHER_REGULATED_CHARGE_ENABLED is 0
        if res[2][0][2] == 0:
            return 0
        else:
            return -1
