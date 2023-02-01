"""E3DC Library for Python.

Python class to connect to an E3/DC system.
Copyright 2017 Francesco Santini <francesco.santini@gmail.com>.
Licensed under a MIT license. See LICENSE for details.
"""

from ._e3dc import E3DC, AuthenticationError, PollError
from ._e3dc_rscp_local import CommunicationError, RSCPAuthenticationError, RSCPKeyError
from ._e3dc_rscp_web import RequestTimeoutError, SocketNotReady
from ._rscpLib import FrameError
from ._rscpLib import set_debug as set_rscp_debug

__all__ = [
    "E3DC",
    "AuthenticationError",
    "PollError",
    "CommunicationError",
    "RSCPAuthenticationError",
    "RSCPKeyError",
    "RequestTimeoutError",
    "SocketNotReady",
    "FrameError",
    "set_rscp_debug",
]
__version__ = "0.7.4"
