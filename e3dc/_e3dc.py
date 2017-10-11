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
    
    DAY_MONDAY = 0
    DAY_TUESDAY = 1
    DAY_WEDNESDAY = 2
    DAY_THURSDAY = 3
    DAY_FRIDAY = 4
    DAY_SATURDAY = 5
    DAY_SUNDAY = 6
    
    IDLE_TYPE_CHARGE = 0
    IDLE_TYPE_DISCHARGE = 1
    
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
        self.idleCharge = None
        self.idleDischarge = None
        
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
        
    def sendRequest(self, request, keepAlive = False):
        if not self.rscp.isConnected():
            self.rscp.connect()
                
        result = self.rscp.sendRequest( request )
        
        if not keepAlive:
            self.rscp.disconnect()
            
        return result
        
    # initialize lists of idle times. Day 0 is monday!
    def _initIdleLists(self):
        idleCharge = []
        idleDischarge = []
        for i in range(7):
            idleCharge.append( { 'start': (None, None), 'end': (None, None), 'active': False } )
            idleDischarge.append( { 'start': (None, None), 'end': (None, None), 'active': False } )
        return idleCharge, idleDischarge
        
    def get_idle_times(self, keepAlive = False):
        idleTimesRaw = self.sendRequest(("EMS_REQ_GET_IDLE_PERIODS", "None", None), keepAlive)
        if idleTimesRaw[0] != "EMS_GET_IDLE_PERIODS":
            return None, None
        idleCharge, idleDischarge = self._initIdleLists()
        # initialize 
        for period in idleTimesRaw[2]:
            active = rscpFindTag(period, 'EMS_IDLE_PERIOD_ACTIVE')[2]
            typ = rscpFindTag(period, 'EMS_IDLE_PERIOD_TYPE')[2]
            day = rscpFindTag(period, 'EMS_IDLE_PERIOD_DAY')[2]
            start = rscpFindTag(period, 'EMS_IDLE_PERIOD_START')
            startHour = rscpFindTag(start, 'EMS_IDLE_PERIOD_HOUR')[2]
            startMin = rscpFindTag(start, 'EMS_IDLE_PERIOD_MINUTE')[2]
            end = rscpFindTag(period, 'EMS_IDLE_PERIOD_END')
            endHour = rscpFindTag(end, 'EMS_IDLE_PERIOD_HOUR')[2]
            endMin = rscpFindTag(end, 'EMS_IDLE_PERIOD_MINUTE')[2]
            periodObj = { 'start': (startHour, startMin), 'end': (endHour, endMin), 'active': active }
            if typ == self.IDLE_TYPE_CHARGE:
                idleCharge[day] = periodObj
            else:
                idleDischarge[day] = periodObj
                
        return idleCharge, idleDischarge
            
    # set the whole period at once
    def set_idle_periods(self, idleCharge, idleDischarge, keepAlive = False):
        periodList = []
        
        def appendPeriod(typ, day, period):
            startHour = period['start'][0]
            startMin = period['start'][1]
            endHour = period['end'][0]
            endMin = period['end'][1]
            active = period['active']
            # if any hour is none, set to default
            if None in [startHour, startMin, endHour, endMin]:
                startHour = 0
                startMin = 0
                endHour = 1
                endMin = 0
                active = False
                
            periodList.append( ('EMS_IDLE_PERIOD', 'Container', [
                        ('EMS_IDLE_PERIOD_TYPE', 'UChar8', typ),
                        ('EMS_IDLE_PERIOD_DAY', 'UChar8', day),
                        ('EMS_IDLE_PERIOD_ACTIVE', 'Bool', active),
                        ('EMS_IDLE_PERIOD_START', 'Container', [
                            ('EMS_IDLE_PERIOD_HOUR', 'UChar8', startHour),
                            ('EMS_IDLE_PERIOD_MINUTE', 'UChar8', startMin)]),
                        ('EMS_IDLE_PERIOD_END', 'Container', [
                            ('EMS_IDLE_PERIOD_HOUR', 'UChar8', endHour),
                            ('EMS_IDLE_PERIOD_MINUTE', 'UChar8', endMin)])]) )
                        
                                
        
        for day in range(len(idleCharge)):
            appendPeriod(self.IDLE_TYPE_CHARGE, day, idleCharge[day])
        
        for day in range(len(idleDischarge)):
            appendPeriod(self.IDLE_TYPE_DISCHARGE, day, idleDischarge[day])
            
        result = self.sendRequest( ('EMS_REQ_SET_IDLE_PERIODS', 'Container', periodList), keepAlive )
        
        if result[0] != 'EMS_SET_IDLE_PERIODS' or result[2] != 1:
            return False
        return True
            

            
    
    def set_idle_time(self, typ, day, start, end, active, defer = False, keepAlive = False):
        """  
            set a specific idle time.
            Type: charge/discharge
            Day: day to set 
            start: tuple (hour, min)
            end: tuple (hour, min)
            if start or end are (None, None), then the times are unchanged
            active: status of the period
            defer: controls whether to immediately apply changes or not
        """
        if self.idleCharge is None:
            self.idleCharge, self.idleDischarge = self.get_idle_times( keepAlive or not defer ) # Note: keep this connection alive if explicitly said, 
                                                                                                # or if not deferred, because then the closing will be done below in set_idle_periods
                                                                                                
        if self.idleCharge is None: return False
    
        # if day is none, just apply the changes (unless defer is true, which doesn't make sense)
        if day is not None:
            if typ == self.IDLE_TYPE_CHARGE:
                idleList = self.idleCharge
            else:
                idleList = self.idleDischarge
                
            # if any of the start or end times is none, then only set the active status
            if None in start + end:
                idleList[day]['active'] = active
            else:
                periodObj = { 'start': start, 'end': end, 'active': active }
                idleList[day] = periodObj
            
        # if we defer apply, then just return. We modified the internal lists
        if not defer:
            success = self.set_idle_periods(self.idleCharge, self.idleDischarge, keepAlive)
            if success:
                self.idleCharge = None
                self.idleDischarge = None
                return True
            else:
                return False
        else:
            return True
        
    def is_battery_limited(self, keepAlive = False):
        res = self.sendRequest(("EMS_REQ_GET_POWER_SETTINGS", "None", None), keepAlive)
        limitsUsed = rscpFindTag(res, "EMS_POWER_LIMITS_USED")
        if limitsUsed is None: return None
        return limitsUsed[2]
        
    def battery_enable_disable(self, enabled, keepAlive = False):
        if enabled:
            res = self.sendRequest(("EMS_REQ_SET_POWER_SETTINGS", "Container", [ ("EMS_POWER_LIMITS_USED", "Bool", False), ("EMS_MAX_DISCHARGE_POWER", "Uint32", 3000), ("EMS_MAX_CHARGE_POWER", "Uint32", 3000) ]), keepAlive = True)
        else:
            res = self.sendRequest(("EMS_REQ_SET_POWER_SETTINGS", "Container", [ ("EMS_POWER_LIMITS_USED", "Bool", True), ("EMS_MAX_DISCHARGE_POWER", "Uint32", 0), ("EMS_MAX_CHARGE_POWER", "Uint32", 0) ]), keepAlive = True)
            
        # the following check if the battery is limited. If enabled is true, then battery should not be limited, and vice versa. If the following is false, it means failure
        return self.is_battery_limited(keepAlive = keepAlive) != enabled
