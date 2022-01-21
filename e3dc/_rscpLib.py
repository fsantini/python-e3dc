#!/usr/bin/env python
# Python class to connect to an E3/DC system through the internet portal
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

import math
import struct
import time
import zlib

from . import _rscpTags as rscpTags

packFmtDict_FixedSize = {
    "Bool": "?",
    "Char8": "b",
    "UChar8": "B",
    "Int16": "h",
    "Uint16": "H",
    "Int32": "i",
    "Uint32": "I",
    "Int64": "q",
    "Uint64": "Q",
    "Float32": "f",
    "Double64": "d",
}

packFmtDict_VarSize = {
    "Bitfield": "s",
    "CString": "s",
    "Container": "s",
    "ByteArray": "s",
    "Error": "s",
}

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


# magic and ctrl are endian swapped
def endianSwapUint16(val):
    return struct.unpack("<H", struct.pack(">H", val))[0]


class FrameError(Exception):
    pass


def rscpEncode(tagStr, typeStr=None, data=None):
    if isinstance(tagStr, tuple):
        typeStr = tagStr[1]
        data = tagStr[2]
        tagStr = tagStr[0]
    else:
        if typeStr is None:
            raise TypeError("Second argument must not be none if first is not a tuple")

    tagHex = rscpTags.getHexTag(tagStr)
    typeHex = rscpTags.getHexDatatype(typeStr)

    if type(data) is str:
        data = data.encode("utf-8")

    packFmt = (
        "<IBH"  # format of header: little-endian, Uint32 tag, Uint8 type, Uint16 length
    )
    headerLen = struct.calcsize(packFmt)

    if typeStr == "None":  # special case: no content
        return struct.pack(packFmt, tagHex, typeHex, 0)
    elif (
        typeStr == "Timestamp"
    ):  # timestamp has a special format, divided into 32 bit integers
        ts = int(data / 1000)  # this is int64
        ms = (data - ts * 1000) * 1e6  # ms are multiplied by 10^6

        hiword = ts >> 32
        loword = ts & 0xFFFFFFFF

        packFmt += "iii"
        length = struct.calcsize(packFmt) - headerLen

        return struct.pack(packFmt, tagHex, typeHex, length, hiword, loword, ms)
    elif typeStr == "Container":
        if isinstance(data, list):
            newData = b""
            for dataChunk in data:
                newData += rscpEncode(
                    dataChunk[0], dataChunk[1], dataChunk[2]
                )  # transform each dataChunk into byte array
            data = newData
            packFmt += str(len(data)) + packFmtDict_VarSize[typeStr]
    elif typeStr in packFmtDict_FixedSize:
        packFmt += packFmtDict_FixedSize[typeStr]
    elif typeStr in packFmtDict_VarSize:
        packFmt += str(len(data)) + packFmtDict_VarSize[typeStr]

    length = struct.calcsize(packFmt) - headerLen
    return struct.pack(packFmt, tagHex, typeHex, length, data)


def rscpFrame(data):
    magic = endianSwapUint16(0xE3DC)
    ctrl = endianSwapUint16(0x11)
    t = time.time()
    sec1 = math.ceil(t)
    sec2 = 0
    ns = round((t - int(t)) * 1000)
    length = len(data)
    packFmt = "<HHIIIH" + str(length) + "s"
    frame = struct.pack(packFmt, magic, ctrl, sec1, sec2, ns, length, data)
    crc = zlib.crc32(frame) % (1 << 32)  # unsigned crc32
    frame += struct.pack("<I", crc)
    return frame


def rscpFrameDecode(frameData, returnFrameLen=False):
    headerFmt = "<HHIIIH"
    crcFmt = "I"
    crc = None

    magic, ctrl, sec1, sec2, ns, length = struct.unpack(
        headerFmt, frameData[: struct.calcsize(headerFmt)]
    )

    magic = endianSwapUint16(magic)
    ctrl = endianSwapUint16(ctrl)

    if ctrl & 0x10:  # crc enabled
        totalLen = struct.calcsize(headerFmt) + length + struct.calcsize(crcFmt)
        data, crc = struct.unpack(
            "<" + str(length) + "s" + crcFmt,
            frameData[struct.calcsize(headerFmt) : totalLen],
        )
    else:
        totalLen = struct.calcsize(headerFmt) + length
        data = struct.unpack(
            "<" + str(length) + "s", frameData[struct.calcsize(headerFmt) : totalLen]
        )[0]

    # check crc
    if crc is not None:
        crcCalc = zlib.crc32(frameData[: -struct.calcsize("<" + crcFmt)]) % (
            1 << 32
        )  # unsigned crc32
        if crcCalc != crc:
            raise FrameError("CRC32 not validated")

    timestamp = sec1 + float(ns) / 1000
    if returnFrameLen:
        return data, timestamp, totalLen
    else:
        return data, timestamp


def rscpDecode(data):

    headerFmt = (
        "<IBH"  # format of header: little-endian, Uint32 tag, Uint8 type, Uint16 length
    )
    headerSize = struct.calcsize(headerFmt)

    magicCheckFmt = ">H"
    magic = struct.unpack(magicCheckFmt, data[: struct.calcsize(magicCheckFmt)])[0]
    if magic == 0xE3DC:
        # we have a frame: decode it
        # print "Decoding frame in rscpDecode"
        return rscpDecode(rscpFrameDecode(data)[0])

    # decode header
    hexTag, hexType, length = struct.unpack(
        headerFmt, data[: struct.calcsize(headerFmt)]
    )
    # print (hex(hexTag), hex(hexType), length, data[struct.calcsize(headerFmt):])
    strTag = rscpTags.getTag(hexTag)
    strType = rscpTags.getDatatype(hexType)

    if strType == "Container":
        # this is a container: parse the inside
        dataList = []
        curByte = headerSize
        while curByte < headerSize + length:
            innerData, usedLength = rscpDecode(data[curByte:])
            curByte += usedLength
            dataList.append(innerData)
        return (strTag, strType, dataList), curByte
    elif strType == "Timestamp":
        fmt = "<iii"
        hiword, loword, ms = struct.unpack(
            fmt, data[headerSize : headerSize + struct.calcsize(fmt)]
        )
        # t = float((hiword << 32) + loword) + (float(ms)*1e-9) # this should work, but doesn't
        t = float(hiword + loword) + (float(ms) * 1e-9)  # this seems to be correct
        return (strTag, strType, t), headerSize + struct.calcsize(fmt)
    elif strType == "None":
        return (strTag, strType, None), headerSize
    elif strType in packFmtDict_FixedSize:
        fmt = "<" + packFmtDict_FixedSize[strType]
    elif strType in packFmtDict_VarSize:
        fmt = "<" + str(length) + packFmtDict_VarSize[strType]

    val = struct.unpack(fmt, data[headerSize : headerSize + struct.calcsize(fmt)])[0]

    if strType == "Error":
        val = rscpTags.getErrorcode(int.from_bytes(val, "little"))
    elif isinstance(val, bytes) and strType == "CString":
        # return string instead of bytes
        val = val.decode("utf-8")

    return (strTag, strType, val), headerSize + struct.calcsize(fmt)
