"""A simple python script to test the e3dc module."""

import argparse
import json
from datetime import date, datetime

from e3dc import E3DC


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))


def printJson(obj):
    """Print a json object with a datetime obect."""
    print(json.dumps(obj, indent=2, default=json_serial))


parser = argparse.ArgumentParser(description="E3DC tests")
parser.add_argument("-c", "--config", help="config of E3DC", default="{}")
requiredNamed = parser.add_argument_group("required named arguments")
requiredNamed.add_argument(
    "-i", "--ipaddress", help="IP address of E3DC", required=True
)
requiredNamed.add_argument("-u", "--username", help="username of E3DC", required=True)
requiredNamed.add_argument("-p", "--password", help="password of E3DC", required=True)
requiredNamed.add_argument("-k", "--key", help="key of E3DC", required=True)
args = vars(parser.parse_args())

e3dc = E3DC(
    E3DC.CONNECT_LOCAL,
    ipAddress=args["ipaddress"],
    username=args["username"],
    password=args["password"],
    key=args["key"],
    configuration=json.loads(args["config"]),
)

methods = [
    "poll",
    "poll_switches",
    "get_idle_periods",
    "get_db_data",
    "get_system_info",
    "get_system_status",
    "get_battery_data",
    "get_batteries_data",
    "get_pvi_data",
    "get_pvis_data",
    "get_powermeters",
    "get_powermeter_data",
    "get_powermeters_data",
    "get_power_settings",
]

for method in methods:
    print(method + "():")
    method = getattr(e3dc, method)
    printJson(method(keepAlive=True))
    print()
