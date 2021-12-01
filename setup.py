from setuptools import setup

VERSION = "0.5.2"
NAME = "pye3dc"
 
install_requires = ["requests", "tzlocal", "pytz", "py3rijndael", "websocket-client", "python-dateutil"]

setup(
    name=NAME,
    version=VERSION,
    description="E3/DC client for python.",
    long_description=open("README.md").read(),
    long_description_content_type='text/markdown',
    author="Francesco Santini",
    author_email="francesco.santini@gmail.com",
    license="MIT",
    url="https://github.com/fsantini/python-e3dc.git",
    python_requires='>=3',
    install_requires=install_requires,
    packages=["e3dc"]
)
