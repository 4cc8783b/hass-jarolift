# (Unofficial) Jarolift Integration for Home Assistant

Jarolift covers can be controlled by remote control. This repository contains a
home assistant custom component which allows to control Jarolift covers (by adding a 'jarolift' cover platform).
The remote control codes are send via a home assistant 'remote' which does the
heavy load of transmitting the bytes via RF to the covers.

The code originates from [here](https://community.home-assistant.io/t/control-of-jarolift-covers-using-broadlink-rm-pro/35600)
but Wladi seems not in the position to support further more. Since there were some
changes needed to the code (and will always be as home assistant evolves) this repository
was set up to track changes.

**Attention: The current implementation will stop working from Home Assistant 2022.2 onwards!**

## KeeLoq Encryption

Jarolift covers use [KeeLoq](https://en.wikipedia.org/wiki/KeeLoq) encryption hence there is always a
proprietary bit of knowledge needed to operate them (the manufacturer key which is used in the process
of encrypting/decrypting data).

**This repository does not and will not contain the secret manufacturer key**

If you do not have the manufacturer key you should get it by using google ;-)

## Installation

Make sure you have the manufacturer secret (MSB and LSB from it are required).
Also you need to have a remote configured that is able to send data (via RF) to your Jarolift covers.
This could for example be an Broadlink RM PRO+ with the appropriate [Home Assistant Integration](https://www.home-assistant.io/integrations/broadlink/)
configured.

### Get the integration

Copy all files from custom_components/jarolift in this repo to your config custom_components/jarolift.

### Setup

Enter following lines to `configuration.yaml`

```yaml
jarolift:
  remote_entity_id: remote.broadlink_rm_proplus_remote # this id is from the device of the remote integration representing the remote to send command with
  MSB: '0x12345678' # Most significant bits of the manufacturer key (**0x12345678 is not the correct value!**)
  LSB: '0x87654321' # Least significant bits of the manufactorer key (**0x87654321 is not the correct value!**)
```

Make sure Home Assistant can write a file in the config directory. The integration will write one to keep
track of the current count of command sent. This count is needed for the KeeLoq encryption.

Save the configuration file and restart Home Assistant.

## Provided services
The integration provides following services:
* jarolift.clear
* jarolift.learn
* jarolift.send_command
* jarolift.send_raw

Those are documented in the [services.yaml](https://github.com/4cc8783b/hass-jarolift/blob/main/custom_components/jarolift/services.yaml).

## Learn covers

Use the provided services from your Home Assistant Developers Tools view to connect to your covers. Use the process that is normally executed when
learning an original Jarolift remote.

## Support
I can't promise to give any support since the code does not originate from me and I'm only using it in terms of "I once configured it and it works and now
I'm only trying to keep it working with newer versions of Home Assistant".
