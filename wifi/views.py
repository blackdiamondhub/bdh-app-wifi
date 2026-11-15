import base64
import logging
import re
from functools import wraps

from bdh_sdk import is_admin
from bdh_sdk.qr import qr_svg
from bdh_sdk.settings import app_setting
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .models import AUDIENCES, LegacyImport, Network
from .plugin import ADMINS, GUESTS, LEGACY_SLOTS

APP_ID = "wifi"
log = logging.getLogger(__name__)
# Characters the Wi-Fi QR format requires to be backslash-escaped.
_QR_SPECIAL = re.compile(r'([\\;,:"])')
NOTE = "wifi_note"
OPEN = "wifi_open"


def _qr_escape(text):
    return _QR_SPECIAL.sub(r"\\\1", text)


def _import_legacy():
    """Copy the networks from the old fixed Settings slots, once.

    They were hub settings (or ``BDH_WIFI_SSID_<n>`` env vars) before the
    networks moved into this app's own table.
    """
    if LegacyImport.objects.exists():
        return
    try:
        slots = []
        for n in range(1, LEGACY_SLOTS + 1):
            ssid = str(app_setting(APP_ID, f"ssid_{n}", "") or "").strip()
            if ssid:
                audience = str(app_setting(APP_ID, f"audience_{n}", "") or "").strip()
                slots.append((ssid, str(app_setting(APP_ID, f"password_{n}", "") or ""),
                              ADMINS if audience == ADMINS else GUESTS))
    except Exception:
        # Try again next time rather than lose the old networks.
        log.warning("could not read the old wifi settings", exc_info=True)
        return
    with transaction.atomic():
        if LegacyImport.objects.select_for_update().exists():
            return
        for order, (ssid, password, audience) in enumerate(slots):
            Network.objects.create(ssid=ssid[:64], password=password[:128],
                                   audience=audience, order=order)
        LegacyImport.objects.create()


def _networks(admin):
    """(ssid, password) for each network the viewer may see.

    Admins see the admins-only networks; everyone else the ones for everyone.
    """
    _import_legacy()
    audience = ADMINS if admin else GUESTS
    return [(n.ssid, n.password) for n in Network.objects.filter(audience=audience)]


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


def _admin_only(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_admin(request):
            raise Http404
        return view(request, *args, **kwargs)
    return wrapped


def _clean(post):
    """(fields, error) from a submitted network form."""
    ssid = (post.get("ssid") or "").strip()
    password = post.get("password") or ""
    audience = post.get("audience") or GUESTS
    if not ssid:
        return None, "Enter the network name."
    if len(ssid.encode("utf-8")) > 32:
        return None, "Network names are at most 32 bytes."
    if password and not 8 <= len(password) <= 63:
        return None, "WiFi passwords are 8 to 63 characters (or leave it empty for an open network)."
    if audience not in dict(AUDIENCES):
        audience = GUESTS
    return {"ssid": ssid, "password": password, "audience": audience}, None


@_admin_only
def networks_page(request):
    _import_legacy()
    add_open = False
    error = None
    form = {}
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            fields, error = _clean(request.POST)
            if fields:
                last = Network.objects.order_by("-order").first()
                net = Network.objects.create(order=(last.order + 1) if last else 0, **fields)
                request.session[NOTE] = ("ok", f"Added {net.ssid}.")
                return redirect("wifi_networks")
            add_open, form = True, request.POST
        elif action in ("save", "delete"):
            net = get_object_or_404(Network, id=request.POST.get("id"))
            if action == "delete":
                net.delete()
                request.session[NOTE] = ("ok", f"Removed {net.ssid}.")
                return redirect("wifi_networks")
            fields, error = _clean(request.POST)
            if fields:
                for k, v in fields.items():
                    setattr(net, k, v)
                net.save()
                request.session[NOTE] = ("ok", f"Saved {net.ssid}.")
                return redirect("wifi_networks")
            request.session[OPEN] = net.id
    note = ("bad", error) if error else request.session.pop(NOTE, None)
    networks = list(Network.objects.all())
    return render(request, "wifi/settings_networks.html", {
        "active": APP_ID,
        "networks": networks,
        "audiences": AUDIENCES,
        "note": note,
        "open_id": request.session.pop(OPEN, None),
        "add_open": add_open or not networks,
        "form": form,
    })
