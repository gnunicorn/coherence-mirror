# Licensed under the MIT license
# http://opensource.org/licenses/mit-license.php

# Copyright 2006, Frank Scholz <coherence@beebits.net>

from coherence.upnp.services.clients.connection_manager_client import ConnectionManagerClient
from coherence.upnp.services.clients.content_directory_client import ContentDirectoryClient
from coherence.upnp.services.clients.av_transport_client import AVTransportClient

from coherence.upnp.devices.basics import BasicClient

import coherence.extern.louie as louie

class MediaServerClient(BasicClient):
    logCategory = 'ms_client'

    def startup(self):
        self.device_type = self.device.get_friendly_device_type()
        self.version = int(self.device.get_device_type_version())
        self.icons = self.device.icons
        self.scheduled_recording = None
        self.content_directory = None
        self.connection_manager = None
        self.av_transport = None

        for service in self.device.get_services():
            connected = False
            if service.get_type() in ["urn:schemas-upnp-org:service:ContentDirectory:1",
                                      "urn:schemas-upnp-org:service:ContentDirectory:2"]:
                self.content_directory = ContentDirectoryClient(service)
                connected = True

            if service.get_type() in ["urn:schemas-upnp-org:service:ConnectionManager:1",
                                      "urn:schemas-upnp-org:service:ConnectionManager:2"]:
                self.connection_manager = ConnectionManagerClient(service)
                connected = True

            if service.get_type() in ["urn:schemas-upnp-org:service:AVTransport:1",
                                      "urn:schemas-upnp-org:service:AVTransport:2"]:
                self.av_transport = AVTransportClient(service)
                connected = True

            #if service.get_type()  in ["urn:schemas-upnp-org:service:ScheduledRecording:1",
            #                           "urn:schemas-upnp-org:service:ScheduledRecording:2"]:
            #    self.scheduled_recording = ScheduledRecordingClient( service)

            if connected and not service.last_time_updated:
                service.connect("notify", self.service_notify)

        self.info("MediaServer %s" % (self.device.get_friendly_name()))
        if self.content_directory:
            self.info("ContentDirectory available")
        else:
            self.warning("ContentDirectory not available, device not implemented properly according to the UPnP specification")
            return
        if self.connection_manager:
            self.info("ConnectionManager available")
        else:
            self.warning("ConnectionManager not available, device not implemented properly according to the UPnP specification")
            return
        if self.av_transport:
            self.info("AVTransport (optional) available")
        if self.scheduled_recording:
            self.info("ScheduledRecording (optional) available")

        self.service_notify()

    def remove(self):
        self.info("removal of MediaServerClient started")
        if self.content_directory:
            self.content_directory.remove()
        if self.connection_manager:
            self.connection_manager.remove()
        if self.av_transport:
            self.av_transport.remove()
        if self.scheduled_recording:
            self.scheduled_recording.remove()

    def service_notify(self):
        self.debug("notified")
        if self.content_directory:
            if not hasattr(self.content_directory.service, 'last_time_updated'):
                return
            if self.content_directory.service.last_time_updated == None:
                return
        if self.connection_manager:
            if not hasattr(self.connection_manager.service, 'last_time_updated'):
                return
            if self.connection_manager.service.last_time_updated == None:
                return
        if self.av_transport:
            if not hasattr(self.av_transport.service, 'last_time_updated'):
                return
            if self.av_transport.service.last_time_updated == None:
                return
        if self.scheduled_recording:
            if not hasattr(self.scheduled_recording.service, 'last_time_updated'):
                return
            if self.scheduled_recording.service.last_time_updated == None:
                return
        self.emit("detection_completed")

    def state_variable_change( self, variable, usn):
        self.info(variable.name, 'changed from', variable.old_value, 'to', variable.value)

    def print_results(self, results):
        self.info("results=", results)

    def process_meta( self, results):
        for k,v in results.iteritems():
            dfr = self.content_directory.browse(k, "BrowseMetadata")
            dfr.addCallback( self.print_results)
