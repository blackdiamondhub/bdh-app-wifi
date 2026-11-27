"""Assistant tool: the guest Wi-Fi, for the hub's voice/chat assistant.

One read-only lookup for every mode: the name and password of each network
the WiFi page shows to everyone. Admins-only networks are never part of the
answer, in any mode (the page only shows them to signed-in admins, and an
assistant session never signs in).
"""
from __future__ import annotations

from bdh_sdk import ALL_MODES
from bdh_sdk.tools import Tool, ToolError

WIFI_INFO = "wifi_info"
ON_SCREEN = "It's also on the WiFi page of the hub's screen, with a QR code to scan."
NONE_SET = "No guest WiFi network is set up on the hub. Please ask your host."
OPEN = "none, it's an open network"


def tools(mode=None):
    return [
        Tool(WIFI_INFO, "Guest WiFi",
             "The lodge's guest WiFi network name and password. Use for 'what's the wifi password?', "
             "'what's the wifi called?', 'how do I get on the internet?'.",
             modes=ALL_MODES, readonly=True),
    ]


def guest_networks():
    """``[{"network", "password"}]`` for each network shown to everyone."""
    from .views import _networks

    return [{"network": ssid, "password": password or OPEN} for ssid, password in _networks(admin=False)]


def run_tool(tool_id, args, mode=None):
    if tool_id != WIFI_INFO:
        raise ToolError(f"Unknown tool {tool_id!r}")
    networks = guest_networks()
    if not networks:
        raise ToolError(NONE_SET)
    out = dict(networks[0]) if len(networks) == 1 else {"networks": networks}
    out["note"] = ON_SCREEN
    return out
