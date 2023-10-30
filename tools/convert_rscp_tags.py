"""This is a helper script to convert the enumerations from the "official" RSCP implementation into a format that can be used in the Python implementation.

Requirements (just for this script):
pip install pye3dc[develop]
"""

import argparse
import re
import sys

import jsbeautifier
import requests

parser = argparse.ArgumentParser(description="E3DC rscp tags convert")
parser.add_argument(
    "-r", "--rscpLib", help="rscp library file", default="rscpLibV0.9.3.min.js"
)
args = vars(parser.parse_args())

rscpLib = args["rscpLib"]
source = requests.get(
    "https://s10.e3dc.com/s10/js/{}".format(rscpLib), allow_redirects=True
)
if source.status_code != 200:
    print("Can't download {}".format(rscpLib), file=sys.stderr)
    exit(1)
input = jsbeautifier.beautify(str(source.content, encoding="utf-8"))

rscpTagsFromJS = re.search(r"var rscpTags = {(.*?)getHexTag.*?}", input, re.DOTALL)

if rscpTagsFromJS is None:
    exit(1)

lines = rscpTagsFromJS.group(1).splitlines()

print("class RscpTag(Enum):")
print(
    '    """All available RSCP tags. Generated from https://s10.e3dc.com/s10/js/{}."""\n'.format(
        rscpLib
    )
)

for line in lines:
    line = line.strip()
    if not line:
        continue
    number, string = line.split(": ")
    number = number.strip()
    hex_number = hex(int(float(number))).upper()[2:]
    padded_hex_number = hex_number.zfill(8)
    name = string.removeprefix('"').removesuffix('",').strip()
    enum_entry = f"    {name} = 0x{padded_hex_number}"
    print(enum_entry)
