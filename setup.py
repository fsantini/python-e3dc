from setuptools import setup

VERSION = "0.2.0"
NAME = "e3dc"
 
install_requires = ["requests", "websocket-client", "tzlocal", "pytz"]

setup(
    name=NAME,
    version=VERSION,
    description="E3/DC client for python.",
    long_description=open("README.md").read(),
    author="Francesco Santini",
    author_email="francesco.santini@gmail.com",
    license="MIT",
    url="https://github.com/fsantini/python-e3dc.git",
    install_requires=install_requires,
    packages=["e3dc"]
)
