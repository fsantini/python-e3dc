"""Example script demonstrating Dynamic Power Pricing (DPP) features.

This example shows how to read and configure DPP settings for battery and
wallbox charging based on dynamic electricity prices.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from e3dc import E3DC  # noqa: E402

# Connection parameters
TCP_IP = "192.168.1.57"
USERNAME = "user@example.com"
PASS = "your_password"
KEY = "your_rscp_key"
CONFIG = {
    "powermeters": [
        {"index": 0, "type": 1, "typeName": "PM_TYPE_ROOT"},
    ]
}

print("Connecting to E3/DC system...")
print(f"IP: {TCP_IP}")
print(f"Username: {USERNAME}")

try:
    e3dc_obj = E3DC(
        E3DC.CONNECT_LOCAL,
        username=USERNAME,
        password=PASS,
        ipAddress=TCP_IP,
        key=KEY,
        configuration=CONFIG,
    )
    print("✓ Successfully connected!")
except Exception as e:
    print(f"\n✗ Connection failed: {type(e).__name__}")
    print(f"Error: {e}")
    print("\nPossible causes:")
    print("- Wrong RSCP encryption key (check E3/DC device settings)")
    print("- Wrong username or password")
    print("- E3/DC device not reachable at the specified IP address")
    print("- Firewall blocking connection to port 5033")
    sys.exit(1)

# Get current DPP data
print("\n=== Reading Battery DPP Data ===")
dpp_data = e3dc_obj.get_dpp_data(keepAlive=True)

print(f"DPP Battery Charging Enabled: {dpp_data['price_based_battery_charge_enabled']}")
print(
    f"DPP Battery Charging Currently Active: "
    f"{dpp_data['price_based_battery_charge_active']}"
)
print(f"Price Limit for Battery Charging: {dpp_data['price_limit_battery']} €/kWh")
print(f"Target Battery SOC: {dpp_data['soc_battery']}%")
print(f"Active Months (bitmask): {dpp_data['months_active']}")
if "months_active_string" in dpp_data:
    print(f"Active Months (string): {dpp_data['months_active_string']}")
    print("  (Uppercase letters = active months: jfmamjjasond)")

# Example: Configure DPP settings
print("\n=== Battery DPP Configuration Examples (commented out) ===")
# print("Example 1: Enable battery DPP with price limit of 0.27 €/kWh")
# results = e3dc_obj.set_dpp_battery_charging(
#     enabled=True,
#     price_limit=0.27,
#     soc_target=80,
#     months_active="JFMAmjjasOND",  # Jan, Feb, Mar, Apr, Oct, Nov,
#                                     # Dec active
#     keepAlive=True
# )
# print(f"Results: {results}")

# print("\nExample 2: Activate battery DPP only for winter months")
# results = e3dc_obj.set_dpp_battery_charging(
#     months_active="JFmamjjasOND",  # Jan, Feb, Oct, Nov, Dec active
#     keepAlive=True
# )
# print(f"Results: {results}")

# print("\nExample 3: Disable battery DPP charging")
# results = e3dc_obj.set_dpp_battery_charging(
#     enabled=False,
#     keepAlive=True
# )
# print(f"Results: {results}")

# Disconnect
e3dc_obj.disconnect()
print("\nDisconnected from E3/DC system")
