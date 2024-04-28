# python-e3dc

[![PyPI version](https://badge.fury.io/py/pye3dc.svg)](https://badge.fury.io/py/pye3dc)
[![GitHub license](https://img.shields.io/github/license/fsantini/python-e3dc)](https://github.com/fsantini/python-e3dc/blob/master/LICENSE)
[![Codestyle](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Documentation Status](https://readthedocs.org/projects/python-e3dc/badge/?version=latest)](https://python-e3dc.readthedocs.io/en/latest/?badge=latest)

**NOTE: With Release 0.8.0 at least Python 3.8 is required**

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

## Configuration

There is a great variety of E3/DC implementation configurations, that can't automatically be detected. For example the `index` of the root power meter can be either `0` or `6`, depending how the system was installed. Additional power meter can have an ID of `1-4` and there might be also multiple inverter.
This library assumes, that there is one inverter installed and the root power meter has an index of `6` for S10 mini and `0` for other systems.

For any other configurations, there is an optional `configuration` object that can be used to alter the defaults:

```python
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

## Usage

### Local Connection

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
e3dc_obj = E3DC(E3DC.CONNECT_LOCAL, username=USERNAME, password=PASS, ipAddress = TCP_IP, key = KEY, configuration = CONFIG)
# The following connections are performed through the RSCP interface
print(e3dc_obj.poll(keepAlive=True))
print(e3dc_obj.get_pvi_data(keepAlive=True))
e3dc_obj.disconnect()
```

### Web Connection

An example script using the library is the following:

```python
from e3dc import E3DC

USERNAME = 'test@test.com'
PASS = 'MySecurePassword'
SERIALNUMBER = 'S10-012345678910'
CONFIG = {}

print("web connection")
e3dc_obj = E3DC(E3DC.CONNECT_WEB, username=USERNAME, password=PASS, serialNumber = SERIALNUMBER, isPasswordMd5=False, configuration = CONFIG)
# connect to the portal and poll the status. This might raise an exception in case of failed login. This operation is performed with Ajax
print(e3dc_obj.poll(keepAlive=True))
print(e3dc_obj.get_pvi_data(keepAlive=True))
e3dc_obj.disconnect()
```

## Example: poll() return values

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

## Available methods

- `poll()`
- `get_system_info()`
- `get_system_status()`
- `poll_switches()`
- `get_idle_periods()`
- `set_idle_periods()`
- `get_db_data()`
- `get_batteries()`
- `get_battery_data()`
- `get_batteries_data()`
- `get_pvis()`
- `get_pvi_data()`
- `get_pvis_data()`
- `get_powermeters()`
- `get_powermeter_data()`
- `get_powermeters_data()`
- `get_power_settings()`
- `get_wallbox_data()`
- `set_battery_to_car_mode()`
- `set_power_limits()`
- `set_powersave()`
- `set_wallbox_max_charge_current()`
- `set_wallbox_schuko()`
- `set_wallbox_sunmode()`
- `set_weather_regulated_charge()`
- `toggle_wallbox_charging()`
- `toggle_wallbox_phases()`

- `sendWallboxRequest()`
- `sendWallboxSetRequest()`

See the full documentation on [ReadTheDocs](https://python-e3dc.readthedocs.io/en/latest/)

## Note: The RSCP interface

The communication to an E3/DC system has to be implemented via a rather complicated protocol, called by E3/DC RSCP. This protocol is binary and based on websockets. The documentation provided by E3/DC is limited and outdated. It can be found in the E3/DC download portal.

If keepAlive is false, the websocket connection is closed after the command. This makes sense because these requests are not meant to be made as often as the status requests, however, if keepAlive is True, the connection is left open and kept alive in the background in a separate thread.


## Known limitations

One limitation of the package concerns the implemented RSCP methods. This project also lacks the hardware to test different configurations. However, the RSCP protocol is fully implemented and it should be easy to extend the requests to other use cases.

## Projects using this library

- [e3dc-rest](https://github.com/vchrisb/e3dc-rest): a simple REST API to access an E3/DC system
- [e3dc-to-mqtt](https://github.com/mdhom/e3dc-to-mqtt): publish E3/DC data via MQTT
- [weewx-photovoltaics](https://github.com/roe-dl/weewx-photovoltaics): Extension to WeeWX for processing data of the photovoltaics system E3/DC
- [hacs-e3dc](https://github.com/torbennehmer/hacs-e3dc): HACS Version of the E3DC Home Assistant integration

## Contribution

- Open an issue before making a pull request
- Note the E3/DC system you tested with and implementation details
- Pull request checks will enforce code styling
  - Install development dependencies `pip install -U --upgrade-strategy eager .[develop]`
  - Run `tools/validate.sh` before creating a commit.
- Make sure to support Python versions >= 3.8
- Consider adding yourself to `AUTHORS`
