from bdh_sdk import PluginSpec, Setting, Tile
from bdh_sdk.plugins import CHOICE, LIFECYCLE_ON_DEMAND, NETWORK_NONE

# How many networks the Settings page offers.
SLOTS = 4
GUESTS = "guests"
ADMINS = "admins"


def _network_settings(n):
    return (
        Setting(f"ssid_{n}", f"Network {n}: name (SSID)", default="",
                help="Leave empty to hide this network."),
        Setting(f"password_{n}", f"Network {n}: password", default=""),
        Setting(f"audience_{n}", f"Network {n}: shown to", type=CHOICE, default=GUESTS,
                choices=((GUESTS, "Everyone"), (ADMINS, "Signed-in admins only"))),
    )


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
    settings=tuple(s for n in range(1, SLOTS + 1) for s in _network_settings(n)),
    api_version=2,
    # Only reads its own settings; the QR codes are drawn locally.
    permissions=(),
    network=NETWORK_NONE,
    # A page people open now and then; nothing to do in the background.
    lifecycle=LIFECYCLE_ON_DEMAND,
    memory_mb=96,
)