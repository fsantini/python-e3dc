"""A simple python script to test the e3dc module."""

import argparse
import json
import re
from datetime import date, datetime


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))


def printJson(obj):
    """Print a json object with a datetime obect."""
    output = json.dumps(obj, indent=2, default=json_serial)
    output = re.sub(r"(.*\"serial.*\": \")(.*)(\",*)", r"\1redacted\3", output, re.M)
    output = re.sub(r"(.*\"serial.*\": )(\d+)(,*)", r"\g<1>0\g<3>", output, re.M)
    print(output)


parser = argparse.ArgumentParser(description="E3DC tests")
parser.add_argument("-c", "--configuration", help="configuration of E3DC", default="{}")
parser.add_argument(
    "-m",
    "--module",
    action="store_false",
    help="use locally installed E3DC module for test",
)
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    help="use local E3DC module for test",
)
requiredNamed = parser.add_argument_group("required named arguments")
requiredNamed.add_argument("-u", "--username", help="username of E3DC", required=True)
requiredNamed.add_argument("-p", "--password", help="password of E3DC", required=True)

requiredNamedLocal = parser.add_argument_group(
    "required named arguments for local connection"
)
requiredNamedLocal.add_argument("-i", "--ipaddress", help="IP address of E3DC")
requiredNamedLocal.add_argument("-k", "--key", help="rscp key of E3DC")

requiredNamedWeb = parser.add_argument_group(
    "required named arguments for web connection"
)
requiredNamedWeb.add_argument("-s", "--serialnumber", help="serialnumber of E3DC")

args = vars(parser.parse_args())

if args["serialnumber"] and (args["ipaddress"] or args["key"]):
    print("either provide require arguments for web or local connection")
    exit(2)
elif args["serialnumber"] is None and not (args["ipaddress"] and args["key"]):
    print("for local connection ipaddress and key are required")
    exit(2)

if args["module"]:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import e3dc

    if args["verbose"]:
        print("Running Test for E3DC from sources!\n")
else:
    import e3dc

    if args["verbose"]:
        print("Running Test for E3DC {}\n".format(e3dc.__version__))

if args["serialnumber"]:
    e3dc_obj = e3dc.E3DC(
        e3dc.E3DC.CONNECT_WEB,
        username=args["username"],
        password=args["password"],
        serialNumber=args["serialnumber"],
        configuration=json.loads(args["configuration"]),
    )
else:
    e3dc_obj = e3dc.E3DC(
        e3dc.E3DC.CONNECT_LOCAL,
        ipAddress=args["ipaddress"],
        username=args["username"],
        password=args["password"],
        key=args["key"],
        configuration=json.loads(args["configuration"]),
    )

methods = [
    "poll",
    "poll_switches",
    "get_idle_periods",
    "get_db_data",
    "get_system_info",
    "get_system_status",
    "get_batteries",
    "get_battery_data",
    "get_batteries_data",
    "get_pvis",
    "get_pvi_data",
    "get_pvis_data",
    "get_powermeters",
    "get_powermeter_data",
    "get_powermeters_data",
    "get_power_settings",
]

for method in methods:
    if args["verbose"]:
        print("\n" + method + "():")
    method = getattr(e3dc_obj, method)
    printJson(method(keepAlive=True))

e3dc_obj.disconnect()
