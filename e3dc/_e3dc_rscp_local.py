#!/usr/bin/env python
# Python class to connect to an E3/DC system.
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

import copy
import socket
import struct

from ._RSCPEncryptDecrypt import RSCPEncryptDecrypt
from ._rscpLib import RscpMessage, endianSwapUint16, rscpDecode, rscpEncode, rscpFrame
from ._rscpTags import RscpError, RscpTag, RscpType

DEFAULT_PORT = 5033
BUFFER_SIZE = 1024 * 32

# Mirrors the frame header format used by rscpFrameDecode() in _rscpLib.py:
# magic, ctrl, sec1, sec2, ns, length (all little-endian).
_FRAME_HEADER_FMT = "<HHIIIH"
_FRAME_HEADER_SIZE = struct.calcsize(_FRAME_HEADER_FMT)
_FRAME_CRC_SIZE = struct.calcsize("<I")


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

    def __init__(
        self, username: str, password: str, ip: str, key: str, port: int | None = None
    ):
        """Constructor of an E3DC RSCP local object.

        Args:
            username (str): username
            password (str): password (plain text)
            ip (str): IP address of the E3DC system
            key (str): encryption key as set in the E3DC settings
            port (int, optional): port number. Defaults to PORT.
        """
        self.username = username.encode("utf-8")
        self.password = password.encode("utf-8")
        self.ip = ip
        self.port = port or DEFAULT_PORT
        self.key = key.encode("utf-8")
        self.socket: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connected: bool = False
        self.encdec: RSCPEncryptDecrypt
        self.processedData = None

    def _send(self, plainMsg: RscpMessage) -> None:
        sendData = rscpFrame(rscpEncode(plainMsg))
        encData = self.encdec.encrypt(sendData)
        self.socket.send(encData)

    def _receive(self):
        """Read and decrypt a complete RSCP frame.

        A single ``socket.recv()`` call is not guaranteed to return an
        entire frame -- TCP may split larger responses (e.g. an
        extensive ``EH_REQ_GET_SAVED_ERRORS`` history) across multiple
        reads. This keeps reading until the frame length declared in
        the header has been fully received, instead of assuming one
        read is always enough.

        ``RSCPEncryptDecrypt.decrypt()`` is stateful across calls, but
        its default (``previouslyProcessedData=None``) bookkeeping
        only accounts for how much of the *immediately preceding*
        chunk was consumed. That is not accurate once more than one
        chunk has a non-block-aligned leftover, which would silently
        corrupt the result for three or more reads. To stay correct
        regardless of how many reads are needed, each iteration
        re-decrypts the whole accumulated ciphertext from scratch on a
        throwaway copy of the encrypt/decrypt state, and only commits
        the real, persistent ``self.encdec`` state once the full frame
        is known to be available -- matching exactly what happens
        today when a response arrives in a single read.
        """
        ciphertext = b""
        while True:
            chunk = self.socket.recv(BUFFER_SIZE)
            if len(chunk) == 0:
                raise RSCPKeyError
            ciphertext += chunk

            plaintext = copy.copy(self.encdec).decrypt(ciphertext)
            if len(plaintext) < _FRAME_HEADER_SIZE:
                continue

            _, ctrl, _, _, _, length = struct.unpack(
                _FRAME_HEADER_FMT, plaintext[:_FRAME_HEADER_SIZE]
            )
            ctrl = endianSwapUint16(ctrl)
            crc_len = _FRAME_CRC_SIZE if ctrl & 0x10 else 0
            needed = _FRAME_HEADER_SIZE + length + crc_len

            if len(plaintext) >= needed:
                decData = rscpDecode(self.encdec.decrypt(ciphertext))[0]
                return decData

    def sendCommand(self, plainMsg: RscpMessage) -> None:
        """Sending RSCP command.

        Args:
            plainMsg (tuple): plain message
        """
        self.sendRequest(plainMsg)  # same as sendRequest but doesn't return a value

    def sendRequest(self, plainMsg: RscpMessage) -> RscpMessage:
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
            self.socket.connect((self.ip, self.port))
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
