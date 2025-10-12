#!/usr/bin/env python
# Python class to connect to an E3/DC system.
#
# Copyright 2017 Francesco Santini <francesco.santini@gmail.com>
# Licensed under a MIT license. See LICENSE for details

from __future__ import annotations  # required for python < 3.9

import math
import struct
import time
import zlib
from typing import Any, List, Tuple

from ._rscpTags import (
    RscpTag,
    RscpType,
    getHexRscpTag,
    getHexRscpType,
    getRscpType,
    getStrRscpError,
    getStrRscpTag,
    getStrRscpType,
)

DEBUG_DICT = {"print_rscp": False}


def set_debug(debug: bool):
    """Turns debug on/off.

    Args:
        debug (bool): the status

    Returns:
        Nothing
    """
    DEBUG_DICT["print_rscp"] = debug


packFmtDict_FixedSize = {
    RscpType.Bool: "?",
    RscpType.Char8: "b",
    RscpType.UChar8: "B",
    RscpType.Int16: "h",
    RscpType.Uint16: "H",
    RscpType.Int32: "i",
    RscpType.Uint32: "I",
    RscpType.Int64: "q",
    RscpType.Uint64: "Q",
    RscpType.Float32: "f",
    RscpType.Double64: "d",
}

packFmtDict_VarSize = {
    RscpType.Bitfield: "s",
    RscpType.CString: "s",
    RscpType.Container: "s",
    RscpType.ByteArray: "s",
    RscpType.Error: "s",
}


def rscpFindTag(
    decodedMsg: Tuple[str | int | RscpTag, str | int | RscpType, Any] | None,
    tag: int | str | RscpTag,
) -> Tuple[str | int | RscpTag, str | int | RscpType, Any] | None:
    """Finds a submessage with a specific tag.

    Args:
    decodedMsg (tuple): the decoded message
    tag (RscpTag): the RSCP Tag to search for

    Returns:
        list: the found tag
    """
    try:
        tagStr = getStrRscpTag(tag)
    except KeyError:
        # Tag is unknown to this library
        return None

    if decodedMsg is None:
        return None
    if decodedMsg[0] == tagStr:
        return decodedMsg
    if isinstance(decodedMsg[2], list):
        msgList: List[Tuple[str | int | RscpTag, str | int | RscpType, Any]] = (
            decodedMsg[2]
        )
        for msg in msgList:
            msgValue = rscpFindTag(msg, tag)
            if msgValue is not None:
                return msgValue
    return None


def rscpFindTagIndex(
    decodedMsg: Tuple[str | int | RscpTag, str | int | RscpType, Any] | None,
    tag: int | str | RscpTag,
    index: int = 2,
) -> Any:
    """Finds a submessage with a specific tag and extracts an index.

    Args:
    decodedMsg (Tuple): the decoded message
    tag (RscpTag): the RSCP Tag to search for
    index (int): the index of the found tag to return. Default is 2, the value of the Tag.

    Returns:
        the content of the configured index for the tag.
    """
    res = rscpFindTag(decodedMsg, tag)
    if res is not None:
        return res[index]
    else:
        return None


def endianSwapUint16(val: int):
    """Endian swaps magic and ctrl."""
    return struct.unpack("<H", struct.pack(">H", val))[0]


class FrameError(Exception):
    """Class for Frame Error Exception."""

    pass


def rscpEncode(
    tag: int | str | RscpTag | Tuple[str | int | RscpTag, str | int | RscpType, Any],
    rscptype: int | str | RscpType | None = None,
    data: Any = None,
) -> bytes:
    """RSCP encodes data."""
    if isinstance(tag, tuple):
        rscptype = tag[1]
        data = tag[2]
        tag = tag[0]
    elif rscptype is None:
        raise TypeError("Second argument must not be none if first is not a tuple")

    tagHex = getHexRscpTag(tag)
    rscptypeHex = getHexRscpType(rscptype)
    rscptype = getRscpType(rscptype)

    if DEBUG_DICT["print_rscp"]:
        print(">", tag, rscptype, data)

    if isinstance(data, str):
        data = data.encode("utf-8")

    packFmt = (
        "<IBH"  # format of header: little-endian, Uint32 tag, Uint8 type, Uint16 length
    )
    headerLen = struct.calcsize(packFmt)

    if rscptype == RscpType.NoneType:  # special case: no content
        return struct.pack(packFmt, tagHex, rscptypeHex, 0)
    elif (
        rscptype == RscpType.Timestamp
    ):  # timestamp has a special format, divided into 32 bit integers
        ts = int(data / 1000)  # this is int64
        ms = (data - ts * 1000) * 1e6  # ms are multiplied by 10^6

        hiword = ts >> 32
        loword = ts & 0xFFFFFFFF

        packFmt += "iii"
        length = struct.calcsize(packFmt) - headerLen

        return struct.pack(packFmt, tagHex, rscptypeHex, length, hiword, loword, ms)
    elif rscptype == RscpType.Container:
        if isinstance(data, list):
            newData = b""
            dataList: List[Tuple[str | int | RscpTag, str | int | RscpType, Any]] = data
            for dataChunk in dataList:
                newData += rscpEncode(
                    dataChunk[0], dataChunk[1], dataChunk[2]
                )  # transform each dataChunk into byte array
            data = newData
            packFmt += str(len(data)) + packFmtDict_VarSize[rscptype]
    elif rscptype in packFmtDict_FixedSize:
        packFmt += packFmtDict_FixedSize[rscptype]
    elif rscptype in packFmtDict_VarSize:
        packFmt += str(len(data)) + packFmtDict_VarSize[rscptype]

    length = struct.calcsize(packFmt) - headerLen
    return struct.pack(packFmt, tagHex, rscptypeHex, length, data)


def rscpFrame(data: bytes) -> bytes:
    """Generates RSCP frame."""
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


def rscpFrameDecode(frameData: bytes, returnFrameLen: bool = False):
    """Decodes RSCP Frame."""
    headerFmt = "<HHIIIH"
    crcFmt = "I"
    crc = None

    magic, ctrl, sec1, _, ns, length = struct.unpack(
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


def rscpDecode(
    data: bytes,
) -> Tuple[Tuple[str | int | RscpTag, str | int | RscpType, Any], int]:
    """Decodes RSCP data."""
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
    strTag = getStrRscpTag(hexTag)
    strType = getStrRscpType(hexType)
    type_ = getRscpType(hexType)

    if type_ == RscpType.Container:
        # this is a container: parse the inside
        dataList: List[Tuple[str | int | RscpTag, str | int | RscpType, Any]] = []
        curByte = headerSize
        while curByte < headerSize + length:
            innerData, usedLength = rscpDecode(data[curByte:])
            curByte += usedLength
            dataList.append(innerData)
        return (strTag, strType, dataList), curByte
    elif type_ == RscpType.Timestamp:
        fmt = "<iii"
        hiword, loword, ms = struct.unpack(
            fmt, data[headerSize : headerSize + struct.calcsize(fmt)]
        )
        # t = float((hiword << 32) + loword) + (float(ms)*1e-9) # this should work, but doesn't
        t = float(hiword + loword) + (float(ms) * 1e-9)  # this seems to be correct
        return (strTag, strType, t), headerSize + struct.calcsize(fmt)
    elif type_ == RscpType.NoneType:
        return (strTag, strType, None), headerSize
    elif type_ in packFmtDict_FixedSize:
        fmt = "<" + packFmtDict_FixedSize[type_]
    elif type_ in packFmtDict_VarSize:
        fmt = "<" + str(length) + packFmtDict_VarSize[type_]
    else:
        raise Exception("data can't be decoded")

    val = struct.unpack(fmt, data[headerSize : headerSize + struct.calcsize(fmt)])[0]

    if type_ == RscpType.Error:
        val = getStrRscpError(int.from_bytes(val, "little"))
    elif isinstance(val, bytes) and type_ == RscpType.CString:
        # return string instead of bytes
        # ignore none utf-8 bytes
        val = val.decode("utf-8", "ignore")

    if DEBUG_DICT["print_rscp"]:
        print("<", strTag, strType, val)

    return (strTag, strType, val), headerSize + struct.calcsize(fmt)
