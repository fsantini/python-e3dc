#!/usr/bin/env python
# Python class to connect to an E3/DC system through the internet portal
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

import requests
import hashlib
import time
import dateutil.parser
import datetime
import json

from _e3dc_rscp_web import E3DC_RSCP_web
from _e3dc_rscp_local import E3DC_RSCP_local 
from _rscpLib import rscpFindTag

REMOTE_ADDRESS='https://s10.e3dc.com/s10/phpcmd/cmd.php'
REQUEST_INTERVAL_SEC = 10 # minimum interval between requests

class AuthenticationError(Exception):
    pass

class PollError(Exception):
    pass

class E3DC:
    """A class describing an E3DC system, used to poll the status from the portal
    """
    
    CONNECT_LOCAL = 1
    CONNECT_WEB = 2
    
    def __init__(self, connectType, **kwargs):
        """Constructor of a E3DC object (does not connect)
    
        Args:
            connectType: CONNECT_LOCAL: use local rscp connection
                Named args for CONNECT_LOCAL:
                username (string): username
                password (string): password (plain text)
                ipAddress (string): IP address of the E3DC system
                key (string): encryption key as set in the E3DC settings
            
            connectType: CONNECT_WEB: use web connection
                Named args for CONNECT_WEB:
                username (string): username
                password (string): password (plain text or md5 hash)
                serialNumber (string): the serial number of the system to monitor
                isPasswordMd5 (boolean, optional): indicates whether the password is already md5 digest (recommended, default = True)
        """
        
        self.connectType = connectType
        self.username = kwargs['username']
        if connectType == self.CONNECT_LOCAL:
            self.ip = kwargs['ipAddress']
            self.key = kwargs['key']
            self.password = kwargs['password']
            self.rscp = E3DC_RSCP_local(self.username, self.password, self.ip, self.key)
            self.poll = self.poll_rscp
        
        else:
            self.serialNumber = kwargs['serialNumber']
            if 'isPasswordMd5' in kwargs:
                if kwargs['isPasswordMd5'] == True:
                    self.password = kwargs['password']
                else:
                    self.password = hashlib.md5(kwargs['password']).hexdigest()
            self.rscp = E3DC_RSCP_web(self.username, self.password, self.serialNumber)
            self.poll = self.poll_ajax
        
        self.jar = None
        self.lastRequestTime = -1
        self.lastRequest = None
        self.connected = False
        
    def connect_local(self):
        pass
        
    def connect_web(self):
        """Connects to the E3DC portal and opens a session
        
        Raises:
            e3dc.AuthenticationError: login error
        """
        # login request
        loginPayload = {'DO' : 'LOGIN', 'USERNAME' : self.username, 'PASSWD' : self.password}
        
        try:
            r = requests.post(REMOTE_ADDRESS, data=loginPayload)
            jsonResponse = r.json()
        except:
            raise AuthenticationError("Error communicating with server")
        if jsonResponse['ERRNO'] != 0:
            raise AuthenticationError("Login error")
        
        # get cookies
        self.jar = r.cookies
        
        # set the proper device
        deviceSelectPayload = {'DO' : 'GETCONTENT', 'MODID' : 'IDOVERVIEWUNITMAIN', 'ARG0' : self.serialNumber, 'TOS' : -7200}
        
        try:
            r = requests.post(REMOTE_ADDRESS, data=deviceSelectPayload, cookies = self.jar)
            jsonResponse = r.json()
        except:
            raise AuthenticationError("Error communicating with server")
        if jsonResponse['ERRNO'] != 0:
            raise AuthenticationError("Error selecting device")
        self.connected = True
        
    def poll_ajax_raw(self):
        """Polls the portal for the current status
        
        Returns:
            Dictionary containing the status information in raw format as returned by the portal
            
        Raises:
            e3dc.PollError in case of problems polling
        """
        
        if self.connected == False:
            self.connect_web()
        
        if self.lastRequest is not None and (time.time() - self.lastRequestTime) < REQUEST_INTERVAL_SEC:
            return lastRequest
        
        pollPayload = { 'DO' : 'LIVEUNITDATA' }
        pollHeaders = { 'Pragma' : 'no-cache', 'Cache-Control' : 'no-cache' }
        
        try:
            r = requests.post(REMOTE_ADDRESS, data=pollPayload, cookies = self.jar, headers = pollHeaders)
            jsonResponse = r.json()
        except:
            self.connected = False
            raise PollError("Error communicating with server")
        
        if jsonResponse['ERRNO'] != 0:
            raise PollError("Error polling: %d" % (jsonResponse['ERRNO']))
        
        self.lastRequest = jsonResponse['CONTENT']
        self.lastRequestTime = time.time()
        return json.loads(jsonResponse['CONTENT'])
        
    def poll_ajax(self, **kwargs):
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
        raw = self.poll_ajax_raw()
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
    
    def poll_rscp(self, keepAlive = False):
        
        if self.lastRequest is not None and (time.time() - self.lastRequestTime) < REQUEST_INTERVAL_SEC:
            return lastRequest
        
        if not self.rscp.isConnected():
            self.rscp.connect()
        
        ts = self.rscp.sendRequest( ('INFO_REQ_UTC_TIME', 'None', None) )[2]
        #print time.time()
        soc = self.rscp.sendRequest( ('EMS_REQ_BAT_SOC', 'None', None) )[2]
        solar = self.rscp.sendRequest( ('EMS_REQ_POWER_PV', 'None', None) )[2]
        bat = self.rscp.sendRequest( ('EMS_REQ_POWER_BAT', 'None', None) )[2]
        #home = self.rscp.sendRequest( ('EMS_REQ_POWER_HOME', 'None', None) )[2]
        grid = self.rscp.sendRequest( ('EMS_REQ_POWER_GRID', 'None', None) )[2]
        wb = self.rscp.sendRequest( ('EMS_REQ_POWER_WB_ALL', 'None', None) )[2]
        
        home = solar + grid - bat - wb # make balance = 0
        
        if not keepAlive:
            self.rscp.disconnect()
            
        outObj = {
            'time': datetime.datetime.utcfromtimestamp(ts),
            'sysStatus': 1234,
            'stateOfCharge': soc,
            'production': {
                'solar' : solar,
                'grid' : grid
                },
            'consumption': {
                'battery': bat,
                'house': home,
                'wallbox': wb
                }
            }
            
        self.lastRequest = outObj
        self.lastRequestTime = time.time()
        return outObj
    
    def poll_switches(self, keepAlive = False):
        """
            This function uses the RSCP interface to poll the switch status
            if keepAlive is False, the connection is closed afterwards
        """
        
        if not self.rscp.isConnected():
            self.rscp.connect()
            
        switchDesc = self.rscp.sendRequest( ("HA_REQ_DATAPOINT_LIST", "None", None) )
        switchStatus = self.rscp.sendRequest( ("HA_REQ_ACTUATOR_STATES", "None", None) )
        
        descList = switchDesc[2] # get the payload of the container
        statusList = switchStatus[2]
        
        #print switchStatus
        
        switchList = []
        
        for switch in range(len(descList)):
            switchID = rscpFindTag(descList[switch], 'HA_DATAPOINT_INDEX')[2]
            switchType = rscpFindTag(descList[switch], 'HA_DATAPOINT_TYPE')[2]
            switchName = rscpFindTag(descList[switch], 'HA_DATAPOINT_NAME')[2]
            switchStatus = rscpFindTag(statusList[switch], 'HA_DATAPOINT_STATE')[2]
            switchList.append({'id': switchID, 'type': switchType, 'name': switchName, 'status': switchStatus})
            
        if not keepAlive:
            self.rscp.disconnect()
        
        return switchList
                               
    def set_switch_onoff(self, switchID, value, keepAlive = False):
        """
            This function uses the RSCP interface to turn a switch on or off
            The switchID is as returned by poll_switches
        """
        
        if not self.rscp.isConnected():
            self.rscp.connect()
        
        cmd = "on" if value else "off"
        
        result = self.rscp.sendRequest( ("HA_REQ_COMMAND_ACTUATOR", "Container", [
                    ("HA_DATAPOINT_INDEX", "Uint16", switchID),
                    ("HA_REQ_COMMAND", "CString", cmd)]))
        
        if not keepAlive:
            self.rscp.disconnect()
        
        
        if result[0] == "HA_COMMAND_ACTUATOR" and result[2] == True:
            return True
        else:
            return False # operation did not succeed
        

    
