#!/usr/bin/env python
# Python class to connect to an E3/DC system.
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

import datetime
import hashlib
import json
import time
import uuid

import dateutil.parser
import requests

from ._e3dc_rscp_local import (
    E3DC_RSCP_local,
    RSCPAuthenticationError,
    RSCPNotAvailableError,
)
from ._e3dc_rscp_web import E3DC_RSCP_web
from ._rscpLib import rscpFindTag, rscpFindTagIndex

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

    def __init__(self, connectType, **kwargs):
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
        self.powermeters = None
        self.pvis = None
        self.batteries = None
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
            self.poll = self.poll_rscp
        else:
            self._set_serial(kwargs["serialNumber"])
            if "isPasswordMd5" in kwargs:
                if kwargs["isPasswordMd5"]:
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
            self.poll = self.poll_ajax

        self.get_system_info_static(keepAlive=True)

    def _set_serial(self, serial):
        self.batteries = self.batteries or [{"index": 0}]
        self.pmIndexExt = 0

        if serial[0].isdigit():
            self.serialNumber = serial
        else:
            self.serialNumber = serial[4:]
            self.serialNumberPrefix = serial[:4]

        if self.serialNumber.startswith("4"):
            self.model = "S10E"
            self.powermeters = self.powermeters or [{"index": 0}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "S10-"
        elif self.serialNumber.startswith("5"):
            self.model = "S10mini"
            self.powermeters = self.powermeters or [{"index": 6}]
            self.pvis = self.pvis or [{"index": 0, "phases": [0]}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "S10-"
        elif self.serialNumber.startswith("6"):
            self.model = "Quattroporte"
            self.powermeters = self.powermeters or [{"index": 6}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "Q10-"
        elif self.serialNumber.startswith("7"):
            self.model = "Pro"
            self.powermeters = self.powermeters or [{"index": 0}]
            self.pvis = self.pvis or [{"index": 0}]
            if not self.serialNumberPrefix:
                self.serialNumberPrefix = "P10-"
        else:
            self.model = "NA"
            self.powermeters = self.powermeters or [{"index": 0}]

    def connect_web(self):
        """Connects to the E3DC portal and opens a session.

        Raises:
            e3dc.AuthenticationError: login error
        """
        # login request
        loginPayload = {
            "DO": "LOGIN",
            "USERNAME": self.username,
            "PASSWD": self.password,
        }
        headers = {"Window-Id": self.guid}

        try:
            r = requests.post(REMOTE_ADDRESS, data=loginPayload, headers=headers)
            jsonResponse = r.json()
        except:
            raise AuthenticationError("Error communicating with server")
        if jsonResponse["ERRNO"] != 0:
            raise AuthenticationError("Login error")

        # get cookies
        self.jar = r.cookies

        # set the proper device
        deviceSelectPayload = {
            "DO": "GETCONTENT",
            "MODID": "IDOVERVIEWUNITMAIN",
            "ARG0": self.serialNumber,
            "TOS": -7200,
        }

        try:
            r = requests.post(
                REMOTE_ADDRESS,
                data=deviceSelectPayload,
                cookies=self.jar,
                headers=headers,
            )
            jsonResponse = r.json()
        except:
            raise AuthenticationError("Error communicating with server")
        if jsonResponse["ERRNO"] != 0:
            raise AuthenticationError("Error selecting device")
        self.connected = True

    def poll_ajax_raw(self):
        """Polls the portal for the current status.

        Returns:
            dict: Dictionary containing the status information in raw format as returned by the portal

        Raises:
            e3dc.PollError in case of problems polling
        """
        if not self.connected:
            self.connect_web()

        pollPayload = {"DO": "LIVEUNITDATA"}
        pollHeaders = {
            "Pragma": "no-cache",
            "Cache-Control": "no-store",
            "Window-Id": self.guid,
        }

        try:
            r = requests.post(
                REMOTE_ADDRESS, data=pollPayload, cookies=self.jar, headers=pollHeaders
            )
            jsonResponse = r.json()
        except:
            self.connected = False
            raise PollError("Error communicating with server")

        if jsonResponse["ERRNO"] != 0:
            raise PollError("Error polling: %d" % (jsonResponse["ERRNO"]))

        return json.loads(jsonResponse["CONTENT"])

    def poll_ajax(self, **kwargs):
        """Polls the portal for the current status and returns a digest.

        Args:
            **kwars: argument list

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

        Raises:
            e3dc.PollError in case of problems polling
        """
        if (
            self.lastRequest is not None
            and (time.time() - self.lastRequestTime) < REQUEST_INTERVAL_SEC
        ):
            return self.lastRequest

        raw = self.poll_ajax_raw()
        strPmIndex = str(self.pmIndexExt)
        outObj = {
            "time": dateutil.parser.parse(raw["time"]).replace(
                tzinfo=datetime.timezone.utc
            ),
            "sysStatus": raw["SYSSTATUS"],
            "stateOfCharge": int(raw["SOC"]),
            "production": {
                "solar": int(raw["POWER_PV_S1"])
                + int(raw["POWER_PV_S2"])
                + int(raw["POWER_PV_S3"]),
                "add": -(
                    int(raw["PM" + strPmIndex + "_L1"])
                    + int(raw["PM" + strPmIndex + "_L2"])
                    + int(raw["PM" + strPmIndex + "_L3"])
                ),
                "grid": int(raw["POWER_LM_L1"])
                + int(raw["POWER_LM_L2"])
                + int(raw["POWER_LM_L3"]),
            },
            "consumption": {
                "battery": int(raw["POWER_BAT"]),
                "house": int(raw["POWER_C_L1"])
                + int(raw["POWER_C_L2"])
                + int(raw["POWER_C_L3"]),
                "wallbox": int(raw["POWER_WALLBOX"]),
            },
        }

        self.lastRequest = outObj
        self.lastRequestTime = time.time()

        return outObj

    def poll_rscp(self, keepAlive=False):
        """Polls via rscp protocol locally.

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

        ts = self.sendRequestTag("INFO_REQ_UTC_TIME", keepAlive=True)
        soc = self.sendRequestTag("EMS_REQ_BAT_SOC", keepAlive=True)
        solar = self.sendRequestTag("EMS_REQ_POWER_PV", keepAlive=True)
        add = self.sendRequestTag("EMS_REQ_POWER_ADD", keepAlive=True)
        bat = self.sendRequestTag("EMS_REQ_POWER_BAT", keepAlive=True)
        home = self.sendRequestTag("EMS_REQ_POWER_HOME", keepAlive=True)
        grid = self.sendRequestTag("EMS_REQ_POWER_GRID", keepAlive=True)
        wb = self.sendRequestTag("EMS_REQ_POWER_WB_ALL", keepAlive=True)

        sc = round(
            self.sendRequestTag("EMS_REQ_SELF_CONSUMPTION", keepAlive=True),
            2,
        )

        # last call, use keepAlive value
        autarky = round(
            self.sendRequestTag("EMS_REQ_AUTARKY", keepAlive=keepAlive),
            2,
        )

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

    def poll_switches(self, keepAlive=False):
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
            ("HA_REQ_DATAPOINT_LIST", "None", None), keepAlive=True
        )
        switchStatus = self.sendRequest(
            ("HA_REQ_ACTUATOR_STATES", "None", None), keepAlive=keepAlive
        )

        descList = switchDesc[2]  # get the payload of the container
        statusList = switchStatus[2]

        switchList = []

        for switch in range(len(descList)):
            switchID = rscpFindTagIndex(descList[switch], "HA_DATAPOINT_INDEX")
            switchType = rscpFindTagIndex(descList[switch], "HA_DATAPOINT_TYPE")
            switchName = rscpFindTagIndex(descList[switch], "HA_DATAPOINT_NAME")
            switchStatus = rscpFindTagIndex(statusList[switch], "HA_DATAPOINT_STATE")
            switchList.append(
                {
                    "id": switchID,
                    "type": switchType,
                    "name": switchName,
                    "status": switchStatus,
                }
            )

        return switchList

    def set_switch_onoff(self, switchID, value, keepAlive=False):
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
                "HA_REQ_COMMAND_ACTUATOR",
                "Container",
                [
                    ("HA_DATAPOINT_INDEX", "Uint16", switchID),
                    ("HA_REQ_COMMAND", "CString", cmd),
                ],
            ),
            keepAlive=keepAlive,
        )

        if result[0] == "HA_COMMAND_ACTUATOR" and result[2]:
            return True
        else:
            return False  # operation did not succeed

    def sendRequest(self, request, retries=3, keepAlive=False):
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
            except Exception:
                retry += 1
                if retry > retries:
                    raise SendError("Max retries reached")

        if not keepAlive:
            self.rscp.disconnect()

        return result

    def sendRequestTag(self, tag, retries=3, keepAlive=False):
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
            (tag, "None", None), retries=retries, keepAlive=keepAlive
        )[2]

    def get_idle_periods(self, keepAlive=False):
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
            ("EMS_REQ_GET_IDLE_PERIODS", "None", None), keepAlive=keepAlive
        )
        if idlePeriodsRaw[0] != "EMS_GET_IDLE_PERIODS":
            return None

        idlePeriods = {"idleCharge": [None] * 7, "idleDischarge": [None] * 7}

        # initialize
        for period in idlePeriodsRaw[2]:
            active = rscpFindTagIndex(period, "EMS_IDLE_PERIOD_ACTIVE")
            typ = rscpFindTagIndex(period, "EMS_IDLE_PERIOD_TYPE")
            day = rscpFindTagIndex(period, "EMS_IDLE_PERIOD_DAY")
            start = rscpFindTag(period, "EMS_IDLE_PERIOD_START")
            startHour = rscpFindTagIndex(start, "EMS_IDLE_PERIOD_HOUR")
            startMin = rscpFindTagIndex(start, "EMS_IDLE_PERIOD_MINUTE")
            end = rscpFindTag(period, "EMS_IDLE_PERIOD_END")
            endHour = rscpFindTagIndex(end, "EMS_IDLE_PERIOD_HOUR")
            endMin = rscpFindTagIndex(end, "EMS_IDLE_PERIOD_MINUTE")
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

    def set_idle_periods(self, idlePeriods, keepAlive=False):
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

        if not isinstance(idlePeriods, dict):
            raise TypeError("object is not a dict")
        elif "idleCharge" not in idlePeriods and "idleDischarge" not in idlePeriods:
            raise ValueError("neither key idleCharge nor idleDischarge in object")

        for idle_type in ["idleCharge", "idleDischarge"]:
            if idle_type in idlePeriods:
                if isinstance(idlePeriods[idle_type], list):
                    for idlePeriod in idlePeriods[idle_type]:
                        if isinstance(idlePeriod, dict):
                            if "day" not in idlePeriod:
                                raise ValueError("day key in " + idle_type + " missing")
                            elif isinstance(idlePeriod["day"], bool):
                                raise TypeError("day in " + idle_type + " not a bool")
                            elif not (0 <= idlePeriod["day"] <= 6):
                                raise ValueError(
                                    "day in " + idle_type + " out of range"
                                )

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
                                                        (
                                                            i == 0
                                                            and idlePeriod[key][i] < 24
                                                        )
                                                        or (
                                                            i == 1
                                                            and idlePeriod[key][i] < 60
                                                        )
                                                    ):
                                                        idlePeriod[key][i] = idlePeriod[
                                                            key
                                                        ][i]
                                                    else:
                                                        raise ValueError(
                                                            key
                                                            in " period "
                                                            + str(idlePeriod["day"])
                                                            + " in "
                                                            + idle_type
                                                            + " is not between 00:00 and 23:59"
                                                        )
                                if (
                                    idlePeriod["start"][0] * 60 + idlePeriod["start"][1]
                                ) < (idlePeriod["end"][0] * 60 + idlePeriod["end"][1]):
                                    periodList.append(
                                        (
                                            "EMS_IDLE_PERIOD",
                                            "Container",
                                            [
                                                (
                                                    "EMS_IDLE_PERIOD_TYPE",
                                                    "UChar8",
                                                    self._IDLE_TYPE[idle_type],
                                                ),
                                                (
                                                    "EMS_IDLE_PERIOD_DAY",
                                                    "UChar8",
                                                    idlePeriod["day"],
                                                ),
                                                (
                                                    "EMS_IDLE_PERIOD_ACTIVE",
                                                    "Bool",
                                                    idlePeriod["active"],
                                                ),
                                                (
                                                    "EMS_IDLE_PERIOD_START",
                                                    "Container",
                                                    [
                                                        (
                                                            "EMS_IDLE_PERIOD_HOUR",
                                                            "UChar8",
                                                            idlePeriod["start"][0],
                                                        ),
                                                        (
                                                            "EMS_IDLE_PERIOD_MINUTE",
                                                            "UChar8",
                                                            idlePeriod["start"][1],
                                                        ),
                                                    ],
                                                ),
                                                (
                                                    "EMS_IDLE_PERIOD_END",
                                                    "Container",
                                                    [
                                                        (
                                                            "EMS_IDLE_PERIOD_HOUR",
                                                            "UChar8",
                                                            idlePeriod["end"][0],
                                                        ),
                                                        (
                                                            "EMS_IDLE_PERIOD_MINUTE",
                                                            "UChar8",
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
            ("EMS_REQ_SET_IDLE_PERIODS", "Container", periodList), keepAlive=keepAlive
        )

        if result[0] != "EMS_SET_IDLE_PERIODS" or result[2] != 1:
            return False
        return True

    def get_db_data(
        self, startDate: datetime.date = None, timespan: str = "DAY", keepAlive=False
    ):
        """Reads DB data and summed up values for the given timespan via rscp protocol locally.

        Args:
            startDate (datetime.date): start date for timespan, default today
            timespan (str): string specifying the time span ["DAY", "MONTH", "YEAR"]
            keepAlive (Optional[bool]): True to keep connection alive

        Returns:
            dict: Dictionary containing the stored db information structured as follows::

                {
                    "autarky": <autarky in the period in %>,
                    "bat_power_in": <power entering battery, charging>,
                    "bat_power_out": <power leavinb battery, discharging>,
                    "consumed_production": <power directly consumed in %>,
                    "consumption": <self consumed power>,
                    "grid_power_in": <power taken from the grid>,
                    "grid_power_out": <power into the grid>,
                    "stateOfCharge": <battery charge level in %>,
                    "solarProduction": <power production>,
                }
        """
        span: int = 0
        if startDate is None:
            startDate = datetime.date.today()
        requestDate: int = int(time.mktime(startDate.timetuple()))

        if "YEAR" == timespan:
            spanDate = startDate.replace(year=startDate.year + 1)
            span = int(time.mktime(spanDate.timetuple()) - requestDate)
        if "MONTH" == timespan:
            if 12 == startDate.month:
                spanDate = startDate.replace(month=1, year=startDate.year + 1)
            else:
                spanDate = startDate.replace(month=startDate.month + 1)
            span = int(time.mktime(spanDate.timetuple()) - requestDate)
        if "DAY" == timespan:
            span = 24 * 60 * 60

        if span == 0:
            return None

        response = self.sendRequest(
            (
                "DB_REQ_HISTORY_DATA_DAY",
                "Container",
                [
                    ("DB_REQ_HISTORY_TIME_START", "Uint64", requestDate),
                    ("DB_REQ_HISTORY_TIME_INTERVAL", "Uint64", span),
                    ("DB_REQ_HISTORY_TIME_SPAN", "Uint64", span),
                ],
            ),
            keepAlive=keepAlive,
        )

        outObj = {
            "autarky": rscpFindTagIndex(response[2][0], "DB_AUTARKY"),
            "bat_power_in": rscpFindTagIndex(response[2][0], "DB_BAT_POWER_IN"),
            "bat_power_out": rscpFindTagIndex(response[2][0], "DB_BAT_POWER_OUT"),
            "consumed_production": rscpFindTagIndex(
                response[2][0], "DB_CONSUMED_PRODUCTION"
            ),
            "consumption": rscpFindTagIndex(response[2][0], "DB_CONSUMPTION"),
            "grid_power_in": rscpFindTagIndex(response[2][0], "DB_GRID_POWER_IN"),
            "grid_power_out": rscpFindTagIndex(response[2][0], "DB_GRID_POWER_OUT"),
            "stateOfCharge": rscpFindTagIndex(response[2][0], "DB_BAT_CHARGE_LEVEL"),
            "solarProduction": rscpFindTagIndex(response[2][0], "DB_DC_POWER"),
        }
        return outObj

    def get_system_info_static(self, keepAlive=False):
        """Polls the static system info via rscp protocol locally.

        Args:
            keepAlive (Optional[bool]): True to keep connection alive
        """
        self.deratePercent = round(
            self.sendRequestTag("EMS_REQ_DERATE_AT_PERCENT_VALUE", keepAlive=True) * 100
        )
        self.deratePower = self.sendRequestTag(
            "EMS_REQ_DERATE_AT_POWER_VALUE", keepAlive=True
        )
        self.installedPeakPower = self.sendRequestTag(
            "EMS_REQ_INSTALLED_PEAK_POWER", keepAlive=True
        )
        self.externalSourceAvailable = self.sendRequestTag(
            "EMS_REQ_EXT_SRC_AVAILABLE", keepAlive=True
        )
        self.macAddress = self.sendRequestTag("INFO_REQ_MAC_ADDRESS", keepAlive=True)
        if (
            not self.serialNumber
        ):  # do not send this for a web connection because it screws up the handshake!
            self._set_serial(
                self.sendRequestTag("INFO_REQ_SERIAL_NUMBER", keepAlive=True)
            )

        sys_specs = self.sendRequestTag("EMS_REQ_GET_SYS_SPECS", keepAlive=keepAlive)
        for item in sys_specs:
            if (
                rscpFindTagIndex(item, "EMS_SYS_SPEC_NAME")
                == "installedBatteryCapacity"
            ):
                self.installedBatteryCapacity = rscpFindTagIndex(
                    item, "EMS_SYS_SPEC_VALUE_INT"
                )
            elif rscpFindTagIndex(item, "EMS_SYS_SPEC_NAME") == "maxAcPower":
                self.maxAcPower = rscpFindTagIndex(item, "EMS_SYS_SPEC_VALUE_INT")
            elif rscpFindTagIndex(item, "EMS_SYS_SPEC_NAME") == "maxBatChargePower":
                self.maxBatChargePower = rscpFindTagIndex(
                    item, "EMS_SYS_SPEC_VALUE_INT"
                )
            elif rscpFindTagIndex(item, "EMS_SYS_SPEC_NAME") == "maxBatDischargPower":
                self.maxBatDischargePower = rscpFindTagIndex(
                    item, "EMS_SYS_SPEC_VALUE_INT"
                )

        # EMS_REQ_SPECIFICATION_VALUES

        return True

    def get_system_info(self, keepAlive=False):
        """Polls the system info via rscp protocol locally.

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
        sw = self.sendRequestTag("INFO_REQ_SW_RELEASE", keepAlive=keepAlive)

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

    def get_system_status(self, keepAlive=False):
        """Polls the system status via rscp protocol locally.

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
        sw = self.sendRequestTag("EMS_REQ_SYS_STATUS", keepAlive=keepAlive)
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

    def get_battery_data(self, batIndex=None, dcbs=None, keepAlive=False):
        """Polls the battery data via rscp protocol locally.

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
                    "measuredResistance": <measured resistance>,
                    "measuredResistanceRun": <measure resistance (RUN)>,
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
                "BAT_REQ_DATA",
                "Container",
                [
                    ("BAT_INDEX", "Uint16", batIndex),
                    ("BAT_REQ_ASOC", "None", None),
                    ("BAT_REQ_CHARGE_CYCLES", "None", None),
                    ("BAT_REQ_CURRENT", "None", None),
                    ("BAT_REQ_DCB_COUNT", "None", None),
                    ("BAT_REQ_DESIGN_CAPACITY", "None", None),
                    ("BAT_REQ_DEVICE_NAME", "None", None),
                    ("BAT_REQ_DEVICE_STATE", "None", None),
                    ("BAT_REQ_EOD_VOLTAGE", "None", None),
                    ("BAT_REQ_ERROR_CODE", "None", None),
                    ("BAT_REQ_FCC", "None", None),
                    ("BAT_REQ_MAX_BAT_VOLTAGE", "None", None),
                    ("BAT_REQ_MAX_CHARGE_CURRENT", "None", None),
                    ("BAT_REQ_MAX_DISCHARGE_CURRENT", "None", None),
                    ("BAT_REQ_MAX_DCB_CELL_TEMPERATURE", "None", None),
                    ("BAT_REQ_MIN_DCB_CELL_TEMPERATURE", "None", None),
                    ("BAT_REQ_INTERNALS", "None", None),
                    ("BAT_REQ_MODULE_VOLTAGE", "None", None),
                    ("BAT_REQ_RC", "None", None),
                    ("BAT_REQ_READY_FOR_SHUTDOWN", "None", None),
                    ("BAT_REQ_RSOC", "None", None),
                    ("BAT_REQ_RSOC_REAL", "None", None),
                    ("BAT_REQ_STATUS_CODE", "None", None),
                    ("BAT_REQ_TERMINAL_VOLTAGE", "None", None),
                    ("BAT_REQ_TOTAL_USE_TIME", "None", None),
                    ("BAT_REQ_TOTAL_DISCHARGE_TIME", "None", None),
                    ("BAT_REQ_TRAINING_MODE", "None", None),
                    ("BAT_REQ_USABLE_CAPACITY", "None", None),
                    ("BAT_REQ_USABLE_REMAINING_CAPACITY", "None", None),
                ],
            ),
            keepAlive=True,
        )

        dcbCount = rscpFindTagIndex(req, "BAT_DCB_COUNT")
        deviceStateContainer = rscpFindTag(req, "BAT_DEVICE_STATE")

        outObj = {
            "asoc": rscpFindTagIndex(req, "BAT_ASOC"),
            "chargeCycles": rscpFindTagIndex(req, "BAT_CHARGE_CYCLES"),
            "current": round(rscpFindTagIndex(req, "BAT_CURRENT"), 2),
            "dcbCount": dcbCount,
            "dcbs": {},
            "designCapacity": round(rscpFindTagIndex(req, "BAT_DESIGN_CAPACITY"), 2),
            "deviceConnected": rscpFindTagIndex(
                deviceStateContainer, "BAT_DEVICE_CONNECTED"
            ),
            "deviceInService": rscpFindTagIndex(
                deviceStateContainer, "BAT_DEVICE_IN_SERVICE"
            ),
            "deviceName": rscpFindTagIndex(req, "BAT_DEVICE_NAME"),
            "deviceWorking": rscpFindTagIndex(
                deviceStateContainer, "BAT_DEVICE_WORKING"
            ),
            "eodVoltage": round(rscpFindTagIndex(req, "BAT_EOD_VOLTAGE"), 2),
            "errorCode": rscpFindTagIndex(req, "BAT_ERROR_CODE"),
            "fcc": rscpFindTagIndex(req, "BAT_FCC"),
            "index": batIndex,
            "maxBatVoltage": round(rscpFindTagIndex(req, "BAT_MAX_BAT_VOLTAGE"), 2),
            "maxChargeCurrent": round(
                rscpFindTagIndex(req, "BAT_MAX_CHARGE_CURRENT"), 2
            ),
            "maxDischargeCurrent": round(
                rscpFindTagIndex(req, "BAT_MAX_DISCHARGE_CURRENT"), 2
            ),
            "maxDcbCellTemp": round(
                rscpFindTagIndex(req, "BAT_MAX_DCB_CELL_TEMPERATURE"), 2
            ),
            "measuredResistance": round(
                rscpFindTagIndex(req, "BAT_MEASURED_RESISTANCE"), 4
            ),
            "measuredResistanceRun": round(
                rscpFindTagIndex(req, "BAT_RUN_MEASURED_RESISTANCE"), 4
            ),
            "minDcbCellTemp": round(
                rscpFindTagIndex(req, "BAT_MIN_DCB_CELL_TEMPERATURE"), 2
            ),
            "moduleVoltage": round(rscpFindTagIndex(req, "BAT_MODULE_VOLTAGE"), 2),
            "rc": round(rscpFindTagIndex(req, "BAT_RC"), 2),
            "readyForShutdown": round(
                rscpFindTagIndex(req, "BAT_READY_FOR_SHUTDOWN"), 2
            ),
            "rsoc": round(rscpFindTagIndex(req, "BAT_RSOC"), 2),
            "rsocReal": round(rscpFindTagIndex(req, "BAT_RSOC_REAL"), 2),
            "statusCode": rscpFindTagIndex(req, "BAT_STATUS_CODE"),
            "terminalVoltage": round(rscpFindTagIndex(req, "BAT_TERMINAL_VOLTAGE"), 2),
            "totalUseTime": rscpFindTagIndex(req, "BAT_TOTAL_USE_TIME"),
            "totalDischargeTime": rscpFindTagIndex(req, "BAT_TOTAL_DISCHARGE_TIME"),
            "trainingMode": rscpFindTagIndex(req, "BAT_TRAINING_MODE"),
            "usuableCapacity": round(rscpFindTagIndex(req, "BAT_USABLE_CAPACITY"), 2),
            "usuableRemainingCapacity": round(
                rscpFindTagIndex(req, "BAT_USABLE_REMAINING_CAPACITY"), 2
            ),
        }

        if dcbs is None:
            dcbs = range(0, dcbCount)

        for dcb in dcbs:
            req = self.sendRequest(
                (
                    "BAT_REQ_DATA",
                    "Container",
                    [
                        ("BAT_INDEX", "Uint16", batIndex),
                        ("BAT_REQ_DCB_ALL_CELL_TEMPERATURES", "Uint16", dcb),
                        ("BAT_REQ_DCB_ALL_CELL_VOLTAGES", "Uint16", dcb),
                        ("BAT_REQ_DCB_INFO", "Uint16", dcb),
                    ],
                ),
                keepAlive=True
                if dcb != dcbs[-1]
                else keepAlive,  # last request should honor keepAlive
            )

            info = rscpFindTag(req, "BAT_DCB_INFO")

            temperatures_raw = rscpFindTagIndex(
                rscpFindTag(req, "BAT_DCB_ALL_CELL_TEMPERATURES"), "BAT_DATA"
            )
            temperatures = []
            sensorCount = rscpFindTagIndex(info, "BAT_DCB_NR_SENSOR")
            for sensor in range(0, sensorCount):
                temperatures.append(round(temperatures_raw[sensor][2], 2))

            voltages_raw = rscpFindTagIndex(
                rscpFindTag(req, "BAT_DCB_ALL_CELL_VOLTAGES"), "BAT_DATA"
            )
            voltages = []
            seriesCellCount = rscpFindTagIndex(info, "BAT_DCB_NR_SERIES_CELL")
            for cell in range(0, seriesCellCount):
                voltages.append(round(voltages_raw[cell][2], 2))

            dcbobj = {
                "current": rscpFindTagIndex(info, "BAT_DCB_CURRENT"),
                "currentAvg30s": rscpFindTagIndex(info, "BAT_DCB_CURRENT_AVG_30S"),
                "cycleCount": rscpFindTagIndex(info, "BAT_DCB_CYCLE_COUNT"),
                "designCapacity": rscpFindTagIndex(info, "BAT_DCB_DESIGN_CAPACITY"),
                "designVoltage": rscpFindTagIndex(info, "BAT_DCB_DESIGN_VOLTAGE"),
                "deviceName": rscpFindTagIndex(info, "BAT_DCB_DEVICE_NAME"),
                "endOfDischarge": rscpFindTagIndex(info, "BAT_DCB_END_OF_DISCHARGE"),
                "error": rscpFindTagIndex(info, "BAT_DCB_ERROR"),
                "fullChargeCapacity": rscpFindTagIndex(
                    info, "BAT_DCB_FULL_CHARGE_CAPACITY"
                ),
                "fwVersion": rscpFindTagIndex(info, "BAT_DCB_FW_VERSION"),
                "manufactureDate": rscpFindTagIndex(info, "BAT_DCB_MANUFACTURE_DATE"),
                "manufactureName": rscpFindTagIndex(info, "BAT_DCB_MANUFACTURE_NAME"),
                "maxChargeCurrent": rscpFindTagIndex(
                    info, "BAT_DCB_MAX_CHARGE_CURRENT"
                ),
                "maxChargeTemperature": rscpFindTagIndex(
                    info, "BAT_DCB_CHARGE_HIGH_TEMPERATURE"
                ),
                "maxChargeVoltage": rscpFindTagIndex(
                    info, "BAT_DCB_MAX_CHARGE_VOLTAGE"
                ),
                "maxDischargeCurrent": rscpFindTagIndex(
                    info, "BAT_DCB_MAX_DISCHARGE_CURRENT"
                ),
                "minChargeTemperature": rscpFindTagIndex(
                    info, "BAT_DCB_CHARGE_LOW_TEMPERATURE"
                ),
                "parallelCellCount": rscpFindTagIndex(info, "BAT_DCB_NR_PARALLEL_CELL"),
                "sensorCount": sensorCount,
                "seriesCellCount": seriesCellCount,
                "pcbVersion": rscpFindTagIndex(info, "BAT_DCB_PCB_VERSION"),
                "protocolVersion": rscpFindTagIndex(info, "BAT_DCB_PROTOCOL_VERSION"),
                "remainingCapacity": rscpFindTagIndex(
                    info, "BAT_DCB_REMAINING_CAPACITY"
                ),
                "serialCode": rscpFindTagIndex(info, "BAT_DCB_SERIALCODE"),
                "serialNo": rscpFindTagIndex(info, "BAT_DCB_SERIALNO"),
                "soc": rscpFindTagIndex(info, "BAT_DCB_SOC"),
                "soh": rscpFindTagIndex(info, "BAT_DCB_SOH"),
                "status": rscpFindTagIndex(info, "BAT_DCB_STATUS"),
                "temperatures": temperatures,
                "voltage": rscpFindTagIndex(info, "BAT_DCB_VOLTAGE"),
                "voltageAvg30s": rscpFindTagIndex(info, "BAT_DCB_VOLTAGE_AVG_30S"),
                "voltages": voltages,
                "warning": rscpFindTagIndex(info, "BAT_DCB_WARNING"),
            }
            outObj["dcbs"][dcb] = dcbobj
        return outObj

    def get_batteries_data(self, batteries=None, keepAlive=False):
        """Polls the batteries data via rscp protocol locally.

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
                dcbs = range(0, battery["dcbs"])
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

    def get_pvi_data(self, pviIndex=None, strings=None, phases=None, keepAlive=False):
        """Polls the inverter data via rscp protocol locally.

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
                phases = range(0, self.pvis[0]["phases"])

        req = self.sendRequest(
            (
                "PVI_REQ_DATA",
                "Container",
                [
                    ("PVI_INDEX", "Uint16", pviIndex),
                    ("PVI_REQ_AC_MAX_PHASE_COUNT", "None", None),
                    ("PVI_REQ_TEMPERATURE_COUNT", "None", None),
                    ("PVI_REQ_DC_MAX_STRING_COUNT", "None", None),
                    ("PVI_REQ_USED_STRING_COUNT", "None", None),
                    ("PVI_REQ_TYPE", "None", None),
                    ("PVI_REQ_SERIAL_NUMBER", "None", None),
                    ("PVI_REQ_VERSION", "None", None),
                    ("PVI_REQ_ON_GRID", "None", None),
                    ("PVI_REQ_STATE", "None", None),
                    ("PVI_REQ_LAST_ERROR", "None", None),
                    ("PVI_REQ_COS_PHI", "None", None),
                    ("PVI_REQ_VOLTAGE_MONITORING", "None", None),
                    ("PVI_REQ_POWER_MODE", "None", None),
                    ("PVI_REQ_SYSTEM_MODE", "None", None),
                    ("PVI_REQ_FREQUENCY_UNDER_OVER", "None", None),
                    ("PVI_REQ_MAX_TEMPERATURE", "None", None),
                    ("PVI_REQ_MIN_TEMPERATURE", "None", None),
                    ("PVI_REQ_AC_MAX_APPARENTPOWER", "None", None),
                    ("PVI_REQ_DEVICE_STATE", "None", None),
                ],
            ),
            keepAlive=True,
        )

        maxPhaseCount = int(rscpFindTagIndex(req, "PVI_AC_MAX_PHASE_COUNT"))
        maxStringCount = int(rscpFindTagIndex(req, "PVI_DC_MAX_STRING_COUNT"))
        usedStringCount = int(rscpFindTagIndex(req, "PVI_USED_STRING_COUNT"))

        voltageMonitoring = rscpFindTag(req, "PVI_VOLTAGE_MONITORING")
        cosPhi = rscpFindTag(req, "PVI_COS_PHI")
        frequency = rscpFindTag(req, "PVI_FREQUENCY_UNDER_OVER")
        deviceState = rscpFindTag(req, "PVI_DEVICE_STATE")

        outObj = {
            "acMaxApparentPower": rscpFindTagIndex(
                rscpFindTag(req, "PVI_AC_MAX_APPARENTPOWER"), "PVI_VALUE"
            ),
            "cosPhi": {
                "active": rscpFindTagIndex(cosPhi, "PVI_COS_PHI_IS_AKTIV"),
                "value": rscpFindTagIndex(cosPhi, "PVI_COS_PHI_VALUE"),
                "excited": rscpFindTagIndex(cosPhi, "PVI_COS_PHI_EXCITED"),
            },
            "deviceState": {
                "connected": rscpFindTagIndex(deviceState, "PVI_DEVICE_CONNECTED"),
                "working": rscpFindTagIndex(deviceState, "PVI_DEVICE_WORKING"),
                "inService": rscpFindTagIndex(deviceState, "PVI_DEVICE_IN_SERVICE"),
            },
            "frequency": {
                "under": rscpFindTagIndex(frequency, "PVI_FREQUENCY_UNDER"),
                "over": rscpFindTagIndex(frequency, "PVI_FREQUENCY_OVER"),
            },
            "index": pviIndex,
            "lastError": rscpFindTagIndex(req, "PVI_LAST_ERROR"),
            "maxPhaseCount": maxPhaseCount,
            "maxStringCount": maxStringCount,
            "onGrid": rscpFindTagIndex(req, "PVI_ON_GRID"),
            "phases": {},
            "powerMode": rscpFindTagIndex(req, "PVI_POWER_MODE"),
            "serialNumber": rscpFindTagIndex(req, "PVI_SERIAL_NUMBER"),
            "state": rscpFindTagIndex(req, "PVI_STATE"),
            "strings": {},
            "systemMode": rscpFindTagIndex(req, "PVI_SYSTEM_MODE"),
            "temperature": {
                "max": rscpFindTagIndex(
                    rscpFindTag(req, "PVI_MAX_TEMPERATURE"), "PVI_VALUE"
                ),
                "min": rscpFindTagIndex(
                    rscpFindTag(req, "PVI_MIN_TEMPERATURE"), "PVI_VALUE"
                ),
                "values": [],
            },
            "type": rscpFindTagIndex(req, "PVI_TYPE"),
            "version": rscpFindTagIndex(
                rscpFindTag(req, "PVI_VERSION"), "PVI_VERSION_MAIN"
            ),
            "voltageMonitoring": {
                "thresholdTop": rscpFindTagIndex(
                    voltageMonitoring, "PVI_VOLTAGE_MONITORING_THRESHOLD_TOP"
                ),
                "thresholdBottom": rscpFindTagIndex(
                    voltageMonitoring, "PVI_VOLTAGE_MONITORING_THRESHOLD_BOTTOM"
                ),
                "slopeUp": rscpFindTagIndex(
                    voltageMonitoring, "PVI_VOLTAGE_MONITORING_SLOPE_UP"
                ),
                "slopeDown": rscpFindTagIndex(
                    voltageMonitoring, "PVI_VOLTAGE_MONITORING_SLOPE_DOWN"
                ),
            },
        }

        temperatures = range(0, int(rscpFindTagIndex(req, "PVI_TEMPERATURE_COUNT")))
        for temperature in temperatures:
            req = self.sendRequest(
                (
                    "PVI_REQ_DATA",
                    "Container",
                    [
                        ("PVI_INDEX", "Uint16", pviIndex),
                        ("PVI_REQ_TEMPERATURE", "Uint16", temperature),
                    ],
                ),
                keepAlive=True,
            )
            outObj["temperature"]["values"].append(
                round(
                    rscpFindTagIndex(rscpFindTag(req, "PVI_TEMPERATURE"), "PVI_VALUE"),
                    2,
                )
            )

        if phases is None:
            phases = range(0, maxPhaseCount)

        for phase in phases:
            req = self.sendRequest(
                (
                    "PVI_REQ_DATA",
                    "Container",
                    [
                        ("PVI_INDEX", "Uint16", pviIndex),
                        ("PVI_REQ_AC_POWER", "Uint16", phase),
                        ("PVI_REQ_AC_VOLTAGE", "Uint16", phase),
                        ("PVI_REQ_AC_CURRENT", "Uint16", phase),
                        ("PVI_REQ_AC_APPARENTPOWER", "Uint16", phase),
                        ("PVI_REQ_AC_REACTIVEPOWER", "Uint16", phase),
                        ("PVI_REQ_AC_ENERGY_ALL", "Uint16", phase),
                        ("PVI_REQ_AC_ENERGY_GRID_CONSUMPTION", "Uint16", phase),
                    ],
                ),
                keepAlive=True,
            )
            phaseobj = {
                "power": round(
                    rscpFindTagIndex(rscpFindTag(req, "PVI_AC_POWER"), "PVI_VALUE"), 2
                ),
                "voltage": round(
                    rscpFindTagIndex(rscpFindTag(req, "PVI_AC_VOLTAGE"), "PVI_VALUE"), 2
                ),
                "current": round(
                    rscpFindTagIndex(rscpFindTag(req, "PVI_AC_CURRENT"), "PVI_VALUE"), 2
                ),
                "apparentPower": round(
                    rscpFindTag(rscpFindTag(req, "PVI_AC_APPARENTPOWER"), "PVI_VALUE")[
                        2
                    ],
                    2,
                ),
                "reactivePower": round(
                    rscpFindTagIndex(
                        rscpFindTag(req, "PVI_AC_REACTIVEPOWER"), "PVI_VALUE"
                    ),
                    2,
                ),
                "energyAll": round(
                    rscpFindTagIndex(
                        rscpFindTag(req, "PVI_AC_ENERGY_ALL"), "PVI_VALUE"
                    ),
                    2,
                ),
                "energyGridConsumption": round(
                    rscpFindTagIndex(
                        rscpFindTag(req, "PVI_AC_ENERGY_GRID_CONSUMPTION"), "PVI_VALUE"
                    ),
                    2,
                ),
            }
            outObj["phases"][phase] = phaseobj

        if strings is None:
            strings = range(0, usedStringCount)

        for string in strings:
            req = self.sendRequest(
                (
                    "PVI_REQ_DATA",
                    "Container",
                    [
                        ("PVI_INDEX", "Uint16", pviIndex),
                        ("PVI_REQ_DC_POWER", "Uint16", string),
                        ("PVI_REQ_DC_VOLTAGE", "Uint16", string),
                        ("PVI_REQ_DC_CURRENT", "Uint16", string),
                        ("PVI_REQ_DC_STRING_ENERGY_ALL", "Uint16", string),
                    ],
                ),
                keepAlive=True
                if string != strings[-1]
                else keepAlive,  # last request should honor keepAlive
            )
            stringobj = {
                "power": round(
                    rscpFindTagIndex(rscpFindTag(req, "PVI_DC_POWER"), "PVI_VALUE"), 2
                ),
                "voltage": round(
                    rscpFindTagIndex(rscpFindTag(req, "PVI_DC_VOLTAGE"), "PVI_VALUE"), 2
                ),
                "current": round(
                    rscpFindTagIndex(rscpFindTag(req, "PVI_DC_CURRENT"), "PVI_VALUE"), 2
                ),
                "energyAll": round(
                    rscpFindTagIndex(
                        rscpFindTag(req, "PVI_DC_STRING_ENERGY_ALL"), "PVI_VALUE"
                    ),
                    2,
                ),
            }
            outObj["strings"][string] = stringobj
        return outObj

    def get_pvis_data(self, pvis=None, keepAlive=False):
        """Polls the inverters data via rscp protocol locally.

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
                strings = range(0, pvi["strings"])
            else:
                strings = None

            if "phases" in pvi:
                phases = range(0, pvi["phases"])
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

    def get_powermeter_data(self, pmIndex=None, keepAlive=False):
        """Polls the power meter data via rscp protocol locally.

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
                "PM_REQ_DATA",
                "Container",
                [
                    ("PM_INDEX", "Uint16", pmIndex),
                    ("PM_REQ_POWER_L1", "None", None),
                    ("PM_REQ_POWER_L2", "None", None),
                    ("PM_REQ_POWER_L3", "None", None),
                    ("PM_REQ_VOLTAGE_L1", "None", None),
                    ("PM_REQ_VOLTAGE_L2", "None", None),
                    ("PM_REQ_VOLTAGE_L3", "None", None),
                    ("PM_REQ_ENERGY_L1", "None", None),
                    ("PM_REQ_ENERGY_L2", "None", None),
                    ("PM_REQ_ENERGY_L3", "None", None),
                    ("PM_REQ_MAX_PHASE_POWER", "None", None),
                    ("PM_REQ_ACTIVE_PHASES", "None", None),
                    ("PM_REQ_TYPE", "None", None),
                    ("PM_REQ_MODE", "None", None),
                ],
            ),
            keepAlive=keepAlive,
        )

        activePhasesChar = rscpFindTagIndex(res, "PM_ACTIVE_PHASES")
        activePhases = f"{activePhasesChar:03b}"

        outObj = {
            "activePhases": activePhases,
            "energy": {
                "L1": rscpFindTagIndex(res, "PM_ENERGY_L1"),
                "L2": rscpFindTagIndex(res, "PM_ENERGY_L2"),
                "L3": rscpFindTagIndex(res, "PM_ENERGY_L3"),
            },
            "index": pmIndex,
            "maxPhasePower": rscpFindTagIndex(res, "PM_MAX_PHASE_POWER"),
            "mode": rscpFindTagIndex(res, "PM_MODE"),
            "power": {
                "L1": rscpFindTagIndex(res, "PM_POWER_L1"),
                "L2": rscpFindTagIndex(res, "PM_POWER_L2"),
                "L3": rscpFindTagIndex(res, "PM_POWER_L3"),
            },
            "type": rscpFindTagIndex(res, "PM_TYPE"),
            "voltage": {
                "L1": round(rscpFindTagIndex(res, "PM_VOLTAGE_L1"), 4),
                "L2": round(rscpFindTagIndex(res, "PM_VOLTAGE_L2"), 4),
                "L3": round(rscpFindTagIndex(res, "PM_VOLTAGE_L3"), 4),
            },
        }
        return outObj

    def get_powermeters_data(self, powermeters=None, keepAlive=False):
        """Polls the powermeters data via rscp protocol locally.

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

    def get_power_data(self, pmIndex=None, keepAlive=False):
        """DEPRECATED: Please use get_powermeter_data() instead."""
        return self.get_powermeter_data(pmIndex=pmIndex, keepAlive=keepAlive)

    def get_power_settings(self, keepAlive=False):
        """Polls the power settings via rscp protocol locally.

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
            ("EMS_REQ_GET_POWER_SETTINGS", "None", None), keepAlive=keepAlive
        )

        dischargeStartPower = rscpFindTagIndex(res, "EMS_DISCHARGE_START_POWER")
        maxChargePower = rscpFindTagIndex(res, "EMS_MAX_CHARGE_POWER")
        maxDischargePower = rscpFindTagIndex(res, "EMS_MAX_DISCHARGE_POWER")
        powerLimitsUsed = rscpFindTagIndex(res, "EMS_POWER_LIMITS_USED")
        powerSaveEnabled = rscpFindTagIndex(res, "EMS_POWERSAVE_ENABLED")
        weatherForecastMode = rscpFindTagIndex(res, "EMS_WEATHER_FORECAST_MODE")
        weatherRegulatedChargeEnabled = rscpFindTagIndex(
            res, "EMS_WEATHER_REGULATED_CHARGE_ENABLED"
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
        enable,
        max_charge=None,
        max_discharge=None,
        discharge_start=None,
        keepAlive=False,
    ):
        """Setting the SmartPower power limits via rscp protocol locally.

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
                    "EMS_REQ_SET_POWER_SETTINGS",
                    "Container",
                    [
                        ("EMS_POWER_LIMITS_USED", "Bool", True),
                        ("EMS_MAX_DISCHARGE_POWER", "Uint32", max_discharge),
                        ("EMS_MAX_CHARGE_POWER", "Uint32", max_charge),
                        ("EMS_DISCHARGE_START_POWER", "Uint32", discharge_start),
                    ],
                ),
                keepAlive=keepAlive,
            )
        else:
            res = self.sendRequest(
                (
                    "EMS_REQ_SET_POWER_SETTINGS",
                    "Container",
                    [("EMS_POWER_LIMITS_USED", "Bool", False)],
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

    def set_powersave(self, enable, keepAlive=False):
        """Setting the SmartPower power save via rscp protocol locally.

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
                    "EMS_REQ_SET_POWER_SETTINGS",
                    "Container",
                    [("EMS_POWERSAVE_ENABLED", "UChar8", 1)],
                ),
                keepAlive=keepAlive,
            )
        else:
            res = self.sendRequest(
                (
                    "EMS_REQ_SET_POWER_SETTINGS",
                    "Container",
                    [("EMS_POWERSAVE_ENABLED", "UChar8", 0)],
                ),
                keepAlive=keepAlive,
            )

        # validate return code for EMS_RES_POWERSAVE_ENABLED is 0
        if res[2][0][2] == 0:
            return 0
        else:
            return -1

    def set_weather_regulated_charge(self, enable, keepAlive=False):
        """Setting the SmartCharge weather regulated charge via rscp protocol locally.

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
                    "EMS_REQ_SET_POWER_SETTINGS",
                    "Container",
                    [("EMS_WEATHER_REGULATED_CHARGE_ENABLED", "UChar8", 1)],
                ),
                keepAlive=keepAlive,
            )
        else:
            res = self.sendRequest(
                (
                    "EMS_REQ_SET_POWER_SETTINGS",
                    "Container",
                    [("EMS_WEATHER_REGULATED_CHARGE_ENABLED", "UChar8", 0)],
                ),
                keepAlive=keepAlive,
            )

        # validate return code for EMS_RES_WEATHER_REGULATED_CHARGE_ENABLED is 0
        if res[2][0][2] == 0:
            return 0
        else:
            return -1
