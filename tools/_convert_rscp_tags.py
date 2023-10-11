# This is a helper script to convert the enumerations from the "official" RSCP
# implementation into a format that can be used in the Python implementation.
#
# The source can be found here:
# https://s10.e3dc.com/s10/js/rscpLibV<x.x.x>.min.js (replace <x.x.x> with the
# version number). At the time of writing, the latest version is 0.9.3.
#
# Requirements (just for this script):
# pip install jsbeautifier

import re

import jsbeautifier

TOOLS_DIR = "tools/"
INPUT_SCRIPT_FILE = "rscpLibV0.9.3.min.js"
OUTPUT_PY_FILE = "generated_enum.py"


def _generate_enum_from_file(input_string, output_file_path):
    lines = input_string.splitlines()
    with open(output_file_path, "w") as outfile:
        outfile.write("class RscpTag(Enum):\n")
        outfile.write(
            f'    """All available RSCP tags. Generated from https://s10.e3dc.com/s10/js/{INPUT_SCRIPT_FILE}."""\n\n'
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
            enum_entry = f"    {name} = 0x{padded_hex_number}\n"
            outfile.write(enum_entry)


input = jsbeautifier.beautify_file(TOOLS_DIR + INPUT_SCRIPT_FILE)
rscpTagsFromJS = re.search(
    r"var rscpTags = {(.*?)getHexTag.*?}", input, re.DOTALL
).group(1)
_generate_enum_from_file(rscpTagsFromJS, TOOLS_DIR + OUTPUT_PY_FILE)
