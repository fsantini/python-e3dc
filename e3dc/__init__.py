"""

   E3DC Library for Python

    Python class to connect to an E3/DC system through the internet portal
    Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
    Licensed under a MIT license. See LICENSE for details

"""

from ._e3dc import E3DC, AuthenticationError, PollError
from ._e3dc_rscp_web import SocketNotReady, RequestTimeoutError
from ._e3dc_rscp_local import RSCPAuthenticationError, CommunicationError
from ._rscpLib import FrameError



__version__ = "0.5.2"
