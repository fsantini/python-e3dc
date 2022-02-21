"""E3DC Library for Python.

Python class to connect to an E3/DC system.
Copyright 2017 Francesco Santini <francesco.santini@gmail.com>.
Licensed under a MIT license. See LICENSE for details.
"""

from ._e3dc import E3DC, AuthenticationError, PollError
from ._e3dc_rscp_local import CommunicationError, RSCPAuthenticationError
from ._e3dc_rscp_web import RequestTimeoutError, SocketNotReady
from ._rscpLib import FrameError

__all__ = [
    "E3DC",
    "AuthenticationError",
    "PollError",
    "CommunicationError",
    "RSCPAuthenticationError",
    "RequestTimeoutError",
    "SocketNotReady",
    "FrameError",
]
__version__ = "0.7.0"
