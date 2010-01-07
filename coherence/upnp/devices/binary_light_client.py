# Licensed under the MIT license
# http://opensource.org/licenses/mit-license.php

# Copyright 2008, Frank Scholz <coherence@beebits.net>

from coherence.upnp.devices.basics import BasicClient
from coherence.upnp.services.clients.switch_power_client import SwitchPowerClient

class BinaryLightClient(BasicClient):
    logCategory = 'binarylight_client'

    def startup(self):
        self.device_type = self.device.get_friendly_device_type()
        self.version = int(self.device.get_device_type_version())
        self.icons = device.icons
        self.switch_power = None

        for service in self.device.get_services():
            if service.get_type() in ["urn:schemas-upnp-org:service:SwitchPower:1"]:
                self.service = service
                break

        self.info("BinaryLight %s" % (self.device.get_friendly_name()))
        if self.service:
            self.switch_power = SwitchPowerClient(self.service)
            self._receiver = self.service.connect("notify", self.service_notify)
            self.info("SwitchPower service available")
        else:
            self.warning("SwitchPower service not available, device not implemented properly according to the UPnP specification")

    def remove(self):
        self.info("removal of BinaryLightClient")
        if self.switch_power:
            self.switch_power.remove()

    def service_notify(self):
        self.emit("detection_completed")
        self.service.disconnect(self._receiver)
        self._receiver = None

    def state_variable_change(self, variable):
        self.info(variable.name, 'changed from', variable.old_value, 'to', variable.value)
