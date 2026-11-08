# (Unofficial) Jarolift Integration for Home Assistant

Control Jarolift covers from Home Assistant. Jarolift motors are operated by RF remotes using
[KeeLoq](https://en.wikipedia.org/wiki/KeeLoq) rolling codes. This integration acts as a virtual
Jarolift remote: it builds the encrypted commands and sends them through an RF capable
Home Assistant `remote`, for example a [Broadlink](https://www.home-assistant.io/integrations/broadlink/)
RM Pro.

The code originates from [this forum thread](https://community.home-assistant.io/t/control-of-jarolift-covers-using-broadlink-rm-pro/35600).
Wladi, the original author, can no longer maintain it, so this repository keeps it working with
newer Home Assistant versions.

## Features

* Set up in the UI, one device per cover
* Open, close and stop. With travel times also move to a position
* Learn and clear covers with a button, no service calls needed
* Intermediate position (long press of stop)
* Diagnostic sensors for the rolling code counter and the last command
* Services for automations and for sending raw commands
* One-time import of an existing YAML configuration (version 1.x)

## Requirements

* Home Assistant 2025.4 or newer. For older versions use version 1.4.x (see tags).
* A `remote` entity that can send 433 MHz RF commands, e.g. a Broadlink RM Pro or RM4 Pro.
* The Jarolift manufacturer key (MSB and LSB).

**This repository does not and will not contain the secret manufacturer key!**
If you don't have it, search the web or have a look at the forum thread linked above.

## Installation

### Marketplace (Home Assistant 2026.11 and newer)

1. Open **Settings > Marketplace**, choose **Add from link** and enter
   `https://github.com/4cc8783b/hass-jarolift` (type: integration). Adding a repository by
   link asks you to sign in with GitHub once.
2. Install **Jarolift** and restart Home Assistant if asked.

If you installed the integration with HACS before, nothing changes: Home Assistant migrates HACS
to the Marketplace and keeps updating the integration.

### HACS (before Home Assistant 2026.11)

1. Add this repository as a custom repository in HACS (type: integration).
2. Search for "Jarolift", install it and restart Home Assistant.

### Manual

Copy `custom_components/jarolift` from this repository into the `custom_components` folder of
your Home Assistant configuration and restart Home Assistant.

## Setup

### Add the integration

Go to **Settings > Devices & services > Add integration > Jarolift** and enter:

| Field | Description |
|---|---|
| Remote | The remote entity that sends the RF packets, e.g. `remote.broadlink_rm_proplus_remote` |
| Manufacturer key MSB / LSB | The two 32 bit halves of the manufacturer key, hex (e.g. `0x12345678`) |
| Delay between covers | Minimum pause after a command before the next cover gets one. Increase it if covers miss commands when several move at once |

You can change these later with **Reconfigure** on the integration entry.

### Add covers

On the Jarolift integration page choose **Add cover** and enter:

| Field | Description |
|---|---|
| Name | Name of the cover (and its device) |
| Serial | Serial of the virtual remote, hex up to `0x0FFFFFFF`, e.g. `0x106aa01`. Pick any value that none of your other remotes uses |
| Group | Channel bits, hex. Each bit is a channel: `0x0001` = channel 1, `0x0002` = channel 2, `0x0004` = channel 3 … |
| Repeat count | Extra transmissions of each command, for covers with bad reception (default 0) |
| Repeat delay | Pause between the repeated transmissions in seconds (default 0.2) |
| Reverse up/down | For covers that close on "up" |

Several covers can share a serial if they use different groups. The combination of serial
and group must be unique.

### Learn a cover

Put the motor into learning mode as described in the manual of your Jarolift motor (the same
procedure you would use with an original Jarolift remote). Then either tick **Learn now** in
the last step of **Add cover**, or press the cover's **Learn** button later.

To remove the virtual remote from a cover again, enable and press the
**Clear learned remote** button. The cover then has to be learned again before it can be
controlled by this integration.

## Entities

Every cover is a device with these entities:

| Entity | Purpose |
|---|---|
| Cover | Open, close, stop. With travel times also set position |
| Learn | Teach the cover (put the motor into learning mode first) |
| Clear learned remote | Remove this remote from the cover. Disabled by default because it is easy to press by accident |
| Intermediate position | Long press of stop: moves to the programmed intermediate position, if your motor has one |
| Travel time up / down | Seconds from one end position to the other. 0 disables position estimation |
| Rolling code counter | Next KeeLoq counter of the serial (diagnostic) |
| Last command | When and which command was sent last (diagnostic) |

All covers also belong to a Jarolift hub device, which is linked to the device of the
sending remote.

### State and position

The motors send no feedback, so the state is assumed: Home Assistant shows what was sent last.
Commands sent with the `jarolift.send_command` service update the state as well. Pressing an
original Jarolift remote is not detected.

When both travel times are set, the integration estimates the position from how long the
cover has been moving, and the cover can be moved to a position (e.g. 30 %). To measure the
travel times, time a full run from closed to open and from open to closed. The estimate is
only as good as these values. Open or close the cover completely now and then to resync, and
after setting the travel times for the first time.

## Services

| Service | Description |
|---|---|
| `jarolift.send_command` | Send a button press: `serial` (required), `group`, `button` (`0x2` down, `0x4` stop, `0x8` up), `rep_count`, `rep_delay`, `hold` (long press), `counter` |
| `jarolift.learn` | Learn a cover: `serial` (required), `group`, `counter` |
| `jarolift.clear` | Clear a learned cover: `serial` (required), `group`, `counter` |
| `jarolift.send_raw` | Send a raw packet (`packet`) through the remote |

Serial, group, button and counter are hex values given as strings, e.g. `'0x0001'`. Without
`counter` (or with `0`), the stored rolling code counter is used and increased. All services
take an optional `config_entry_id`, which is only needed if several Jarolift entries
(remotes) are set up. Details are in [services.yaml](custom_components/jarolift/services.yaml).

```yaml
action: jarolift.send_command
data:
  serial: '0x106aa01'
  group: '0x0001'
  button: '0x8'
```

For covers set up in the integration, prefer the cover actions (`cover.open_cover` etc.)
and the buttons.

## Migrating from version 1.x (YAML)

On the first start with version 2.x the existing `jarolift:` configuration and all
`cover: - platform: jarolift` covers are imported into the UI, once:

* The cover entities keep their entity IDs, so automations and dashboards keep working.
* The rolling code counters are taken over from the `counter_0x….txt` files in the
  configuration folder. The files are renamed to `….txt.migrated` afterwards.
* The covers don't have to be learned again.

A repair notice then asks you to remove the YAML configuration. Changes made to the YAML after
the import are not picked up. Edit the covers in the UI instead.

Before 2.x, a second cover with the same serial but a different group was dropped by Home
Assistant. Such covers are imported as well and show up as new entities.

> [!WARNING]
> Make a backup before updating, and don't go back to version 1.x after the migration.
> The counters are now stored in `.storage/jarolift.<entry id>`, so version 1.x would send old
> rolling codes, which the covers ignore.

## Troubleshooting

* **A cover does not react:** check that the remote works and is in range. Try a higher
  repeat count. If several covers move at once, increase the delay between covers.
* **A cover stopped reacting after restoring an old backup:** the rolling code counter went
  back, and the cover ignores codes it has seen before. Pressing the cover a few times may be
  enough to get past the old values, otherwise learn the cover again.
* **Debug logging:**

  ```yaml
  logger:
    logs:
      custom_components.jarolift: debug
  ```

## Development

The tests use [pytest-homeassistant-custom-component](https://github.com/MatthiasLohr/pytest-homeassistant-custom-component):

```sh
pip install -r requirements_test.txt
pytest tests
```

`tests/reference_packets.txt` holds packets generated by version 1.x with a dummy key. The
tests make sure the generated packets stay bit identical, so existing covers keep working.

## Support

I can't promise to give any support since the code does not originate from me and I'm only
using it in terms of "I once configured it and it works and now I'm only trying to keep it
working with newer versions of Home Assistant".
