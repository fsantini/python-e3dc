#!/usr/bin/env python
# Python class to connect to an E3/DC system.
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

import socket

from ._RSCPEncryptDecrypt import RSCPEncryptDecrypt
from ._rscpLib import rscpDecode, rscpEncode, rscpFrame

PORT = 5033
BUFFER_SIZE = 1024 * 32


class RSCPAuthenticationError(Exception):
    """Class for RSCP Authentication Error Exception."""

    pass


class RSCPNotAvailableError(Exception):
    """Class for RSCP Not Available Error Exception."""

    pass


class CommunicationError(Exception):
    """Class for Communication Error Exception."""

    pass


class E3DC_RSCP_local:
    """A class describing an E3DC system connection using RSCP protocol locally."""

    def __init__(self, username, password, ip, key):
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
        self.socket = None
        self.encdec = None
        self.processedData = None

    def _send(self, plainMsg):
        sendData = rscpFrame(rscpEncode(plainMsg))
        encData = self.encdec.encrypt(sendData)
        self.socket.send(encData)

    def _receive(self):
        data = self.socket.recv(BUFFER_SIZE)
        decData = rscpDecode(self.encdec.decrypt(data))[0]
        return decData

    def sendCommand(self, plainMsg):
        """Sending RSCP command.

        Args:
            plainMsg (tuple): plain message
        """
        self.sendRequest(plainMsg)  # same as sendRequest but doesn't return a value

    def sendRequest(self, plainMsg):
        """Sending RSCP request.

        Args:
            plainMsg (tuple): plain message

        Returns:
            tuple: received message
        """
        try:
            self._send(plainMsg)
            receive = self._receive()
        except:
            self.disconnect()
            raise CommunicationError

        if receive[1] == "Error":
            self.disconnect()
            if receive[2] == "RSCP_ERR_ACCESS_DENIED":
                raise RSCPAuthenticationError
            elif receive[2] == "RSCP_ERR_NOT_AVAILABLE":
                raise RSCPNotAvailableError
            else:
                raise CommunicationError(receive[2])
        return receive

    def connect(self):
        """Establishes connection to the E3DC system."""
        if self.socket is not None:
            self.disconnect()
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)
            self.socket.connect((self.ip, PORT))
            self.processedData = None
        except:
            self.disconnect()
            raise CommunicationError
        self.encdec = RSCPEncryptDecrypt(self.key)

        self.sendRequest(
            (
                "RSCP_REQ_AUTHENTICATION",
                "Container",
                [
                    ("RSCP_AUTHENTICATION_USER", "CString", self.username),
                    ("RSCP_AUTHENTICATION_PASSWORD", "CString", self.password),
                ],
            )
        )

    def disconnect(self):
        """Disconnects from the E3DC system."""
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def isConnected(self):
        """Validate connection status.

        Returns:
            bool: true if connected
        """
        return self.socket is not None
