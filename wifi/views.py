import base64
import re

from bdh_sdk import is_admin
from bdh_sdk.qr import qr_svg
from bdh_sdk.settings import app_setting
from django.shortcuts import render

from .plugin import ADMINS, SLOTS

APP_ID = "wifi"
# Characters the Wi-Fi QR format requires to be backslash-escaped.
_QR_SPECIAL = re.compile(r'([\\;,:"])')


def _qr_escape(text):
    return _QR_SPECIAL.sub(r"\\\1", text)


def _networks(admin):
    """(ssid, password) for each configured network the viewer may see.

    Admins see the admins-only networks; everyone else the ones for everyone.
    """
    found = []
    for n in range(1, SLOTS + 1):
        ssid = str(app_setting(APP_ID, f"ssid_{n}", "") or "").strip()
        if not ssid:
            continue
        audience = str(app_setting(APP_ID, f"audience_{n}", "") or "").strip()
        if (audience == ADMINS) == admin:
            found.append((ssid, str(app_setting(APP_ID, f"password_{n}", "") or "")))
    return found


def wifi_qr(request):
    qr_codes = []
    for ssid, password in _networks(is_admin(request)):
        # Standard Wi-Fi QR format: WIFI:S:<SSID>;T:WPA;P:<password>;;
        if password:
            payload = f"WIFI:S:{_qr_escape(ssid)};T:WPA;P:{_qr_escape(password)};;"
        else:
            payload = f"WIFI:S:{_qr_escape(ssid)};T:nopass;;"
        svg = qr_svg(payload)
        qr_codes.append({
            "ssid": ssid,
            "qr_image": base64.b64encode(svg.encode("utf-8")).decode("ascii"),
            "password": password,
        })

    return render(request, "wifi/wifi_qr.html", {"qr_codes": qr_codes})