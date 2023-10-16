# Helper Scripts

## install requirements

`pip install pye3dc[develop]`

## Convert RSCP Tags

The script `convert_rscp_tags.py` can be used to generate the `RscpTag(Enum)` class if a new version of the Javascript rscp library (`https://s10.e3dc.com/s10/js/rscpLibV0.9.3.min.js`) is available.

### usage

```
usage: convert_rscp_tags.py [-h] [-r RSCPLIB]

E3DC rscp tags convert

options:
  -h, --help            show this help message and exit
  -r RSCPLIB, --rscpLib RSCPLIB
                        rscp library file
```

## Run tests

The script `test.py` will run all non altering methods for `pye3dc` for testing or sharing the output.

### usage

```
usage: tests.py [-h] [-c CONFIG] -i IPADDRESS -u USERNAME -p PASSWORD -k KEY

E3DC tests

options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        config of E3DC

required named arguments:
  -i IPADDRESS, --ipaddress IPADDRESS
                        IP address of E3DC
  -u USERNAME, --username USERNAME
                        username of E3DC
  -p PASSWORD, --password PASSWORD
                        password of E3DC
  -k KEY, --key KEY     key of E3DC
```

## Run tests for different python versions

The script `testcontainers.py` wil run the `tests`, using docker, for multiple Python versions supported by this library.

### usage

```
usage: testcontainers.py [-h] [-l LIST] [-c CONFIG] -i IPADDRESS -u USERNAME -p PASSWORD -k KEY

E3DC testcontainers

options:
  -h, --help            show this help message and exit
  -l LIST, --list LIST  list of Python versions to test with
  -c CONFIG, --config CONFIG
                        config of E3DC

required named arguments:
  -i IPADDRESS, --ipaddress IPADDRESS
                        IP address of E3DC
  -u USERNAME, --username USERNAME
                        username of E3DC
  -p PASSWORD, --password PASSWORD
                        password of E3DC
  -k KEY, --key KEY     key of E3DC
```