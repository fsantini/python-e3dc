#!/usr/bin/env python
# Python class to connect to an E3/DC system.
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

from __future__ import annotations  # required for python < 3.9

import socket
from typing import Any, Tuple

from ._RSCPEncryptDecrypt import RSCPEncryptDecrypt
from ._rscpLib import rscpDecode, rscpEncode, rscpFrame
from ._rscpTags import RscpError, RscpTag, RscpType

PORT = 5033
BUFFER_SIZE = 1024 * 32


class RSCPAuthenticationError(Exception):
    """Class for RSCP Authentication Error Exception."""

    pass


class RSCPNotAvailableError(Exception):
    """Class for RSCP Not Available Error Exception."""

    pass


class RSCPKeyError(Exception):
    """Class for RSCP Encryption Key Error Exception."""

    pass


class CommunicationError(Exception):
    """Class for Communication Error Exception."""

    pass


class E3DC_RSCP_local:
    """A class describing an E3DC system connection using RSCP protocol locally."""

    def __init__(self, username: str, password: str, ip: str, key: str):
        """Constructor of an E3DC RSCP local object.

        Args:
            username (str): username
            password (str): password (plain text)
            ip (str): IP address of the E3DC system
            key (str): encryption key as set in the E3DC settings
        """
        self.username = username.encode("utf-8")
        self.password = password.encode("utf-8")
        self.ip = ip
        self.key = key.encode("utf-8")
        self.socket: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected: bool = False
        self.encdec: RSCPEncryptDecrypt
        self.processedData = None

    def _send(
        self, plainMsg: Tuple[str | int | RscpTag, str | int | RscpType, Any]
    ) -> None:
        sendData = rscpFrame(rscpEncode(plainMsg))
        encData = self.encdec.encrypt(sendData)
        self.socket.send(encData)

    def _receive(self):
        data = self.socket.recv(BUFFER_SIZE)
        if len(data) == 0:
            raise RSCPKeyError
        decData = rscpDecode(self.encdec.decrypt(data))[0]
        return decData

    def sendCommand(
        self, plainMsg: Tuple[str | int | RscpTag, str | int | RscpType, Any]
    ) -> None:
        """Sending RSCP command.

        Args:
            plainMsg (tuple): plain message
        """
        self.sendRequest(plainMsg)  # same as sendRequest but doesn't return a value

    def sendRequest(
        self, plainMsg: Tuple[str | int | RscpTag, str | int | RscpType, Any]
    ) -> Tuple[str | int | RscpTag, str | int | RscpType, Any]:
        """Sending RSCP request.

        Args:
            plainMsg (tuple): plain message

        Returns:
            tuple: received message
        """
        try:
            self._send(plainMsg)
            receive = self._receive()
        except RSCPKeyError:
            self.disconnect()
            raise
        except Exception:
            self.disconnect()
            raise CommunicationError

        if receive[1] == "Error":
            self.disconnect()
            if receive[2] == RscpError.RSCP_ERR_ACCESS_DENIED.name:
                raise RSCPAuthenticationError
            elif receive[2] == RscpError.RSCP_ERR_NOT_AVAILABLE.name:
                raise RSCPNotAvailableError
            else:
                raise CommunicationError(receive[2])
        return receive

    def connect(self) -> None:
        """Establishes connection to the E3DC system."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)
            self.socket.connect((self.ip, PORT))
            self.processedData = None
            self.connected = True
        except Exception:
            self.disconnect()
            raise CommunicationError
        self.encdec = RSCPEncryptDecrypt(self.key)

        self.sendRequest(
            (
                RscpTag.RSCP_REQ_AUTHENTICATION,
                RscpType.Container,
                [
                    (RscpTag.RSCP_AUTHENTICATION_USER, RscpType.CString, self.username),
                    (
                        RscpTag.RSCP_AUTHENTICATION_PASSWORD,
                        RscpType.CString,
                        self.password,
                    ),
                ],
            )
        )

    def disconnect(self) -> None:
        """Disconnects from the E3DC system."""
        self.socket.close()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected = False

    def isConnected(self) -> bool:
        """Validate connection status.

        Returns:
            bool: true if connected
        """
        return self.connected
