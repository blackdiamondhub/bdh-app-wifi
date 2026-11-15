from bdh_sdk import PluginSpec, SettingsPage, Tile
from bdh_sdk.plugins import LIFECYCLE_ON_DEMAND, NETWORK_NONE

GUESTS = "guests"
ADMINS = "admins"
# The old Settings page had this many fixed network slots; they're imported once.
LEGACY_SLOTS = 4


spec = PluginSpec(
    id="wifi",
    app="wifi",
    urls="wifi.urls",
    tiles=(
        Tile(
            title="WiFi",
            url_name="wifi_qr",
            icon="wifi/hub/icon.svg",
            section="more",
            subtitle="Connect to the internet",
            order=10,
        ),
    ),
    settings_pages=(
        SettingsPage("WiFi networks", "wifi_networks",
                     subtitle="Networks guests can join by scanning a QR code", icon="fas fa-wifi"),
    ),
    api_version=2,
    # Only reads its own settings; the QR codes are drawn locally.
    permissions=(),
    network=NETWORK_NONE,
    # A page people open now and then; nothing to do in the background.
    lifecycle=LIFECYCLE_ON_DEMAND,
    memory_mb=96,
)
