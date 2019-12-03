#!/usr/bin/env python
# Python class to connect to an E3/DC system through the internet portal
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

import websocket
import time
import struct
import hashlib
import threading # TODO: move to threading to make python3 easier
import tzlocal
import pytz
import datetime

from . import _rscpLib as rscpLib

"""
 The connection works the following way: (> outgoing, < incoming)

> [connect]
< SERVER_REGISTER_CONNECTION (conId, authLevel)
> SERVER_CONNECTION_REGISTERED
< SERVER_REQ_RSCP_CMD (information request from server)
> SERVER_REQ_RSCP_CMD (information back)
< INFO_SERIAL_NUMBER (webSerialno)
> SERVER_REQ_NEW_VIRTUAL_CONNECTION (username, password, sn)
< SERVER_REGISTER_CONNECTION (virtConId, virtAuthLevel)
> SERVER_CONNECTION_REGISTERED

 the connection is now established
 
 Communication is through SERVER_REQ_RSCP_CMD which is a container with:
 virtConId, virtAuthLevel, innerFrame
 
 and the innerframe is an RSCP frame with the appropriate command (HA_REQ_ACTUATOR_STATES for example)
 
"""

REMOTE_ADDRESS="wss://s10.e3dc.com/ws/"

class SocketNotReady(Exception):
    pass

class RequestTimeoutError(Exception):
    pass

def calcTimeZone():
    # calculate time zone
    localtz = tzlocal.get_localzone()
    utctz = pytz.timezone("UTC")

    naiveNow = datetime.datetime.now()
    localNow = localtz.localize(naiveNow)
    utcDiff = localtz.utcoffset(naiveNow) #this is a timedelta
    utcDiffS = utcDiff.total_seconds()
    utcDiffH = int(utcDiffS/60/60) # this is local - utc (eg 2 = UTC+2)
    TIMEZONE_STR = "GMT" + ( "+" if utcDiffH > 0 else "-" ) + str(abs(utcDiffH))
    return TIMEZONE_STR, utcDiffS

def timestampEncode(ts):
    sec = float(int(ts))
    ms = int((ts - sec)*1000)
    return struct.pack("<dI", sec, ms)

# finds a submessage with a specific tag
def rscpFindTag(decodedMsg, tag):
    if decodedMsg[0] == tag:
        return decodedMsg
    if isinstance(decodedMsg[2], list):
        for msg in decodedMsg[2]:
            msgValue = rscpFindTag(msg, tag)
            if msgValue is not None:
                return msgValue
    return None

class E3DC_RSCP:
    
    TIMEOUT = 10 # timeout in sec
    
    def __init__(self, username, password, serialNumber, isPasswordMd5 = True):
        """Constructor of a E3DC_RSCP object (does not connect)
        
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
        self.reset()
        
    def reset(self):
        self.ws = None
        self.conId = None
        self.authLevel = None
        self.virtConId = None
        self.virtAuthLevel = None
        self.webSerialno = None
        self.responseCallback = None
        self.responseCallbackCalled = False
        self.requestResult = None


    def buildVirtualConn(self):
        virtualConn = rscpLib.rscpFrame(rscpLib.rscpEncode("SERVER_REQ_NEW_VIRTUAL_CONNECTION", "Container", [
                                                        ("SERVER_USER", "CString", self.username),
                                                        ("SERVER_PASSWD", "CString", self.password),
                                                        ("SERVER_IDENTIFIER", "CString", "S10-" + self.serialNumber),
                                                        ("SERVER_TYPE", "Int32", 4),
                                                        ("SERVER_HASH_CODE", "Int32", 1234567890)]))

        #print "--------------------- Sending virtual conn"
        self.ws.send(virtualConn,  websocket.ABNF.OPCODE_BINARY)
        
    
    def respondToINFORequest(self, decoded):
        TIMEZONE_STR, utcDiffS = calcTimeZone()
        tag = decoded[0]
        if tag == 'INFO_REQ_IP_ADDRESS':
            return rscpLib.rscpEncode("INFO_IP_ADDRESS", "CString","0.0.0.0")
        elif tag == "INFO_REQ_SUBNET_MASK":
            return rscpLib.rscpEncode("INFO_SUBNET_MASK", "CString","0.0.0.0")
        elif tag == "INFO_REQ_GATEWAY":
            return rscpLib.rscpEncode("INFO_GATEWAY", "CString","0.0.0.0");
        elif tag == "INFO_REQ_DNS":
            return rscpLib.rscpEncode("INFO_DNS", "CString","0.0.0.0");
        elif tag == "INFO_REQ_DHCP_STATUS":
            return rscpLib.rscpEncode("INFO_DHCP_STATUS", "Bool","false");
        elif tag == "INFO_REQ_TIME":
            return rscpLib.rscpEncode("INFO_TIME", "ByteArray", timestampEncode(time.time()))
        elif tag == "INFO_REQ_TIME_ZONE":
            return rscpLib.rscpEncode("INFO_TIME_ZONE", "CString", TIMEZONE_STR)
        elif tag == "INFO_REQ_UTC_TIME":
            return rscpLib.rscpEncode("INFO_UTC_TIME", "ByteArray", timestampEncode(time.time() - utcDiffS))
        elif tag == "INFO_REQ_A35_SERIAL_NUMBER":
            return rscpLib.rscpEncode("INFO_A35_SERIAL_NUMBER", "CString","123456")
        elif tag == "INFO_REQ_INFO":
            return rscpLib.rscpEncode("INFO_INFO", "Container",
                                    [("INFO_SERIAL_NUMBER","CString","WEB_" + hashlib.md5(self.username+str(self.conId)).hexdigest()),
                                    ("INFO_PRODUCTION_DATE","CString","570412800000"), 
                                    ("INFO_MAC_ADDRESS","CString","00:00:00:00:00:00")])
        elif tag == "INFO_SERIAL_NUMBER":
            self.webSerialno = decoded[2]
            self.buildVirtualConn()
            return ''
        return None # this is no standard request
            
    def registerConnectionHandler(self, decodedMsg):
        if self.conId is None:
            self.conId = rscpFindTag(decodedMsg, 'SERVER_CONNECTION_ID')[2]
            self.authLevel = rscpFindTag(decodedMsg, 'SERVER_AUTH_LEVEL')[2]
        else:
            self.virtConId = rscpFindTag(decodedMsg, 'SERVER_CONNECTION_ID')[2]
            self.virtAuthLevel = rscpFindTag(decodedMsg, 'SERVER_AUTH_LEVEL')[2]
        #reply = rscpLib.rscpFrame(rscpLib.rscpEncode("SERVER_CONNECTION_REGISTERED", "Container", [decodedMsg[2][0], decodedMsg[2][1]]));
        reply = rscpLib.rscpFrame(rscpLib.rscpEncode("SERVER_CONNECTION_REGISTERED", "Container", [rscpFindTag(decodedMsg, 'SERVER_CONNECTION_ID'), rscpFindTag(decodedMsg, 'SERVER_AUTH_LEVEL')]))
        self.ws.send(reply, websocket.ABNF.OPCODE_BINARY)
        
    def on_message(self, message):
        #print "Received message", message
        if len(message) == 0: return

        decodedMsg = rscpLib.rscpDecode(message)[0]
        
        #print "Decoded received message", decodedMsg
        if decodedMsg[0] == 'SERVER_REQ_PING':
            pingFrame = rscpLib.rscpFrame( rscpLib.rscpEncode("SERVER_PING", "None", None) );
            self.ws.send(pingFrame,  websocket.ABNF.OPCODE_BINARY)  
            return
        elif decodedMsg[0] == 'SERVER_REGISTER_CONNECTION':
            self.registerConnectionHandler(decodedMsg)
        elif decodedMsg[0] == 'SERVER_UNREGISTER_CONNECTION':
            # this signifies some error
            self.disconnect()
        elif decodedMsg[0] == 'SERVER_REQ_RSCP_CMD':
            thisConId = rscpFindTag(decodedMsg, 'SERVER_CONNECTION_ID')[2]
            data = rscpLib.rscpFrameDecode( rscpFindTag(decodedMsg, 'SERVER_RSCP_DATA')[2] )[0]
            response = ''
            self.responseCallbackCalled = False
            while len(data) > 0:
                decoded, l = rscpLib.rscpDecode(data)
                #print "Inner frame chunk decoded", decoded
                data = data[l:]
                responseChunk = self.respondToINFORequest(decoded)
                if responseChunk is None:
                    # this is not a standard request: call the registered callback
                    if self.responseCallback is not None:
                        self.responseCallback(decoded) # !!! Important!!! This is where the callback is called with the decoded inner frame
                        self.responseCallbackCalled = True
                    responseChunk = ''
                        
                response += responseChunk
            if self.responseCallbackCalled: self.responseCallback = None # unregister the callback. Good idea??
            if len(response) == 0: return # do not send an empty response
            innerFrame = rscpLib.rscpFrame(response)
            responseContainer = rscpLib.rscpEncode("SERVER_REQ_RSCP_CMD", "Container",
                                                    [("SERVER_CONNECTION_ID","Int64", self.conId),
                                                    ("SERVER_AUTH_LEVEL","UChar8", self.authLevel),
                                                    ("SERVER_RSCP_DATA_LEN","Int32", len(innerFrame)),
                                                    ("SERVER_RSCP_DATA","ByteArray", innerFrame)])
                                                    
            self.ws.send(rscpLib.rscpFrame(responseContainer),  websocket.ABNF.OPCODE_BINARY)
 
    def _defaultRequestCallback(self, msg):
        self.requestResult = msg
 
    def sendRequest(self, innerFrame, callback=None, synchronous=False):
        """
            sendRequest(self, innerFrame, dataType=None, content=None):
            
            This can be called in two ways:
            sendRequest(<RSCP encoded frame>, [callback], [synchronous])
            sendRequest(<tuple>, [callback], [synchronous])
            
            If synchronous == True, the method waits for a response (i.e. exits after calling callback).
            If synchronous == True and callback = None, the method returns the (last) response message
        """
        if not self.isConnected:
            raise SocketNotReady
        
        if isinstance(innerFrame, tuple):
            # if innerframe is a tuple then the message is not encoded
            innerFrame = rscpLib.rscpFrame( rscpLib.rscpEncode(*innerFrame) )

        self.requestResult = None
        self.responseCallbackCalled = False
        if callback is not None:
            self.responseCallback = callback
        else:
            if synchronous:
                self.responseCallback = lambda msg: self._defaultRequestCallback(msg)
            else:
                self.responseCallback = None
                
        
        outerFrame = rscpLib.rscpFrame( rscpLib.rscpEncode("SERVER_REQ_RSCP_CMD", "Container", [
            ("SERVER_CONNECTION_ID","Int64", self.virtConId),
            ("SERVER_AUTH_LEVEL","UChar8", self.virtAuthLevel),
            ("SERVER_RSCP_DATA_LEN","Int32", len(innerFrame)),
            ("SERVER_RSCP_DATA","ByteArray", innerFrame)]))
        
        self.ws.send(outerFrame,  websocket.ABNF.OPCODE_BINARY)
        
        if synchronous == True:
            for i in range(self.TIMEOUT*10):
                if self.responseCallbackCalled: break
                time.sleep(0.1)
            if not self.responseCallbackCalled: raise RequestTimeoutError
                
            if callback is None: # the default callback was called
                return self.requestResult
        
    def connect(self):
        websocket.enableTrace(False)
        if self.ws is not None:
            self.ws.close()
            self.reset()
        self.ws = websocket.WebSocketApp(REMOTE_ADDRESS, 
                                         on_message = lambda ws, msg: self.on_message(msg),
                                         on_close = lambda ws: self.reset(),
                                         on_error = lambda ws, msg: self.reset())
        
        self.thread = threading.Thread( target = self.ws.run_forever )
        #thread.start_new_thread(self.ws.run_forever, ())
        self.thread.start()
        
        for i in range(self.TIMEOUT*10):
            if self.isConnected(): break
            time.sleep(0.1)
        if not self.isConnected(): raise RequestTimeoutError
    
    def disconnect(self):
        if self.ws is not None: self.ws.close()
        self.reset()
    
    def isConnected(self):
        return (self.virtConId is not None)
