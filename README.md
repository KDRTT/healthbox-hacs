# Healthbox 3 Integration for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]

[![Community Forum][forum-shield]][forum]

_Integration to integrate with [healthbox][healthbox]._

[![Renson][rensonimg]][resonurl]

## About this repository

This is an actively maintained continuation of [rmassch/healthbox-hacs][healthbox] (MIT licensed) - a separate repository sharing that project's history, not a GitHub-linked fork (it won't show up under rmassch's "Forks"). Install via HACS as a custom repository pointing at **this repo's URL**, not upstream's. See [What's New](#whats-new-in-this-repository) below for everything added on top of the original project.

## DISCLAIMER
This is still a work in progress.

## Changing the Host IP

If your Healthbox's IP address changes (e.g. a router restart with no static DHCP lease), you no longer need to delete and re-add the integration:

- **Automatic:** the integration recognizes your device by its serial number and detects when it requests a new DHCP lease (Healthbox 3 units broadcast a DHCP hostname of the form `HEALTHBOX3<serial>`). When that happens, Home Assistant updates the stored IP on its own — no action needed. This is passive discovery, so it isn't instant; it fires whenever the device's DHCP request is next seen on the network (e.g. at lease renewal or after a reboot).
- **Manual (immediate fallback):** use **Settings → Devices & Services → Renson Healthbox → three-dot menu → Reconfigure** to update the host (and API key, if used) in place right away; your existing entities and automations keep working either way.

## If your API key stops working

If the Healthbox rejects the stored API key (e.g. after a device reset), the integration triggers a **Re-authenticate** prompt on its entry in Settings → Devices & Services instead of just failing silently — enter a fresh key there.

## Diagnostics

Each config entry supports **Download Diagnostics** (Settings → Devices & Services → Renson Healthbox → three-dot menu) for bug reports — host, API key, and serial/warranty numbers are redacted.

## Installation

**Requires Home Assistant 2026.6.0 or newer** (raised from 2024.11.3 as of v0.7.0, to resolve security advisories affecting older HA Core releases - see [What's New](#whats-new-in-this-repository)).

### HACS

<!-- #### If published

1. Launch HACS
1. Navigate to the Integrations section
1. "+ Explore & Add Repositories" button in the bottom-right
1. Search for "Renson Healthbox"
1. Select "Install this repository"
1. Restart Home Assistant -->

#### HACS (Manual)

1. Launch HACS
1. Navigate to the Integrations section
1. Click the three dots at the top right
1. Custom Repositories
1. Enter the Repository URL: https://github.com/KDRTT/healthbox-hacs
1. Select Category -> Integration
1. Click Add
1. Close the modal
1. The integration should show up as a new repository, if not, search "Renson Healthbox" in "Explore & Download Repositories"
1. Click the integration & Download
1. Restart Home Assistant

### Home Assistant

1. Go to Settings -> Devices & Services
1. Click on the "+ Add Integration" button at the bottom-right
1. Search for the "Renson Healthbox" integration
1. Select the Renson Healthbox integration
1. Enter the Host IP & API Key (if applicable)
1. Submit


## Configuration

### Options

This integration can only be configured through the UI, and the options below can be configured when the integration is added.

| key       | default        | required | description                                     |
| --------- | -------------- | -------- | ----------------------------------------------- |
| host      | none      | yes      | The IP of the Healthbox 3 device               |
| api_key      | none           | no      | The API key if you want advanced API features and sensors enabled   |

### API Key
The API key can be requested through the Renson support. They will give you the key if you send an e-mail to  service@renson.be
and mention your device serial number.

(See: https://community.home-assistant.io/t/renson-healthbox-3-0/52983/57)

## Sensors
By default:
* Global Air Quality Index
* Serial Number
* Warranty Number
* Boost Level per room (rounded to a whole %)
* Boost Time Remaining (formatted as e.g. `1h 2m 3s`, not raw seconds) and Status
* Airflow Ventilation Rate (rounded to a whole %)
* Device Fan Power measurements
* Profile (read-only sensor; also settable, see **Ventilation Profile** below)

If the API key is provided this integration will enabled the advanced API features which will expose the following sensors per room (if available):
* Temperature (1 decimal)
* Humidity (1 decimal)
* Air Quality Index
* CO2 Concentration (rounded to a whole ppm)
* Volatile Organic Compounds

## Ventilation Profile

Each room also gets a **Profile** Select entity (Eco/Health/Intense) - lets you change the room's ventilation profile directly from the dashboard, same effect as the `change_room_profile` service below.

## Boost Control

Each room with boost support gets a **Fan** entity (`Boost`), plus a **Boost All Rooms** fan that boosts every room at once at one shared level/duration (mirrors the Renson app's own "boost all"). A plain tap of the toggle starts boost at that zone's configured defaults — no need to dial in the slider/preset every time:

- **Default Boost Level** (Number, 10-200%) and **Default Boost Duration** (Select) — one pair per room, plus one pair for "all rooms". Configure these once; the fan's toggle then uses them.
- **Stop Boost** (Button) — a one-tap way to stop a room's boost, same effect as turning its fan off.
- The fan's own percentage slider/preset dropdown still work as usual for a one-off adjustment to an already-running boost, without changing the configured default.

## Ventilation Boost Card

A custom Lovelace card (`ventilation-boost-card`) is bundled with the integration and registers itself automatically on startup - no manual "Resources" step needed. Add it to a dashboard as:

```yaml
type: custom:ventilation-boost-card
entity: fan.keuken_living_boost              # required
airflow_sensor: sensor.living_airflow_ventilation_rate
aq_sensor: sensor.living_co2_concentration    # or a VOC sensor; omit for humidity-only rooms
humidity_sensor: sensor.living_humidity
name: Living                                  # optional override
default_preset: "30 min"                      # optional
default_level: 75                             # optional, 10-100
default_level_entity: number.living_default_boost_level        # optional
default_duration_entity: select.living_default_boost_duration  # optional
```

Shows live CO2/VOC/humidity severity, a boost level stepper and duration chips, and a start/stop button. When `default_level_entity`/`default_duration_entity` are set, the stepper/chips mirror those config entities live while the boost is off, instead of a fixed `default_level`/`default_preset`.

## Services
### Start Room Boost
| parameter       | type        | required | description                                     |
| --------- | -------------- | -------- | ----------------------------------------------- |
| device_id      | str      | yes      | The Healthbox 3 Room Device               |
| boost_level    | int           | yes      | The level you want to boost to. Between 10% and 200%  |
| boost_timeout    | int           | yes      | The boost duration in minutes  |

### Stop Room Boost
| parameter       | type        | required | description                                     |
| --------- | -------------- | -------- | ----------------------------------------------- |
| device_id      | str      | yes      | The Healthbox 3 Room Device               |

## What's New in This Repository

Everything below was added on top of the original [rmassch/healthbox-hacs][healthbox] project. Full details for each release are on the [Releases page][releases].

- **Boost as Fan entities** - per-room `Boost` fan plus a `Boost All Rooms` fan, instead of only a service call.
- **Configurable boost defaults** - `Default Boost Level` (Number) and `Default Boost Duration` (Select) per room (and one pair for "all rooms"), so a plain toggle tap starts boost the way you actually want it, no slider/preset dialing needed.
- **Stop Boost button** - a one-tap, automation-friendly way to stop a room's boost.
- **Ventilation Profile select** - change a room's Eco/Health/Intense profile directly from the dashboard.
- **Automatic IP relocation** - the integration recognizes your Healthbox by serial number and updates its stored IP on its own when the device's DHCP lease changes, with a manual **Reconfigure** flow as an immediate fallback.
- **Re-authenticate flow** - if a stored API key stops working, Home Assistant prompts for a fresh one instead of failing silently.
- **Diagnostics download** - redacted config-entry diagnostics for bug reports (host/API key/serial numbers stripped).
- **Bundled brand icon** - proper Renson branding in the UI via Home Assistant's Brands Proxy API, no separate PR to the `home-assistant/brands` repo needed.
- **Bundled Lovelace card** - a custom `ventilation-boost-card` ships with the integration and registers itself as a dashboard resource automatically, no manual "Resources" setup.
- **Sensor polish** - rounded precision on numeric sensors, `Boost Remaining` split into a raw-seconds sensor and a human-formatted one (e.g. `1h 2m 3s`).
- **Security** - minimum supported Home Assistant version raised to `2026.6.0` (v0.7.0), fixing 4 known CVEs (1 critical) that affected the pinned test/dev dependency older releases relied on.

<!-- ## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md) -->

<!-- *** -->

[healthbox]: https://github.com/rmassch/healthbox-hacs
[buymecoffee]: https://www.buymeacoffee.com/ludeeus
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/KDRTT/healthbox-hacs.svg?style=for-the-badge
[commits]: https://github.com/KDRTT/healthbox-hacs/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[rensonimg]: https://www.renson.eu/Renson/media/Renson-images/renson-logo.png?ext=.png
[resonurl]: https://www.renson.eu/gd-gb/producten-zoeken/ventilatie/mechanische-ventilatie/units/healthbox-3-0
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/KDRTT/healthbox-hacs.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-@KDRTT-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/KDRTT/healthbox-hacs.svg?style=for-the-badge
[releases]: https://github.com/KDRTT/healthbox-hacs/releases
