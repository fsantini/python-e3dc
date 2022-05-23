# python-e3dc

[![PyPI version](https://badge.fury.io/py/pye3dc.svg)](https://badge.fury.io/py/pye3dc)
[![GitHub license](https://img.shields.io/github/license/fsantini/python-e3dc)](https://github.com/fsantini/python-e3dc/blob/master/LICENSE)
[![Codestyle](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**NOTE: With Release 0.6.0 at least Python 3.7 is required**

Python API for querying an [E3/DC](https://e3dc.de/) systems

This is supported either directly via RSCP connection or through the manufacturer's portal. The RSCP implementation has currently the most capabilities.

In order to use it you need:
- Your user name
- Your password
- The IP address of the E3/DC system
- The RSCP Password (encryption key), as set on the device under Main Page -> Personalize -> User profile -> RSCP password

Alternatively, for a web connection, you need:
- Your user name
- Your password
- The serial number of the system, which can be found when logging into the E3/DC webpage.

## Installation

This package can be installed from pip:

`pip install pye3dc`

## Local Connection

### Configuration

There is a great variety of E3/DC implementation configurations, that can't automatically be detected. For example the `index` of the root power meter can be either `0` or `6`, depending how the system was installed. Additional power meter can have an ID of `1-4` and there might be also multiple inverter.
This library assumes, that there is one inverter installed and the root power meter has an index of `6` for S10 mini and `0` for other systems.

For any other configurations, there is an optional `configuration` object that can be used to alter the defaults:

```
{
  "pvis": [
    {
      "index": 0,
      "strings": 2,
      "phases": 3
    }
  ],
  "powermeters": [
    {
      "index": 6
    }
  ],
  "batteries": [
    {
      "index": 0,
      "dcbs": 2
    }
  ]
}
```

> Note: Not all options need to be configured.

### Usage

An example script using the library is the following:

```python
from e3dc import E3DC

TCP_IP = '192.168.1.57'
USERNAME = 'test@test.com'
PASS = 'MySecurePassword'
KEY = 'abc123'
CONFIG = {} 
# CONFIG = {"powermeters": [{"index": 6}]}

print("local connection")
e3dc = E3DC(E3DC.CONNECT_LOCAL, username=USERNAME, password=PASS, ipAddress = TCP_IP, key = KEY, configuration = CONFIG)
# The following connections are performed through the RSCP interface
print(e3dc.poll())
print(e3dc.get_pvi_data())
```

### poll() return values

Poll returns a dictionary like the following:
```python
{
    'autarky': 100,
    'consumption': {
        'battery': 470,
        'house': 477,
        'wallbox': 0
    },
    'production': {
        'solar' : 951,
        'add' : 0,
        'grid' : -4
    },
    'stateOfCharge': 77,
    'selfConsumption': 100,
    'time': datetime.datetime(2021, 8, 14, 7, 6, 13)
}
```

### Available methods

* `poll()`
* `get_system_info()`
* `get_system_status()`
* `poll_switches()`
* `get_idle_periods()`
* `set_idle_periods()`
* `get_db_data()`
* `get_battery_data()`
* `get_batteries_data()`
* `get_pvi_data()`
* `get_pvis_data()`
* `get_powermeter_data()`
* `get_powermeters_data()`
* `get_power_settings()`
* `set_power_limits()`
* `set_powersave()`
* `set_weather_regulated_charge()`

> A documentation for these methods is not yet generated. Please have a look at the docstrings in  `_e3dc.py` for details.

### Note: The RSCP interface

The communication to an E3/DC system has to be implemented via a rather complicated protocol, called by E3/DC RSCP. This protocol is binary and based on websockets. The documentation provided by E3/DC is limited and outdated. It can be found in the E3/DC download portal.

If keepAlive is false, the websocket connection is closed after the command. This makes sense because these requests are not meant to be made as often as the status requests, however, if keepAlive is True, the connection is left open and kept alive in the background in a separate thread.

## Web connection

### Usage

An example script using the library is the following:

```python
from e3dc import E3DC

TCP_IP = '192.168.1.57'
USERNAME = 'test@test.com'
PASS = 'MySecurePassword'
SERIALNUMBER = '1234567890'

print("web connection")
e3dc = E3DC(E3DC.CONNECT_WEB, username=USERNAME, password=PASS, serialNumber = SERIALNUMBER, isPasswordMd5=False)
# connect to the portal and poll the status. This might raise an exception in case of failed login. This operation is performed with Ajax
print(e3dc.poll())
# Poll the status of the switches using a remote RSCP connection via websockets
# return value is in the format {'id': switchID, 'type': switchType, 'name': switchName, 'status': switchStatus}
print(e3dc.poll_switches())
```

## Known limitations

One limitation of the package concerns the implemented RSCP methods. This project also lacks the hardware to test different configurations. However, the RSCP protocol is fully implemented and it should be easy to extend the requests to other use cases.

## Projects using this library

* [e3dc-rest](https://github.com/vchrisb/e3dc-rest): a simple REST API to access an E3/DC system
* [e3dc-to-mqtt](https://github.com/mdhom/e3dc-to-mqtt): publish E3/DC data via MQTT

## Contribution

* open an issue before making a pull request
* note the E3/DC system you tested with and implementation details
* pull request checks will enforce code styling (black, flake8, isort)
* consider adding yourself to `AUTHORS`

## Copyright notice

The Rijndael algorithm comes from the python-cryptoplus package by Philippe Teuwen (https://github.com/doegox/python-cryptoplus) and distributed under a MIT license.
