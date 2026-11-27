# bdh-app-wifi

Black Diamond Hub app that shows Wi-Fi QR codes, so guests can join the
lodge network by scanning. Installed into the hub through the
`blackdiamondhub.plugins` entry point (see
[bdh-sdk](https://github.com/blackdiamondhub/bdh-sdk)).

Page: `/wifi/` (URL name `wifi_qr`). Each network is shown either to everyone
or only to signed-in admins (staff); admins see the admins-only ones.

Each network gets a site-branded SVG QR code from `bdh_sdk.qr.qr_svg`: error
correction level H with the site's monogram over the centre. Special characters
(`\ ; , : "`) in the SSID and password are escaped as the Wi-Fi QR format requires.

## Settings

Up to four networks, set on the hub's Settings page (saved in the hub and read
over the broker with `bdh_sdk.settings.app_setting`). For local development the
`BDH_WIFI_<KEY>` environment variables are the fallback.

| Key | Meaning | Default |
|---|---|---|
| `ssid_<n>` | Network name; empty hides slot `<n>` | empty |
| `password_<n>` | Password; empty makes an open-network QR code | empty |
| `audience_<n>` | `guests` (everyone) or `admins` (signed-in admins only) | `guests` |

The old `NETWORKS_PUBLIC`/`NETWORKS_AUTH`/`PASSWORD_FOR_<SSID>` settings and
their `WIFI_*` environment names are gone in 2.0: re-enter the networks on the
Settings page.

## Assistant tools

The hub's assistant (e.g. the voice app) can read out the guest WiFi through one read-only
tool, offered in every mode (guest, dashboard and owner). The hub only offers it when `wifi` is
in its `assistant_apps` setting (Settings > Location > Assistant).

| Tool | Params | Answers |
|---|---|---|
| `wifi_info` | none | The name and password of the network shown to everyone (or each of them, under `networks`), and that it's also on the WiFi page with a QR code. An open network's password reads "none, it's an open network" |

Only networks whose audience is **Everyone** are ever part of the answer, in every mode, owner
too: admins-only networks (and their passwords) stay on the signed-in page. With no network for
everyone, the tool fails with a short sentence the assistant can say.
## Container (hub API 2)

The app runs in its own container: `network: none`, `lifecycle: on_demand`,
`memory_mb: 96`, no broker permissions beyond reading its own settings.
Since 2.1.0 it ships as its own image. CI's `image` job (from bdh-sdk's `app-ci.yml`) locks the
dependencies against the hub's app runtime, builds the app's image and smoke-tests it the way
the supervisor runs it.

## Development

CI (`.github/workflows/ci.yml`) uses the reusable `app-ci.yml` from bdh-sdk.
It builds the wheel, installs it next to the hub, then runs `hub_smoke`, the
app tests and the selenium tests.

To release, bump `version` in `pyproject.toml`. When that lands on `main`,
`release.yml` tags it and publishes the wheel, and the release notes include
the hashed line for the hub's `sites/<site>/apps.txt`.