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

# connect to the portal. This might raise an exception in case of failed login. If not called, it will be automatically called by poll()
e3dcObj.connect()

# print the status every 60 seconds
for i in range(10):
    # the poll() method returns a dictionary with the basic status information
    # for a more detailed view, use the poll_raw() command, which returns the data from the portal "as-is"
    pprint.pprint(e3dcObj.poll())
    # the poll_switches method returns a list of smart switches available on the system
    # return value is in the format {'id': switchID, 'type': switchType, 'name': switchName, 'status': switchStatus}
    pprint.pprint(e3dcObj.poll_switches())
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
 
 ## setting swiches
 
 The e3dcObj.set_switch_onoff(switchID, value, keepAlive = False) method sets a smart switch on or off, where value is a boolean and True = on, False = off.
 The switchID is a number returned by the poll_switches method. This method only supports on/off switches and not dimmers or motors.
 
 ## Note: The RSCP interface
 
 The power production/consumption status is obtained by the portal through a simple Http request. On the other hand, the switch statuses are obtained and manipulated
 via a more complicated protocol, called by E3/DC RSCP. This protocol is binary and based on websockets.
 
 The E3DC object automatically connects to the websocket and authenticates. Both the poll_switches and set_switch_onoff methods accept an optional keepAlive parameter.
 
 If keepAlive is false, the websocket connection is closed after the command. This makes sense because these requests are not meant to be made as often as the status requests,
 however, if keepAlive is True, the connection is left open and kept alive in the background in a separate thread.
 
 ## Known limitations
 
 The first obvious limitation of the library is that it does not directly connect to the device, but communicates through the Internet portal. This means that the connection
 is rather slow and Internet connection is required.
 
 The second limitation concerns the implemented RSCP methods. At the moment, only switch status requests and setting of on/off switches is implemented. I also lack the hardware
 to test different configurations. However, the RSCP protocol is (to my knowledge) fully implemented and it should be easy to extend the requests to other cases.
