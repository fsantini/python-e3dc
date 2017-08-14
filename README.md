# python-e3dc
Python API for querying E3/DC systems through the manufacturer's portal

This library provides an interface to query an E3/DC solar power management system through the web interface of the manufacturer.

In order to use it you need:
- Your user name
- Your password
- The serial number of the system which can be found when logging into the E3/DC webpage:
![E3/DC screenshot](doc-ima/sn.png)

## Usage

The password is better stored in your script as the md5 hash of the password itself. To calculate it (under Unix) you can use:
	echo -n <password> | md5sum

An example script using the library is the following:
```python
import e3dc
import time
import pprint

USERNAME = 'test@test.com'
#the following is the md5 hash of the password
PASSMD5 = '123456789abcdef0123456789abcdef0'
# alternatively, you can define
#PASSWORD = 'mypassword'
SERIALNUMBER = '123456789012'

e3dcObj = e3dc.E3DC(USERNAME, PASSMD5, SERIALNUMBER)
# or
# e3dcObj = e3dc.E3DC(USERNAME, PASSWORD, SERIALNUMBER, False)

# connect to the portal. This might raise an exception in case of failed login
e3dcObj.connect()

# print the status every 60 seconds
for i in range(10):
    # the poll() method returns a dictionary with the basic status information
    # for a more detailed view, use the poll_raw() command, which returns the data from the portal "as-is"
    pprint.pprint(e3dcObj.poll())
    time.sleep(60)
```
## poll() return values

Poll returns a dictionary like the following:
```python
{
	'consumption': {'battery': 470, 'house': 477, 'wallbox': 0}, # consumption in W. Positive values are exiting the system
	'production': {'grid': -4, 'solar': 951}, # production in W. Positive values are entering the system
	'stateOfCharge' : 77, # battery charge status in %
	'sysStatus': '2623', # status
	'time': datetime.datetime(2017, 8, 14, 7, 6, 13) # timestamp of the poll
} 
 ```