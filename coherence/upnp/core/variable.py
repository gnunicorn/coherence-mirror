# Licensed under the MIT license
# http://opensource.org/licenses/mit-license.php

# Copyright (C) 2006 Fluendo, S.A. (www.fluendo.com).
# Copyright 2006, Frank Scholz <coherence@beebits.net>

import time
from sets import Set

from coherence.upnp.core import utils
try:
    #FIXME:
    # there is some circular import, service imports variable, variable imports service
    # how is this done properly?
    #
    from coherence.upnp.core import service
except ImportError:
    import service

from coherence import log

import coherence.extern.louie as louie

# parsing helpers for the data type as specified on
# - UPNP Device Architecture v1.0 page 33/34:
#   http://upnp.org/specs/arch/UPnP-arch-DeviceArchitecture-v1.0.pdf
# - UPNP Device Architecutre v1.1 page 53/54:
#   http://upnp.org/specs/arch/UPnP-arch-DeviceArchitecture-v1.1.pdf


# maps the different allowed dataType-Types to corresponding python
# parsing functions
__parser_for_type__ = {
    'ui1': int,
    'ui2': int,
    'ui4': int,
    'i1': int,
    'i2': int,
    'i4': int,
    'r4': float,
    'r8': float,
    'number': float,
    'fixed.14.4': float,
    'float': float,
    # specific
    'date': _parse_date,
    'dateTime': _parse_date_time,
    'dateTime.tz': _parse_date_time,
    'time': _parse_time,
    'boolean': utils.generalise_boolean,
    'bin.base64': _parse_base64,
    'bin.hex': _parse_hex,
    # should we understand them as anything else than unicodes?
    'uri': unicode,
    'char': unicode,
    'uuid': unicode,
}

def get_parser_for_type(data_type_node):
    try:
        return __parser_for_type__[data_type_node.findtext()]
    except KeyError:
        try:
            # is it a vendor specific one we know about?
            return __parser_for_type[data_type_node.attrib['type']]
        except KeyError:
            # or we just interpret it as a unicode string
            return unicode


class StateVariable(log.Loggable):
    logCategory = 'variable'

    def __init__(self, upnp_service, name, implementation, instance, send_events,
                 data_type, allowed_values):
        self.service = upnp_service

        self.name = name
        self.implementation = implementation
        self.instance = instance
        self.send_events = utils.means_true(send_events)
        self.never_evented = False
        self.data_type = data_type
        self.allowed_values = allowed_values
        if self.allowed_values == None:
            self.allowed_values = []
        self.has_vendor_values = False
        self.allowed_value_range = None
        self.dependant_variable = None

        self.default_value = ''
        self.old_value = ''
        self.value = ''
        self.last_time_touched = None

        self._callbacks = []
        if isinstance( self.service, service.ServiceServer):
            self.moderated = self.service.is_variable_moderated(name)
            self.updated = False

    def as_tuples(self):
        r = []
        r.append(('Name',self.name))
        if self.send_events:
            r.append(('Evented','yes'))
        else:
            r.append(('Evented','no'))
        r.append(('Data Type',self.data_type))
        r.append(('Default Value',self.default_value))
        r.append(('Current Value',unicode(self.value)))
        if(self.allowed_values != None and len(self.allowed_values) > 0):
            r.append(('Allowed Values',','.join(self.allowed_values)))
        return r

    def set_default_value(self, value):
        self.update(value)
        self.default_value = self.value

    def set_allowed_values(self, values):
        if not isinstance(values,(list,tuple)):
            values = [values]
        self.allowed_values = values

    def set_allowed_value_range(self, **kwargs):
        self.allowed_value_range = kwargs

    def get_allowed_values(self):
        return self.allowed_values

    def set_never_evented(self, value):
        self.never_evented = utils.means_true(value)

    def update(self, value):
        self.info("variable check for update", self.name, value, self.service)
        if not isinstance( self.service, service.Service):
            if self.name == 'ContainerUpdateIDs':
                old_value = self.value
                if self.updated == True:
                    if isinstance( value, tuple):
                        v = old_value.split(',')
                        i = 0
                        while i < len(v):
                            if v[i] == str(value[0]):
                                del v[i:i+2]
                                old_value = ','.join(v)
                                break;
                            i += 2
                        if len(old_value):
                            new_value = old_value + ',' + str(value[0]) + ',' + str(value[1])
                        else:
                            new_value = str(value[0]) + ',' + str(value[1])
                    else:
                        if len(old_value):
                            new_value = str(old_value) + ',' + str(value)
                        else:
                            new_value = str(value)
                else:
                    if isinstance( value, tuple):
                        new_value = str(value[0]) + ',' + str(value[1])
                    else:
                        new_value = value
            else:
                if self.data_type == 'string':
                    if isinstance(value,basestring):
                        value = value.split(',')
                    if(isinstance(value,tuple) or
                       isinstance(value,Set)):
                        value = list(value)
                    if not isinstance(value,list):
                        value = [value]
                    new_value = []
                    for v in value:
                        if type(v) == unicode:
                            v = v.encode('utf-8')
                        else:
                            v = str(v)
                        if len(self.allowed_values):
                            if self.has_vendor_values == True:
                                new_value.append(v)
                            elif v.upper() in [x.upper() for x in self.allowed_values]:
                                new_value.append(v)
                            else:
                                self.warning("Variable %s update, %r value %s doesn't fit in %r" % (self.name, self.has_vendor_values, v, self.allowed_values))
                                new_value = 'Coherence_Value_Error'
                        else:
                            new_value.append(v)
                    new_value = ','.join(new_value)
                elif self.data_type == 'boolean':
                    new_value = utils.generalise_boolean(value)
                elif self.data_type == 'bin.base64':
                    new_value = value
                else:
                    new_value = int(value)
        else:
            if self.data_type == 'string':
                if type(value) == unicode:
                    value = value.encode('utf-8')
                else:
                    value = str(value)
                if len(self.allowed_values):
                    if self.has_vendor_values == True:
                        new_value = value
                    elif value.upper() in [v.upper() for v in self.allowed_values]:
                        new_value = value
                    else:
                        self.warning("Variable %s NOT updated, value %s doesn't fit" % (self.name, value))
                        new_value = 'Coherence_Value_Error'
                else:
                    new_value = value
            elif self.data_type == 'boolean':
                    new_value = utils.generalise_boolean(value)
            elif self.data_type == 'bin.base64':
                new_value = value
            else:
                try:
                    new_value = int(value)
                except ValueError:
                    new_value = 'Coherence_Value_Error'


        if new_value == 'Coherence_Value_Error':
            return
        if new_value == self.value:
            self.info("variable NOT updated, no value change", self.name, self.value)
            return
        self.old_value = self.value
        self.value = new_value
        self.last_time_touched = time.time()

        if isinstance( self.service, service.Service):
            self.notify()
        else:
            self.updated = True
            if self.service.last_change != None:
                self.service.last_change.updated = True
        self.info("variable updated", self.name, self.value)

    def subscribe(self, callback):
        self._callbacks.append(callback)
        callback( self)

    def notify(self):
        if self.name.startswith('A_ARG_TYPE_'):
            return
        self.info("Variable %s sends notify about new value >%r<" %(self.name, self.value))
        #if self.old_value == '':
        #    return
        louie.send(signal='Coherence.UPnP.StateVariable.%s.changed' % self.name, sender=self.service, variable=self)
        louie.send(signal='Coherence.UPnP.StateVariable.changed',sender=self.service, variable=self)
        for callback in self._callbacks:
            callback( self)

    def __repr__(self):
        return "Variable: %s, %s, %d, %s, %s, %s, %s, %s, %s, %s" % \
                        (self.name,
                         str(self.service),
                         self.instance,
                         self.implementation,
                         self.data_type,
                         str(self.allowed_values),
                         str(self.default_value),
                         str(self.old_value),
                         str(self.value),
                         str(self.send_events))
