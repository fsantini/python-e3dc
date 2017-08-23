#!/usr/bin/env python
# Python class to connect to an E3/DC system through the internet portal
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

import requests
import hashlib
import time
import dateutil.parser
import ast

from ._e3dc_rscp import E3DC_RSCP, rscpFindTag

REMOTE_ADDRESS='https://s10.e3dc.com/s10/phpcmd/cmd.php'
REQUEST_INTERVAL_SEC = 10 # minimum interval between requests

class AuthenticationError(Exception):
    pass

class PollError(Exception):
    pass

class E3DC:
    """A class describing an E3DC system, used to poll the status from the portal
    """
    def __init__(self, username, password, serialNumber, isPasswordMd5 = True):
        """Constructor of a E3DC object (does not connect)
        
        Args:
            username (string): the user name to the E3DC portal
            password (string): the password (as md5 digest by default)
            serialNumber (string): the serial number of the system to monitor
            isPasswordMd5 (boolean, optional): indicates whether the password is already md5 digest (recommended, default = True)
        """
        self.username = username
        if isPasswordMd5:
            self.password = password
        else:
            self.password = hashlib.md5(password).hexdigest()
        
        self.serialNumber = serialNumber
        self.jar = None
        self.lastRequestTime = -1
        self.lastRequest = None
        self.connected = False
        self.rscp = E3DC_RSCP(self.username, self.password, self.serialNumber)
        
    def connect(self):
        """Connects to the E3DC portal and opens a session
        
        Raises:
            e3dc.AuthenticationError: login error
        """
        # login request
        loginPayload = {'DO' : 'LOGIN', 'USERNAME' : self.username, 'PASSWD' : self.password}
        r = requests.post(REMOTE_ADDRESS, data=loginPayload)
        
        jsonResponse = r.json()
        if jsonResponse['ERRNO'] != 0:
            raise AuthenticationError("Login error")
        
        # get cookies
        self.jar = r.cookies
        
        # set the proper device
        deviceSelectPayload = {'DO' : 'GETCONTENT', 'MODID' : 'IDOVERVIEWUNITMAIN', 'ARG0' : self.serialNumber, 'TOS' : -7200}
        r = requests.post(REMOTE_ADDRESS, data=deviceSelectPayload, cookies = self.jar)
        jsonResponse = r.json()
        if jsonResponse['ERRNO'] != 0:
            raise AuthenticationError("Error selecting device")
        self.connected = True
        
    def poll_raw(self):
        """Polls the portal for the current status
        
        Returns:
            Dictionary containing the status information in raw format as returned by the portal
            
        Raises:
            e3dc.PollError in case of problems polling
        """
        
        if self.connected == False:
            raise PollError("Not connected! Call connect first")
        
        if self.lastRequest is not None and (time.time() - self.lastRequestTime) < REQUEST_INTERVAL_SEC:
            return lastRequest
        
        pollPayload = { 'DO' : 'LIVEUNITDATA' }
        pollHeaders = { 'Pragma' : 'no-cache', 'Cache-Control' : 'no-cache' }
        
        r = requests.post(REMOTE_ADDRESS, data=pollPayload, cookies = self.jar, headers = pollHeaders)
        
        jsonResponse = r.json()
        if jsonResponse['ERRNO'] != 0:
            raise PollError("Error polling: %d" % (jsonResponse['ERRNO']))
        
        self.lastRequest = jsonResponse['CONTENT']
        self.lastRequestTime = time.time()
        return ast.literal_eval(jsonResponse['CONTENT'])
        
    def poll(self):
        """Polls the portal for the current status and returns a digest
        
        Returns:
            Dictionary containing the condensed status information structured as follows:
                {
                    'time': datetime object containing the timestamp
                    'sysStatus': string containing the system status code
                    'stateOfCharge': battery charge status in %
                    'production': { production values: positive means entering the system
                        'solar' : production from solar in W
                        'grid' : absorption from grid in W
                        },
                    'consumption': { consumption values: positive means exiting the system
                    'battery': power entering battery (positive: charging, negative: discharging)
                    'house': house consumption
                    'wallbox': wallbox consumption
                    }
                }
            
        Raises:
            e3dc.PollError in case of problems polling
        """
        raw = self.poll_raw()
        outObj = {
            'time': dateutil.parser.parse(raw['time']),
            'sysStatus': raw['SYSSTATUS'],
            'stateOfCharge': int(raw['SOC']),
            'production': {
                'solar' : int(raw["POWER_PV_S1"]) + int(raw["POWER_PV_S2"]) + int(raw["POWER_PV_S3"]),
                'grid' : int(raw["POWER_LM_L1"]) + int(raw["POWER_LM_L2"]) + int(raw["POWER_LM_L3"])
                },
            'consumption': {
                'battery': int(raw["POWER_BAT"]),
                'house': int(raw["POWER_C_L1"]) + int(raw["POWER_C_L2"]) + int(raw["POWER_C_L3"]),
                'wallbox': int(raw["POWER_WALLBOX"])
                }
            }
        return outObj
    
    def poll_switches(keepAlive = False):
        """
            This function uses the RSCP interface to poll the switch status
            if keepAlive is False, the connection is closed afterwards
        """
        
        if not self.rscp.isConnected():
            self.rscp.connect()
            
        switchDesc = self.rscp.sendRequest( ("HA_REQ_DATAPOINT_LIST", "None", None), None, True )
        switchStatus = self.rscpsendRequest( ("HA_REQ_ACTUATOR_STATES", "None", None), None, True )
        
        descList = switchDesc[2] # get the payload of the container
        statusList = switchStatus[2]
        
        switchList = []
        
        for switch in range(descList):
            switchID = rscpFindTag(descList[switch], 'HA_DATAPOINT_INDEX')[2]
            switchType = rscpFindTag(descList[switch], 'HA_DATAPOINT_TYPE')[2]
            switchName = rscpFindTag(descList[switch], 'HA_DATAPOINT_NAME')[2]
            switchStatus = rscpFindTag(statusList[switch], 'HA_DATAPOINT_STATE_VALUE')[2]
            switchList.append({'id': switchID, 'type': switchType, 'name': switchName, 'status': switchStatus})
            
        if not keepAlive:
            self.rscp.disconnect()
                               
    def set_switch_onoff(switchID, value, keepAlive = False):
        
        if not self.rscp.isConnected():
            self.rscp.connect()
        
        cmd = "on" if value else "off"
        
        result = swlf.rscp.sendRequest( ("HA_REQ_COMMAND_ACTUATOR", "Container", [
                    ("HA_DATAPOINT_INDEX", "Uint16", switchID),
                    ("HA_REQ_COMMAND", "CString", cmd)]) , None, True)
        
        if not keepAlive:
            self.rscp.disconnect()
        
        
