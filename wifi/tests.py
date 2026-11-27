import base64
import io
import os
import xml.etree.ElementTree as ET
from unittest import mock
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import TestCase, tag, override_settings, Client
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from django.contrib.auth.models import User
from django.urls import reverse

from PIL import Image, ImageDraw
from pyzbar.pyzbar import decode
from tests.selenium_helpers import click_until, get_chrome_options, login_from_page

from wifi.models import LegacyImport, Network
from wifi.views import qr_svg

def _rasterize_qr_svg(svg, scale=12):
    """Rasterize the SVG from wifi.views.qr_svg (circles, finder rects and the
    nested logo <svg>) with PIL. The logo area is painted solid black, the
    worst case a scanner can see there."""
    ns = "{http://www.w3.org/2000/svg}"
    root = ET.fromstring(svg)
    n = float(root.get("viewBox").split()[2])
    img = Image.new("L", (int(n * scale), int(n * scale)), 255)
    draw = ImageDraw.Draw(img)
    for el in root.iter():
        if el.tag == ns + "circle":
            cx, cy, r = (float(el.get(k)) * scale for k in ("cx", "cy", "r"))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=0)
        elif el.tag == ns + "rect" and el.get("x") is not None:
            x, y, w, h = (float(el.get(k)) * scale for k in ("x", "y", "width", "height"))
            if el.get("fill") == "none":
                sw = float(el.get("stroke-width")) * scale
                draw.rectangle([x - sw / 2, y - sw / 2, x + w + sw / 2, y + h + sw / 2], outline=0, width=int(sw))
            else:
                draw.rectangle([x, y, x + w, y + h], fill=0)
        elif el.tag == ns + "svg" and el is not root:
            x, y, w = (float(el.get(k)) * scale for k in ("x", "y", "width"))
            draw.rectangle([x, y, x + w, y + w], fill=0)
    return img


def _decode_data_uri_svg(content):
    """Decode the QR code image (img.qr-code) in a page. Other SVG data URIs,
    like the hub's monogram in the header, are skipped."""
    start = content.find('class="qr-code"')
    assert start != -1, "QR code image not found"
    start = content.rfind("<img", 0, start)
    start = content.find(SVG_DATA_URI, start)
    assert start != -1, "QR code SVG data URI not found"
    start += len(SVG_DATA_URI)
    svg = base64.b64decode(content[start:content.find('"', start)]).decode("utf-8")
    return [d.data.decode("utf-8") for d in decode(_rasterize_qr_svg(svg))]


def _decode_element(img_element):
    """Decode the QR code as the browser rendered it, logo included."""
    image = Image.open(io.BytesIO(img_element.screenshot_as_png))
    decoded = decode(image)
    assert decoded, "No QR code detected in the rendered image"
    return decoded[0].data.decode("utf-8")


SVG_DATA_URI = "data:image/svg+xml;base64,"


class WifiQRGenerationTests(TestCase):
    def setUp(self):
        self.client = Client()

    @override_settings(BDH_WIFI_SSID_1="TestNetwork", BDH_WIFI_PASSWORD_1="testpass123")
    def test_qr_code_generation_from_settings(self):
        response = self.client.get("/wifi/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertEqual(_decode_data_uri_svg(content), ["WIFI:S:TestNetwork;T:WPA;P:testpass123;;"])

    def test_qr_with_logo_scans_for_long_passwords(self):
        """Longer payloads need bigger QR versions; the logo hole scales with
        them and must stay within what error correction can recover."""
        for password in ("x", "correct-horse-battery-staple-" * 3):
            text = f"WIFI:S:Black Diamond Lodge Guest;T:WPA;P:{password};;"
            decoded = [d.data.decode("utf-8") for d in decode(_rasterize_qr_svg(qr_svg(text)))]
            self.assertEqual(decoded, [text])

    @override_settings(BDH_WIFI_SSID_1="Guest", BDH_WIFI_SSID_2="Private",
                       BDH_WIFI_AUDIENCE_2="admins")
    def test_private_networks_are_admin_only(self):
        def ssids():
            return [q["ssid"] for q in self.client.get("/wifi/").context["qr_codes"]]

        self.assertEqual(ssids(), ["Guest"])
        user = User.objects.create_user(username="member", password="pw")
        self.client.force_login(user)
        self.assertEqual(ssids(), ["Guest"])
        user.is_staff = True
        user.save()
        self.assertEqual(ssids(), ["Private"])

    def test_qr_embeds_monogram(self):
        self.assertIn('class="qr-logo"', qr_svg("WIFI:S:x;T:WPA;P:y;;"))

@tag('selenium')
@override_settings(
    BDH_WIFI_SSID_1="TestNetwork", BDH_WIFI_PASSWORD_1="testpass123",
    BDH_WIFI_SSID_2="TestNetwork2", BDH_WIFI_PASSWORD_2="testpass1232",
    BDH_WIFI_SSID_3="TestNetworkAuth", BDH_WIFI_PASSWORD_3="testpass1233",
    BDH_WIFI_AUDIENCE_3="admins",
    BDH_WIFI_SSID_4="TestNetworkAuth2", BDH_WIFI_PASSWORD_4="testpass1234",
    BDH_WIFI_AUDIENCE_4="admins",
)
class WifiQRPageSeleniumTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.driver = webdriver.Chrome(options=get_chrome_options())
        cls.driver.set_window_size(1920, 1080)
        
    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        super().tearDownClass()
        
    def setUp(self):
        # Reset browser state between tests
        self.driver.get('about:blank')
        self.driver.delete_all_cookies()

        self.test_user = User.objects.create_user(username='testuser', password='testpassword', is_staff=True)
        
    def test_wifi_page_title_and_header(self):
        """Verify that the wifi page title and header are correct."""
        self.driver.get(f'{self.live_server_url}/wifi/')
        header = WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        self.assertEqual(header.get_attribute("textContent").strip(), "WiFi Networks")
        
    # def test_qr_codes_container_is_centered(self):
    #     """
    #     Verify that the container holding the QR codes is centered both vertically and horizontally.
    #     """
    #     self.driver.get(f'{self.live_server_url}/wifi/')
        
    #     self.driver.save_screenshot("screenshot.png")
        
    #     # Wait for the container to be present. Adjust the selector if necessary.
    #     container = self.driver.find_element(By.CSS_SELECTOR, '.container.full-height')
        
    #     # Get the container's bounding rectangle.
    #     container_rect = container.rect  # returns {'height': ..., 'width': ..., 'x': ..., 'y': ...}
        
    #     # Get the window size.
    #     window_size = self.driver.get_window_size()  # returns dict with keys 'width' and 'height'
        
    #     # Calculate expected x and y positions for centering.
    #     expected_x = (window_size['width'] - container_rect['width']) / 2
    #     expected_y = (window_size['height'] - container_rect['height']) / 2
        
    #     # Allow a small tolerance for differences due to rendering.
    #     tolerance = 10  # pixels
        
    #     self.assertAlmostEqual(
    #         container_rect['x'], 
    #         expected_x, 
    #         delta=tolerance, 
    #         msg=f"Container is not centered horizontally. Expected x ~{expected_x}, got {container_rect['x']}"
    #     )
        
    #     self.assertAlmostEqual(
    #         container_rect['y'], 
    #         expected_y, 
    #         delta=tolerance, 
    #         msg=f"Container is not centered vertically. Expected y ~{expected_y}, got {container_rect['y']}"
    #     )        
        
    def test_wifi_page_no_auth_qr_codes(self):
        """Verify that no QR codes for authenticated networks are displayed for unauthenticated users."""
        self.driver.get(f'{self.live_server_url}/wifi/')
        # Wait for QR code images to load
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img.qr-code"))
        )
        # Find all QR code images.
        qr_images = self.driver.find_elements(By.CSS_SELECTOR, "img.qr-code")
        self.assertGreater(len(qr_images), 0, "No QR code images found on the page")
        
        # Define the expected auth QR texts that should NOT be present.
        auth_qr_texts = {
            f"WIFI:S:TestNetworkAuth;T:WPA;P:testpass1233;;",
            f"WIFI:S:TestNetworkAuth2;T:WPA;P:testpass1234;;"
        }
        
        # Iterate through each found QR code image.
        for img in qr_images:
            decoded_text = _decode_element(img)
            
            # Ensure no auth network QR data is present.
            self.assertNotIn(
                decoded_text,
                auth_qr_texts,
                f"Auth QR code '{decoded_text}' should not be displayed for non-authenticated users"
            )
        
    def test_wifi_page_public_qr_code(self):
        """Verify that the public QR code is displayed correctly."""
        self.driver.get(f'{self.live_server_url}/wifi/')
        
        # Wait for QR code images to load
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img.qr-code"))
        )
        # Verify that at least one QR code image is present.
        qr_images = self.driver.find_elements(By.CSS_SELECTOR, "img.qr-code")
        self.assertGreater(len(qr_images), 0, "No QR code images found on the page")
        
        # Optionally, assert that each found image has valid dimensions and correct QR data.
        expected_qr_texts = {
            f"WIFI:S:TestNetwork;T:WPA;P:testpass123;;",
            f"WIFI:S:TestNetwork2;T:WPA;P:testpass1232;;"
        }
        found_qr_texts = set()

        for img in qr_images:
            # Ensure the image has non-zero width.
            width = img.size.get("width", 0)
            self.assertGreater(width, 0, f"Image width should be > 0 but got {width}")

            decoded_text = _decode_element(img)
            self.assertIn(
                decoded_text,
                expected_qr_texts,
                f"Decoded QR text '{decoded_text}' not one of the expected values."
            )
            found_qr_texts.add(decoded_text)

        # Verify that we found all expected QR codes.
        self.assertEqual(found_qr_texts, expected_qr_texts, "Not all expected QR codes were found.")
        
    def test_wifi_page_login_redirects_back_to_wifi(self):
        """
        Test that after logging in, the user is redirected back to the wifi page.
        """
       
        self.driver.get(f"{self.live_server_url}/wifi/")
        
        # Log in using shared helper
        login_from_page(self.driver, self.live_server_url)
        
        # Wait for redirect back to wifi page
        WebDriverWait(self.driver, 20).until(
            EC.url_contains("/wifi/")
        )
        
        # Check that the current URL is the wifi page.
        self.assertIn("/wifi/", self.driver.current_url)
        
    def test_wifi_page_logout_redirects_back_to_wifi(self):
        """
        Test that after logging out, the user is redirected back to the wifi page.
        """
     
        self.driver.get(f"{self.live_server_url}/wifi/")
        
        # Log in using shared helper
        login_from_page(self.driver, self.live_server_url)
        
        # Sign out lives in the account menu, so open that first.
        click_until(self.driver, (By.ID, 'user-menu-button'),
                    lambda d: d.find_element(By.ID, 'logout-button').is_displayed())
        click_until(self.driver, (By.ID, 'logout-button'),
                    EC.presence_of_element_located((By.ID, 'login-button')), settle=10)

        self.assertIn("/wifi/", self.driver.current_url)
        
    def test_wifi_page_no_public_qr_codes(self):
        """
        Log in a test user and verify that none of the public QR codes are present.
        """
       
        self.driver.get(f"{self.live_server_url}/wifi/")
        
        # Log in using shared helper
        login_from_page(self.driver, self.live_server_url)
        
        # Wait for redirect back to wifi page and QR codes to load
        WebDriverWait(self.driver, 20).until(
            EC.url_contains("/wifi/")
        )
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img.qr-code"))
        )
    
        qr_images = self.driver.find_elements(By.CSS_SELECTOR, "img.qr-code")
        self.assertGreater(len(qr_images), 0, "No QR code images found on the page")
        
        # Define the expected public QR texts that should NOT be present after login.
        public_qr_texts = {
            f"WIFI:S:TestNetwork;T:WPA;P:testpass123;;",
            f"WIFI:S:TestNetwork2;T:WPA;P:testpass1232;;"
        }
        
        for img in qr_images:
            decoded_text = _decode_element(img)

            # Ensure that the decoded text is not one of the public QR codes.
            self.assertNotIn(
                decoded_text,
                public_qr_texts,
                f"Public QR code '{decoded_text}' should not be displayed for authenticated users"
            )        
        
    
    def test_wifi_page_auth_qr_codes(self):
        """
        Log in a test user and verify that the auth QR codes are present.
        """
        
        self.driver.get(f"{self.live_server_url}/wifi/")
        
        # Log in using shared helper
        login_from_page(self.driver, self.live_server_url)
        
        # Wait for redirect back to wifi page
        WebDriverWait(self.driver, 20).until(
            EC.url_contains("/wifi/")
        )
        
        # Wait for QR code images to load
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img.qr-code"))
        )
        
        qr_images = self.driver.find_elements(By.CSS_SELECTOR, "img.qr-code")
        self.assertGreater(len(qr_images), 0, "No QR code images found on the page")
        
        # Expected auth QR texts based on overridden settings.
        expected_auth_qr_texts = {
            f"WIFI:S:TestNetworkAuth;T:WPA;P:testpass1233;;",
            f"WIFI:S:TestNetworkAuth2;T:WPA;P:testpass1234;;"
        }
        found_auth_qr_texts = set()
        
        for img in qr_images:
            decoded_text = _decode_element(img)
            
            if decoded_text in expected_auth_qr_texts:
                found_auth_qr_texts.add(decoded_text)
        
        self.assertEqual(
            found_auth_qr_texts,
            expected_auth_qr_texts,
            "Not all expected auth QR codes were found on the logged in page."
        )

class WifiSettingsTests(TestCase):
    @mock.patch.dict(os.environ, {
        "BDH_WIFI_SSID_1": "Lodge Guest",
        "BDH_WIFI_PASSWORD_1": "s3cret",
        "BDH_WIFI_SSID_3": "Lodge Open",
    })
    def test_namespaced_env_settings(self):
        response = Client().get(reverse("wifi_qr"))
        self.assertEqual(response.status_code, 200)
        codes = [(c["ssid"], c["password"]) for c in response.context["qr_codes"]]
        self.assertEqual(codes, [("Lodge Guest", "s3cret"), ("Lodge Open", "")])
        # SSID chosen so the SDK QR (ECC H + logo hole) decodes; a few short
        # version-3 payloads such as "WIFI:S:Other;T:nopass;;" do not (SDK qr_svg gap).
        open_svg = base64.b64decode(response.context["qr_codes"][1]["qr_image"]).decode("utf-8")
        self.assertEqual([d.data.decode("utf-8") for d in decode(_rasterize_qr_svg(open_svg))],
                         ["WIFI:S:Lodge Open;T:nopass;;"])

    def test_no_networks_configured_shows_none(self):
        # The base app must not ship a site-specific default network.
        with mock.patch.dict(os.environ, {}, clear=True):
            response = Client().get(reverse("wifi_qr"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["qr_codes"], [])

    @mock.patch.dict(os.environ, {
        "BDH_WIFI_SSID_1": "y'all guest",
        "BDH_WIFI_PASSWORD_1": "pa;ss:wo,rd\\\"x",
    })
    def test_ssid_with_punctuation_and_escaped_qr(self):
        response = Client().get(reverse("wifi_qr"))
        codes = response.context["qr_codes"]
        self.assertEqual([(c["ssid"], c["password"]) for c in codes],
                         [("y'all guest", 'pa;ss:wo,rd\\"x')])
        svg = base64.b64decode(codes[0]["qr_image"]).decode("utf-8")
        self.assertEqual([d.data.decode("utf-8") for d in decode(_rasterize_qr_svg(svg))],
                         ['WIFI:S:y\'all guest;T:WPA;P:pa\\;ss\\:wo\\,rd\\\\\\"x;;'])


class WifiManifestTests(TestCase):
    def test_hub_api_2_manifest(self):
        from wifi.plugin import spec

        manifest = spec.manifest()
        self.assertEqual(manifest["api_version"], 2)
        self.assertEqual(manifest["permissions"], [])
        self.assertEqual(manifest["network"], "none")
        self.assertEqual(manifest["lifecycle"], "on_demand")

    def test_plugin_module_imports_cleanly(self):
        from bdh_sdk.testing import assert_plugin_importable

        assert_plugin_importable("wifi.plugin")


class WifiBrokerTests(TestCase):
    """In its container the app reads the networks from the hub broker."""

    def setUp(self):
        from bdh_sdk import settings
        from bdh_sdk.testing import FakeBroker

        saved = settings._store
        self.broker = FakeBroker(grants=("settings.get",), install=True)
        self.broker.start()
        self.addCleanup(settings.set_store, saved)
        self.addCleanup(self.broker.stop)

    def test_networks_from_hub_settings(self):
        self.broker.settings.update({
            ("wifi", "ssid_1"): "Lodge Guest", ("wifi", "password_1"): "s3cret",
            ("wifi", "ssid_2"): "Lodge Staff", ("wifi", "password_2"): "staff",
            ("wifi", "audience_2"): "admins",
        })
        with mock.patch.dict(os.environ, {}, clear=True):
            response = Client().get(reverse("wifi_qr"))
        self.assertEqual([(c["ssid"], c["password"]) for c in response.context["qr_codes"]],
                         [("Lodge Guest", "s3cret")])
        asked = {p["key"] for p in self.broker.ops("settings.get") if p["app"] == "wifi"}
        self.assertTrue({"ssid_1", "password_1", "audience_1", "ssid_2", "audience_2"} <= asked)


class WifiNetworksPageTests(TestCase):
    """Settings › WiFi networks: one card per network, like calendar feeds."""

    def setUp(self):
        self.url = reverse("wifi_networks")
        self.admin = User.objects.create_user("owner", password="x", is_staff=True)

    def _post(self, **data):
        self.client.force_login(self.admin)
        return self.client.post(self.url, data)

    def test_admins_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(User.objects.create_user("member", password="x"))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self._post(action="add", ssid="x").status_code, 302)  # the admin may
        self.client.force_login(User.objects.create_user("member2", password="x"))
        self.assertEqual(self.client.post(self.url, {"action": "add", "ssid": "y"}).status_code, 404)
        self.assertEqual(list(Network.objects.values_list("ssid", flat=True)), ["x"])

    def test_empty_shows_add_form(self):
        self.client.force_login(self.admin)
        page = self.client.get(self.url)
        self.assertContains(page, "No networks yet.")
        self.assertTrue(page.context["add_open"])

    def test_add_save_delete(self):
        r = self._post(action="add", ssid="Lodge Guest", password="s3cret123", audience="guests")
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self._post(action="add", ssid="Lodge Staff", password="", audience="admins")
        guest, staff = Network.objects.all()
        self.assertEqual((guest.ssid, guest.password, guest.audience, guest.order),
                         ("Lodge Guest", "s3cret123", "guests", 0))
        self.assertEqual((staff.audience, staff.order), ("admins", 1))
        page = self.client.get(self.url)
        self.assertContains(page, "Added Lodge Staff.")
        self.assertContains(page, '<span class="nm">Lodge Guest</span>')
        self.assertFalse(page.context["add_open"])

        self._post(action="save", id=guest.id, ssid="Lodge Guests", password="newpass99", audience="admins")
        guest.refresh_from_db()
        self.assertEqual((guest.ssid, guest.password, guest.audience), ("Lodge Guests", "newpass99", "admins"))

        self._post(action="delete", id=staff.id)
        self.assertEqual(list(Network.objects.values_list("ssid", flat=True)), ["Lodge Guests"])
        self.assertEqual(self._post(action="delete", id=9999).status_code, 404)

    def test_validation(self):
        for data, msg in (({"ssid": " "}, "Enter the network name."),
                          ({"ssid": "x" * 33}, "at most 32 bytes"),
                          ({"ssid": "ok", "password": "short"}, "8 to 63 characters"),
                          ({"ssid": "ok", "password": "x" * 64}, "8 to 63 characters")):
            r = self._post(action="add", **data)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, msg)
            self.assertTrue(r.context["add_open"])
        self.assertFalse(Network.objects.exists())
        net = Network.objects.create(ssid="Keep", password="keepkeep")
        r = self._post(action="save", id=net.id, ssid="", password="")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["open_id"], net.id)
        net.refresh_from_db()
        self.assertEqual(net.ssid, "Keep")

    def test_qr_page_reads_the_networks(self):
        Network.objects.create(ssid="Lodge Guest", password="s3cret123", order=1)
        Network.objects.create(ssid="Lodge Open", order=0)
        Network.objects.create(ssid="Lodge Staff", password="staffstaff", audience="admins")
        codes = [(c["ssid"], c["password"]) for c in self.client.get(reverse("wifi_qr")).context["qr_codes"]]
        self.assertEqual(codes, [("Lodge Open", ""), ("Lodge Guest", "s3cret123")])
        self.client.force_login(self.admin)
        codes = [c["ssid"] for c in self.client.get(reverse("wifi_qr")).context["qr_codes"]]
        self.assertEqual(codes, ["Lodge Staff"])

    @mock.patch.dict(os.environ, {
        "BDH_WIFI_SSID_1": "Lodge Guest", "BDH_WIFI_PASSWORD_1": "s3cret",
        "BDH_WIFI_SSID_3": "Lodge Staff", "BDH_WIFI_AUDIENCE_3": "admins",
    })
    def test_old_slots_imported_once(self):
        self.client.force_login(self.admin)
        self.client.get(self.url)
        self.assertEqual(list(Network.objects.values_list("ssid", "password", "audience")),
                         [("Lodge Guest", "s3cret", "guests"), ("Lodge Staff", "", "admins")])
        # Removing them all must not bring them back.
        for net in Network.objects.all():
            self._post(action="delete", id=net.id)
        self.client.get(self.url)
        self.client.get(reverse("wifi_qr"))
        self.assertFalse(Network.objects.exists())
        self.assertEqual(LegacyImport.objects.count(), 1)

    def test_import_retried_when_settings_unreadable(self):
        with mock.patch("wifi.views.app_setting", side_effect=RuntimeError("broker down")):
            self.client.get(reverse("wifi_qr"))
        self.assertFalse(LegacyImport.objects.exists())
        with mock.patch.dict(os.environ, {"BDH_WIFI_SSID_1": "Later"}):
            self.client.get(reverse("wifi_qr"))
        self.assertEqual(list(Network.objects.values_list("ssid", flat=True)), ["Later"])

    def test_manifest_has_a_settings_page_not_fields(self):
        from wifi.plugin import spec

        self.assertEqual(tuple(spec.settings), ())
        self.assertEqual([(p.title, p.url_name) for p in spec.settings_pages], [("WiFi networks", "wifi_networks")])


class HubFrameLayoutTests(TestCase):
    """The app renders inside the hub's iframe, already below the hub navbar, so its
    CSS must not reserve space for that navbar (top:62px / 100vh-62px / phone 118px)
    nor scope rules under the hub's `.navbar`, which doesn't exist in the iframe."""

    def test_no_hub_navbar_offsets(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent
        self.assertTrue((root / "templates").is_dir(), root)
        pattern = re.compile(r"top\s*:\s*(6[0-9]|118)px|100vh\s*-\s*(6[0-9]|118)px|\.navbar(?![-\w])")
        hits = []
        for path in list(root.glob("templates/**/*.html")) + list(root.glob("static/**/*.css")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(root)}:{n}: {line.strip()}")
        self.assertEqual(hits, [])


class WifiAssistantToolTests(TestCase):
    """The assistant's guest WiFi lookup never hands out an admins-only network."""

    def setUp(self):
        LegacyImport.objects.create()
        Network.objects.create(ssid="Lodge Guest", password="guestpass1", audience="guests", order=0)
        Network.objects.create(ssid="Lodge Owner", password="ownersecret9", audience="admins", order=1)
        Network.objects.create(ssid="Lodge IoT", password="iotsecret77", audience="admins", order=2)

    def run_tool(self, mode="guest"):
        from wifi import assistant
        return assistant.run_tool("wifi_info", {}, mode=mode)

    def test_every_mode_gets_one_readonly_lookup(self):
        from bdh_sdk import ALL_MODES, hooks
        from wifi import assistant
        from wifi.plugin import spec
        for mode in sorted(ALL_MODES):
            with self.subTest(mode=mode):
                tools = assistant.tools(mode=mode)
                self.assertEqual([t.id for t in tools], ["wifi_info"])
                self.assertEqual((tools[0].modes, tools[0].readonly, tools[0].confirm), (ALL_MODES, True, False))
                self.assertLessEqual(len(tools[0].description), 300)
        self.assertEqual([t["id"] for t in hooks.run(spec, "tools", mode="guest")], ["wifi_info"])

    def test_guest_network_and_password(self):
        self.assertEqual(self.run_tool(), {
            "network": "Lodge Guest", "password": "guestpass1",
            "note": "It's also on the WiFi page of the hub's screen, with a QR code to scan."})

    def test_admins_only_networks_never_in_any_mode(self):
        import json
        from bdh_sdk import ALL_MODES
        Network.objects.create(ssid="Lodge Guest 5G", password="", audience="guests", order=3)
        for mode in sorted(ALL_MODES):
            with self.subTest(mode=mode):
                result = self.run_tool(mode)
                self.assertEqual([(n["network"], n["password"]) for n in result["networks"]],
                                 [("Lodge Guest", "guestpass1"), ("Lodge Guest 5G", "none, it's an open network")])
                text = json.dumps(result)
                for secret in ("Lodge Owner", "ownersecret9", "Lodge IoT", "iotsecret77"):
                    self.assertNotIn(secret, text)

    def test_no_guest_network(self):
        from bdh_sdk.tools import ToolError
        Network.objects.filter(audience="guests").delete()
        with self.assertRaisesMessage(ToolError, "No guest WiFi network is set up on the hub."):
            self.run_tool()