"""A simple python script to test the e3dc module with various python versions in docker."""

import argparse
import json
from pathlib import Path

import docker


class Testcontainers:
    """A class to run commands in a python container."""

    container = ""
    version = ""

    def __init__(
        self,
        ipAddress,
        username,
        password,
        configuration,
        key="",
        serialNumber="",
        version="3.8",
    ):
        """The init method for Testcontainers."""
        client = docker.from_env()
        self.version = version
        image_name = "python:" + version
        container_name = "python-e3dc-" + version
        client.images.pull(image_name)
        try:
            client.containers.get(container_name).remove(force=True)
        except docker.errors.NotFound:
            pass
        self.container = client.containers.run(
            image_name,
            name=container_name,
            stdin_open=True,
            remove=True,
            detach=True,
            volumes=[str(Path(__file__).resolve().parents[1]) + ":/pye3dc"],
            working_dir="/pye3dc",
            environment={
                "IPADDRESS": ipAddress,
                "USERNAME": username,
                "PASSWORD": password,
                "KEY": key,
                "SERIALNUMBER": serialNumber,
                "CONFIG": configuration,
            },
        )

    def exec_cmd_stream(self, command):
        """Execute a command and stream output."""
        _, stream = self.container.exec_run(cmd=command, stream=True)
        for data in stream:
            print(data.decode(), end="")

    def exec_cmd(self, command, verbose=True):
        """Execute a command and validate return code."""
        result, output = self.container.exec_run(cmd=command)
        if verbose:
            print(output.decode())
        if result != 0:
            exit(1)

    def remove(self):
        """Remove the test container."""
        self.container.remove(force=True)


parser = argparse.ArgumentParser(description="E3DC testcontainers")
parser.add_argument(
    "-l",
    "--list",
    help="list of Python versions to test with",
    default='["3.8", "3.9", "3.10", "3.11", "3.12"]',
)
parser.add_argument("-c", "--configuration", help="configuration of E3DC", default="{}")
parser.add_argument(
    "-m",
    "--module",
    help="specify E3DC module version to be installed for tests. Use local to install from sources",
    default="local",
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

args = vars(parser.parse_args())

for version in json.loads(args["list"]):
    if args["verbose"]:
        print("Starting test on Python " + version + ":")
    testcontainers = Testcontainers(
        ipAddress=args["ipaddress"],
        username=args["username"],
        password=args["password"],
        key=args["key"],
        configuration=args["configuration"],
        serialNumber=args["serialnumber"],
        version=version,
    )
    cmd = "sh -c 'python tools/tests.py -u $USERNAME -p $PASSWORD -c $CONFIG"
    if args["module"] == "local":
        testcontainers.exec_cmd("pip install .", args["verbose"])
    else:
        testcontainers.exec_cmd(
            "pip install pye3dc=={}".format(args["module"]), args["verbose"]
        )
        cmd = cmd + " -m"
    if args["key"]:
        cmd = cmd + " -i $IPADDRESS -k $KEY"
    else:
        cmd = cmd + " -s $SERIALNUMBER"
    if args["verbose"]:
        cmd = cmd + " -v'"
    else:
        cmd = cmd + "'"
    testcontainers.exec_cmd(cmd)
    testcontainers.remove()
