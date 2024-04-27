#!/usr/bin/env python
# Python class to connect to an E3/DC system.
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details
from __future__ import annotations  # required for python < 3.9

import datetime
import hashlib
import struct
import threading
import time
from typing import Any, Callable, Tuple

import tzlocal
from websocket import ABNF, WebSocketApp

from ._rscpLib import (
    rscpDecode,
    rscpEncode,
    rscpFindTag,
    rscpFindTagIndex,
    rscpFrame,
    rscpFrameDecode,
)
from ._rscpTags import RscpTag, RscpType, getRscpTag

"""
 The connection works the following way: (> outgoing, < incoming)

> [connect]
< SERVER_REGISTER_CONNECTION (conId, authLevel)
> SERVER_CONNECTION_REGISTERED
< SERVER_REQ_RSCP_CMD (information request from server)
> SERVER_REQ_RSCP_CMD (information back)
< INFO_SERIAL_NUMBER (webSerialno)
> SERVER_REQ_NEW_VIRTUAL_CONNECTION (username, password, sn)
< SERVER_REGISTER_CONNECTION (virtConId, virtAuthLevel)
> SERVER_CONNECTION_REGISTERED

 the connection is now established
 
 Communication is through SERVER_REQ_RSCP_CMD which is a container with:
 virtConId, virtAuthLevel, innerFrame
 
 and the innerframe is an RSCP frame with the appropriate command (HA_REQ_ACTUATOR_STATES for example)
 
"""

REMOTE_ADDRESS = "wss://s10.e3dc.com/ws"


class SocketNotReady(Exception):
    """Class for Socket Not Ready Exception."""

    pass


class RequestTimeoutError(Exception):
    """Class for Request Timeout Error Exception."""

    pass


def calcTimeZone():
    """Method to calculate time zone.

    Returns:
        str: timezone string
        int: UTC diff
    """
    localtz = tzlocal.get_localzone()
    naiveNow = datetime.datetime.now()
    utcDiff = localtz.utcoffset(naiveNow)  # this is a timedelta
    utcDiffS = utcDiff.total_seconds() if utcDiff else 0
    utcDiffH = int(utcDiffS / 60 / 60)  # this is local - utc (eg 2 = UTC+2)
    TIMEZONE_STR = "GMT" + ("+" if utcDiffH > 0 else "-") + str(abs(utcDiffH))
    return TIMEZONE_STR, utcDiffS


def timestampEncode(ts: float):
    """Method to encode timestamp.

    Args:
        ts (time): timestamp

    """
    sec = float(int(ts))
    ms = int((ts - sec) * 1000)
    return struct.pack("<dI", sec, ms)


class E3DC_RSCP_web:
    """A class describing an E3DC system connection using RSCP protocol over web."""

    TIMEOUT = 10  # timeout in sec

    def __init__(
        self,
        username: str,
        password: str,
        serialNumberWithPrefix: str,
        isPasswordMd5: bool = True,
    ):
        """Constructor of an E3DC RSCP web object.

        Args:
            username (string): the user name to the E3DC portal
            password (string): the password (as md5 digest by default)
            serialNumberWithPrefix (string): the serial number of the system to monitor
            isPasswordMd5 (boolean, optional): indicates whether the password is already md5 digest (recommended, default = True)
        """
        self.username = username.encode("utf-8")
        self.password = password.encode("utf-8")
        if isPasswordMd5:
            self.password = password
        else:
            self.password = hashlib.md5(bytes(password, "UTF-8")).hexdigest()

        self.serialNumberWithPrefix = serialNumberWithPrefix.encode("utf-8")
        self.ws = WebSocketApp(
            REMOTE_ADDRESS,
            on_message=lambda _, msg: self.on_message(msg),
            on_close=lambda _ws, _, __: self.reset(),
            on_error=lambda _ws, _: self.reset(),
        )
        self.reset()

    def reset(self):
        """Method to reset E3DC rscp web instance."""
        self.ws.close()  # pyright: ignore [reportUnknownMemberType]
        self.conId: int = 0
        self.authLevel = None
        self.virtConId = None
        self.virtAuthLevel = None
        self.webSerialno = None
        self.responseCallback: Callable[
            [Tuple[str | int | RscpTag, str | int | RscpType, Any]], None
        ]
        self.responseCallbackCalled = False
        self.requestResult: Tuple[str | int | RscpTag, str | int | RscpType, Any]

    def buildVirtualConn(self):
        """Method to create Virtual Connection."""
        virtualConn = rscpFrame(
            rscpEncode(
                RscpTag.SERVER_REQ_NEW_VIRTUAL_CONNECTION,
                RscpType.Container,
                [
                    (RscpTag.SERVER_USER, RscpType.CString, self.username),
                    (RscpTag.SERVER_PASSWD, RscpType.CString, self.password),
                    (
                        RscpTag.SERVER_IDENTIFIER,
                        RscpType.CString,
                        self.serialNumberWithPrefix,
                    ),
                    (RscpTag.SERVER_TYPE, RscpType.Int32, 4),
                    (RscpTag.SERVER_HASH_CODE, RscpType.Int32, 1234567890),
                ],
            )
        )

        # print("--------------------- Sending virtual conn")
        self.ws.send(virtualConn, ABNF.OPCODE_BINARY)

    def respondToINFORequest(
        self, decoded: Tuple[str | int | RscpTag, str | int | RscpType, Any]
    ):
        """Create Response to INFO request."""
        TIMEZONE_STR, utcDiffS = calcTimeZone()

        try:
            tag = getRscpTag(decoded[0])
        except KeyError:
            # This is a tag unknown to this library
            return None

        if tag == RscpTag.INFO_REQ_IP_ADDRESS:
            return rscpEncode(RscpTag.INFO_IP_ADDRESS, RscpType.CString, "0.0.0.0")
        elif tag == RscpTag.INFO_REQ_SUBNET_MASK:
            return rscpEncode(RscpTag.INFO_SUBNET_MASK, RscpType.CString, "0.0.0.0")
        elif tag == RscpTag.INFO_REQ_GATEWAY:
            return rscpEncode(RscpTag.INFO_GATEWAY, RscpType.CString, "0.0.0.0")
        elif tag == RscpTag.INFO_REQ_DNS:
            return rscpEncode(RscpTag.INFO_DNS, RscpType.CString, "0.0.0.0")
        elif tag == RscpTag.INFO_REQ_DHCP_STATUS:
            return rscpEncode(RscpTag.INFO_DHCP_STATUS, RscpType.Bool, "false")
        elif tag == RscpTag.INFO_REQ_TIME:
            return rscpEncode(
                RscpTag.INFO_TIME, RscpType.ByteArray, timestampEncode(time.time())
            )
        elif tag == RscpTag.INFO_REQ_TIME_ZONE:
            return rscpEncode(RscpTag.INFO_TIME_ZONE, RscpType.CString, TIMEZONE_STR)
        elif tag == RscpTag.INFO_REQ_UTC_TIME:
            return rscpEncode(
                RscpTag.INFO_UTC_TIME,
                RscpType.ByteArray,
                timestampEncode(time.time() - utcDiffS),
            )
        elif tag == RscpTag.INFO_REQ_A35_SERIAL_NUMBER:
            return rscpEncode(
                RscpTag.INFO_A35_SERIAL_NUMBER, RscpType.CString, "123456"
            )
        elif tag == RscpTag.INFO_REQ_INFO:
            return rscpEncode(
                RscpTag.INFO_INFO,
                RscpType.Container,
                [
                    (
                        RscpTag.INFO_SERIAL_NUMBER,
                        RscpType.CString,
                        "WEB_"
                        + hashlib.md5(self.username + bytes(self.conId)).hexdigest(),
                    ),
                    (
                        RscpTag.INFO_PRODUCTION_DATE,
                        RscpType.CString,
                        "570412800000",
                    ),
                    (
                        RscpTag.INFO_MAC_ADDRESS,
                        RscpType.CString,
                        "00:00:00:00:00:00",
                    ),
                ],
            )
        elif tag == RscpTag.INFO_SERIAL_NUMBER:
            self.webSerialno = decoded[2]
            self.buildVirtualConn()
            return ""
        return None  # this is no standard request

    def registerConnectionHandler(
        self, decodedMsg: Tuple[str | int | RscpTag, str | int | RscpType, Any]
    ):
        """Registering Connection Handler."""
        if self.conId == 0:
            self.conId = rscpFindTagIndex(decodedMsg, RscpTag.SERVER_CONNECTION_ID)
            self.authLevel = rscpFindTagIndex(decodedMsg, RscpTag.SERVER_AUTH_LEVEL)
        else:
            self.virtConId = rscpFindTagIndex(decodedMsg, RscpTag.SERVER_CONNECTION_ID)
            self.virtAuthLevel = rscpFindTagIndex(decodedMsg, RscpTag.SERVER_AUTH_LEVEL)
        # reply = rscpFrame(rscpEncode(RscpTag.SERVER_CONNECTION_REGISTERED, RscpType.Container, [decodedMsg[2][0], decodedMsg[2][1]]));
        reply = rscpFrame(
            rscpEncode(
                RscpTag.SERVER_CONNECTION_REGISTERED,
                RscpType.Container,
                [
                    rscpFindTag(decodedMsg, RscpTag.SERVER_CONNECTION_ID),
                    rscpFindTag(decodedMsg, RscpTag.SERVER_AUTH_LEVEL),
                ],
            )
        )
        self.ws.send(reply, ABNF.OPCODE_BINARY)

    def on_message(self, message: bytes):
        """Method to handle a received message."""
        # print "Received message", message
        if len(message) == 0:
            return

        decodedMsg = rscpDecode(message)[0]
        try:
            tag = getRscpTag(decodedMsg[0])
        except KeyError:
            # This is a tag unknown to this library
            raise

        # print "Decoded received message", decodedMsg
        if tag == RscpTag.SERVER_REQ_PING:
            pingFrame = rscpFrame(
                rscpEncode(RscpTag.SERVER_PING, RscpType.NoneType, None)
            )
            self.ws.send(
                pingFrame,
                ABNF.OPCODE_BINARY,
            )
            return
        elif tag == RscpTag.SERVER_REGISTER_CONNECTION:
            self.registerConnectionHandler(decodedMsg)
        elif tag == RscpTag.SERVER_UNREGISTER_CONNECTION:
            # this signifies some error
            self.disconnect()
        elif tag == RscpTag.SERVER_REQ_RSCP_CMD:
            data = rscpFrameDecode(
                rscpFindTagIndex(decodedMsg, RscpTag.SERVER_RSCP_DATA)
            )[0]
            response = b""
            self.responseCallbackCalled = False
            while len(data) > 0:
                (
                    decoded,
                    size,  # pyright: ignore [reportUnusedVariable]
                ) = rscpDecode(data)
                # print "Inner frame chunk decoded", decoded
                data = data[size:]
                responseChunk = self.respondToINFORequest(decoded)
                if responseChunk is None:
                    # this is not a standard request: call the registered callback

                    self.responseCallback(
                        decoded
                    )  # !!! Important!!! This is where the callback is called with the decoded inner frame
                    self.responseCallbackCalled = True
                    responseChunk = b""

                if isinstance(responseChunk, str):
                    responseChunk = responseChunk.encode("utf-8")
                response += responseChunk
            if len(response) == 0:
                return  # do not send an empty response
            innerFrame = rscpFrame(response)
            responseContainer = rscpEncode(
                RscpTag.SERVER_REQ_RSCP_CMD,
                RscpType.Container,
                [
                    (RscpTag.SERVER_CONNECTION_ID, RscpType.Int64, self.conId),
                    (RscpTag.SERVER_AUTH_LEVEL, RscpType.UChar8, self.authLevel),
                    (RscpTag.SERVER_RSCP_DATA_LEN, RscpType.Int32, len(innerFrame)),
                    (RscpTag.SERVER_RSCP_DATA, RscpType.ByteArray, innerFrame),
                ],
            )

            self.ws.send(
                rscpFrame(responseContainer),
                ABNF.OPCODE_BINARY,
            )

    def _defaultRequestCallback(
        self, msg: Tuple[str | int | RscpTag, str | int | RscpType, Any]
    ):
        self.requestResult = msg

    def sendRequest(
        self, message: Tuple[str | int | RscpTag, str | int | RscpType, Any]
    ) -> Tuple[str | int | RscpTag, str | int | RscpType, Any]:
        """Send a request and wait for a response."""
        self._sendRequest_internal(rscpFrame(rscpEncode(message)))
        for _ in range(self.TIMEOUT * 10):
            if self.responseCallbackCalled:
                break
            time.sleep(0.1)
        if not self.responseCallbackCalled:
            raise RequestTimeoutError

        return self.requestResult

    def sendCommand(
        self, message: Tuple[str | int | RscpTag, str | int | RscpType, Any]
    ):
        """Send a command."""
        return self._sendRequest_internal(rscpFrame(rscpEncode(message)))

    def _sendRequest_internal(
        self,
        innerFrame: bytes | Tuple[str | int | RscpTag, str | int | RscpType, Any],
        callback: (
            Callable[[Tuple[str | int | RscpTag, str | int | RscpType, Any]], None]
            | None
        ) = None,
    ):
        """Internal send request method.

        Args:
            innerFrame (Union[tuple, <RSCP encoded frame>]): inner frame
            callback (str): callback method
            synchronous (bool): If True, the method waits for a response (i.e. exits after calling callback).
                If True and callback = None, the method returns the (last) response message
        """
        if not self.isConnected():
            raise SocketNotReady

        if isinstance(innerFrame, tuple):
            # if innerframe is a tuple then the message is not encoded
            innerFrame = rscpFrame(rscpEncode(*innerFrame))

        # self.requestResult = None
        self.responseCallbackCalled = False
        if callback is None:
            self.responseCallback = lambda msg: self._defaultRequestCallback(msg)  # type: ignore
        else:
            self.responseCallback = callback

        outerFrame = rscpFrame(
            rscpEncode(
                RscpTag.SERVER_REQ_RSCP_CMD,
                RscpType.Container,
                [
                    (RscpTag.SERVER_CONNECTION_ID, RscpType.Int64, self.virtConId),
                    (
                        RscpTag.SERVER_AUTH_LEVEL,
                        RscpType.UChar8,
                        self.virtAuthLevel,
                    ),
                    (RscpTag.SERVER_RSCP_DATA_LEN, RscpType.Int32, len(innerFrame)),
                    (RscpTag.SERVER_RSCP_DATA, RscpType.ByteArray, innerFrame),
                ],
            )
        )

        self.ws.send(outerFrame, ABNF.OPCODE_BINARY)

    def connect(self):
        """Connect to E3DC system."""
        self.reset()
        self.thread = threading.Thread(
            target=self.ws.run_forever  # pyright: ignore [reportUnknownMemberType, reportUnknownArgumentType]
        )

        self.thread.start()

        for _ in range(self.TIMEOUT * 10):
            if self.isConnected():
                break
            time.sleep(0.1)
        if not self.isConnected():
            raise RequestTimeoutError

    def disconnect(self):
        """Disconnect from E3DC system."""
        self.reset()

    def isConnected(self):
        """Validate connection status.

        Returns:
            bool: true if connected
        """
        return self.virtConId is not None
