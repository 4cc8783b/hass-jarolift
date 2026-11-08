# (Unofficial) Jarolift Integration for Home Assistant

Jarolift covers can be controlled by remote control. This repository contains a
home assistant custom component which allows to control Jarolift covers (by adding a 'jarolift' cover platform).
The remote control codes are send via a home assistant 'remote' which does the
heavy load of transmitting the bytes via RF to the covers.

The code originates from [here](https://community.home-assistant.io/t/control-of-jarolift-covers-using-broadlink-rm-pro/35600)
but Wladi seems not in the position to support further more. Since there were some
changes needed to the code (and will always be as home assistant evolves) this repository
was set up to track changes.

## Supported Home Assistant versions

### Minimum HA version: 2025.4
Version 2.x is set up in the UI and uses config subentries. For older Home Assistant
versions use version 1.4.x (see tags).

## KeeLoq Encryption

Jarolift covers use [KeeLoq](https://en.wikipedia.org/wiki/KeeLoq) encryption hence there is always a
proprietary bit of knowledge needed to operate them (the manufacturer key which is used in the process
of encrypting/decrypting data).

**This repository does not and will not contain the secret manufacturer key!**

If you do not have the manufacturer key you should get it by using Google or follow the linked original source from above ;-)

## Installation

Make sure you have the manufacturer secret (MSB and LSB from it are required).
Also you need to have a remote configured that is able to send data (via RF) to your Jarolift covers.
This could for example be an Broadlink RM PRO+ with the appropriate [Home Assistant Integration](https://www.home-assistant.io/integrations/broadlink/)
configured.

### Get the integration

## Manual installation

Copy all files from custom_components/jarolift in this repo to your config custom_components/jarolift.

## Via HACS

1. Add this repository as HACS repository (type: integration)
2. Search for 'jarolift' and install the integration

### Setup

Go to **Settings > Devices & services > Add integration > Jarolift** and enter:

* the remote that sends the RF packets (e.g. `remote.broadlink_rm_proplus_remote`)
* MSB and LSB of the manufacturer key (hex, e.g. `0x12345678`)
* an optional delay between commands to different covers

Then add your covers with **Add cover** on the Jarolift integration page. For each cover
enter name, serial and group (hex), and optionally repeat count, repeat delay and
"reverse" (for covers that close on "up"). You can learn the cover right away.

Every cover is a device with these entities:

| Entity | Purpose |
|---|---|
| Cover | Open, close, stop. With travel times also set position |
| Learn | Teach the cover (put the motor into learning mode first) |
| Clear learned remote | Remove this remote from the cover (disabled by default) |
| Intermediate position | Long press of stop: moves to the programmed intermediate position, if your motor has one |
| Travel time up / down | Seconds from one end to the other. When both are set, the position is estimated from the travel time |
| Rolling code counter | Next KeeLoq counter of the serial (diagnostic) |
| Last command | When and which command was sent last (diagnostic) |

The state is assumed: the covers send no feedback, so Home Assistant shows what was sent last.

### Migrating from version 1.x (YAML)

On the first start with version 2.x an existing `jarolift:` configuration and all
`cover: - platform: jarolift` covers are imported into the UI once. The cover entities keep
their entity IDs, and the rolling code counters are taken over from the `counter_0x….txt`
files (which are renamed to `….txt.migrated`). Your covers don't have to be learned again.
Afterwards remove the YAML configuration as the repair notice says.

Rolling code counters are now stored in `.storage/jarolift.<entry id>`. Don't go back to
version 1.x after the migration: it would send old rolling codes which the covers ignore.

## Provided services
The integration provides following services:
* jarolift.clear
* jarolift.learn
* jarolift.send_command
* jarolift.send_raw

Those are documented in the [services.yaml](custom_components/jarolift/services.yaml).
`serial` is required. Commands sent with `jarolift.send_command` also update the state of a
configured cover with the same serial and group.

## Learn covers

Use the provided services from your Home Assistant Developers Tools view to connect to your covers. Use the process that is normally executed when
learning an original Jarolift remote.

## Support
I can't promise to give any support since the code does not originate from me and I'm only using it in terms of "I once configured it and it works and now
I'm only trying to keep it working with newer versions of Home Assistant".
