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
        key,
        configuration,
        module,
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
                "CONFIG": configuration,
                "MODULE": module,
            },
        )

    def exec_cmd_stream(self, command):
        """Execute a command and stream output."""
        _, stream = self.container.exec_run(cmd=command, stream=True)
        for data in stream:
            print(data.decode(), end="")

    def exec_cmd(self, command):
        """Execute a command and validate return code."""
        result, output = self.container.exec_run(cmd=command)
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
parser.add_argument("-c", "--config", help="config of E3DC", default="{}")
parser.add_argument(
    "-m",
    "--module",
    help="E3DC module source to use for test",
    choices=["source", "default"],
    default="source",
)
requiredNamed = parser.add_argument_group("required named arguments")
requiredNamed.add_argument(
    "-i", "--ipaddress", help="IP address of E3DC", required=True
)
requiredNamed.add_argument("-u", "--username", help="username of E3DC", required=True)
requiredNamed.add_argument("-p", "--password", help="password of E3DC", required=True)
requiredNamed.add_argument("-k", "--key", help="key of E3DC", required=True)
args = vars(parser.parse_args())

for version in json.loads(args["list"]):
    print("Starting test on Python " + version + ":")
    testcontainers = Testcontainers(
        ipAddress=args["ipaddress"],
        username=args["username"],
        password=args["password"],
        key=args["key"],
        configuration=args["config"],
        module=args["module"],
        version=version,
    )
    testcontainers.exec_cmd("pip install .")
    testcontainers.exec_cmd(
        "sh -c 'python tools/tests.py -i $IPADDRESS -u $USERNAME -p $PASSWORD -k $KEY -c $CONFIG -m $MODULE'"
    )
    testcontainers.remove()
    print()
