# -*- coding: utf-8 -*-

# Licensed under the MIT license
# http://opensource.org/licenses/mit-license.php

# Copyright 2008, Frank Scholz <coherence@beebits.net>

""" transcoder classes to be used in combination with
    a Coherence MediaServer

    using GStreamer pipelines for the actually work
    and feeding the output into a http response
"""

import pygst
pygst.require('0.10')
import gst
import gobject
gobject.threads_init()

import urllib

from twisted.web import resource, server

from coherence import log

import struct

class FakeTransformer(gst.Element, log.Loggable):
    logCategory = 'faker_datasink'

    _sinkpadtemplate = gst.PadTemplate ("sinkpadtemplate",
                                        gst.PAD_SINK,
                                        gst.PAD_ALWAYS,
                                        gst.caps_new_any())

    _srcpadtemplate =  gst.PadTemplate ("srcpadtemplate",
                                        gst.PAD_SRC,
                                        gst.PAD_ALWAYS,
                                        gst.caps_new_any())

    def __init__(self,destination=None,request=None):
        gst.Element.__init__(self)
        self.sinkpad = gst.Pad(self._sinkpadtemplate, "sink")
        self.srcpad = gst.Pad(self._srcpadtemplate, "src")
        self.add_pad(self.sinkpad)
        self.add_pad(self.srcpad)

        self.sinkpad.set_chain_function(self.chainfunc)

        self.buffer = ''
        self.buffer_size = 0
        self.proxy = False
        self.got_new_segment = False
        self.closed = False

    def get_fake_header(self):
        return struct.pack(">L4s", 32, 'ftyp') + \
            "mp42\x00\x00\x00\x00mp42mp41isomiso2"

    def chainfunc(self, pad, buffer):
        if self.proxy:
            # we are in proxy mode already
            self.srcpad.push(buffer)
            return gst.FLOW_OK

        self.buffer = self.buffer + buffer.data
        if not self.buffer_size:
            try:
                self.buffer_size, a_type = struct.unpack(">L4s", self.buffer[:8])
            except:
                return gst.FLOW_OK

        if len(self.buffer) < self.buffer_size:
            # we need to buffer more
            return gst.FLOW_OK

        buffer = self.buffer[self.buffer_size:]
        fake_header = self.get_fake_header()
        n_buf = gst.Buffer(fake_header + buffer)
        self.proxy = True
        self.srcpad.push(n_buf)

        return gst.FLOW_OK

gobject.type_register(FakeTransformer)

class DataSink(gst.Element, log.Loggable):

    logCategory = 'transcoder_datasink'

    _sinkpadtemplate = gst.PadTemplate ("sinkpadtemplate",
                                        gst.PAD_SINK,
                                        gst.PAD_ALWAYS,
                                        gst.caps_new_any())

    def __init__(self,destination=None,request=None):
        gst.Element.__init__(self)
        self.sinkpad = gst.Pad(self._sinkpadtemplate, "sink")
        self.add_pad(self.sinkpad)

        self.sinkpad.set_chain_function(self.chainfunc)
        self.sinkpad.set_event_function(self.eventfunc)
        self.destination = destination
        self.request = request

        if self.destination != None:
            self.destination = open(self.destination, 'wb')
        self.buffer = ''
        self.data_size = 0
        self.got_new_segment = False
        self.closed = False

    def chainfunc(self, pad, buffer):
        if self.closed == True:
            return gst.FLOW_OK
        if self.destination != None:
            self.destination.write(buffer.data)
        elif self.request != None:
            self.buffer += buffer.data
            if len(self.buffer) > 200000:
                self.request.write(self.buffer)
                self.buffer = ''
        else:
            self.buffer += buffer.data

        self.data_size += buffer.size
        return gst.FLOW_OK

    def eventfunc(self, pad, event):
        if event.type == gst.EVENT_NEWSEGMENT:
            if self.got_new_segment == False:
                self.got_new_segment = True
            else:
                self.closed = True
        elif event.type == gst.EVENT_EOS:
            if self.destination != None:
                self.destination.close()
            elif self.request != None:
                if len(self.buffer) > 0:
                    self.request.write(self.buffer)
                self.request.finish()
        return True


gobject.type_register(DataSink)

class GStreamerPipeline(resource.Resource, log.Loggable):
    logCategory = 'gstreamer'
    addSlash = True

    def __init__(self,pipeline,mimetype):
        self.uri = pipeline
        self.contentType = mimetype
        self.requests = []
        # if stream has a streamheader (something that has to be prepended
        # before any data), then it will be a tuple of GstBuffers
        self.streamheader = None
        self.parse_pipeline()
        resource.Resource.__init__(self)

    def parse_pipeline(self):
        self.pipeline = gst.parse_launch(
                            self.uri)
        self.appsink = gst.element_factory_make("appsink", "sink")
        self.appsink.set_property('emit-signals', True)
        self.pipeline.add(self.appsink)
        enc = self.pipeline.get_by_name("enc")
        enc.link(self.appsink)
        self.appsink.connect("new-preroll", self.new_preroll)
        self.appsink.connect("new-buffer", self.new_buffer)
        self.appsink.connect("eos", self.eos)

    def start(self,request=None):
        self.info("GStreamerPipeline start %r %r" % (request,self.uri))
        self.requests.append(request)
        self.pipeline.set_state(gst.STATE_PLAYING)

        d = request.notifyFinish()
        d.addBoth(self.requestFinished, request)

    def new_preroll(self, appsink):
        self.debug("new preroll")
        buffer = appsink.emit('pull-preroll')
        if not self.streamheader:
            # check caps for streamheader buffer
            caps = buffer.get_caps()
            s = caps[0]
            if s.has_key("streamheader"):
                self.streamheader = s["streamheader"]
                self.debug("setting streamheader")
                for r in self.requests:
                    self.debug("writing streamheader")
                    for h in self.streamheader:
                        r.write(h.data)
        for r in self.requests:
            self.debug("writing preroll")
            r.write(buffer.data)

    def new_buffer(self, appsink):
        buffer = appsink.emit('pull-buffer')
        if not self.streamheader:
            # check caps for streamheader buffers
            caps = buffer.get_caps()
            s = caps[0]
            if s.has_key("streamheader"):
                self.streamheader = s["streamheader"]
                self.debug("setting streamheader")
                for r in self.requests:
                    self.debug("writing streamheader")
                    for h in self.streamheader:
                        r.write(h.data)
        for r in self.requests:
            r.write(buffer.data)

    def eos(self, appsink):
        self.info("eos")
        for r in self.requests:
            r.finish()
        self.cleanup()

    def getChild(self, name, request):
        self.info('getChild %s, %s' % (name, request))
        return self

    def render_GET(self,request):
        self.info('render GET %r' % (request))
        request.setResponseCode(200)
        if hasattr(self,'contentType'):
            request.setHeader('Content-Type', self.contentType)
        request.write('')

        headers = request.getAllHeaders()
        if('connection' in headers and
           headers['connection'] == 'close'):
            pass
        if self.requests:
            if self.streamheader:
                self.debug("writing streamheader")
                for h in self.streamheader:
                    request.write(h.data)
            self.requests.append(request)
        else:
            self.parse_pipeline()
            self.start(request)
        return server.NOT_DONE_YET

    def render_HEAD(self,request):
        self.info('render HEAD %r' % (request))
        request.setResponseCode(200)
        request.setHeader('Content-Type', self.contentType)
        request.write('')

    def requestFinished(self,result, request):
        self.info("requestFinished %r" % result)
        """ we need to find a way to destroy the pipeline here
        """
        #from twisted.internet import reactor
        #reactor.callLater(0, self.pipeline.set_state, gst.STATE_NULL)
        self.requests.remove(request)
        if not self.requests:
            self.cleanup()

    def on_message(self,bus,message):
        t = message.type
        print "on_message", t
        if t == gst.MESSAGE_ERROR:
            #err, debug = message.parse_error()
            #print "Error: %s" % err, debug
            self.cleanup()
        elif t == gst.MESSAGE_EOS:
            self.cleanup()

    def cleanup(self):
        self.info("pipeline cleanup")
        self.pipeline.set_state(gst.STATE_NULL)
        self.requests = []
        self.streamheader = None

class BaseTranscoder(resource.Resource, log.Loggable):
    logCategory = 'transcoder'
    addSlash = True

    def __init__(self,uri,destination=None):
        self.info('uri %s %r' % (uri, type(uri)))
        if uri[:7] not in ['file://','http://']:
            uri = 'file://' + urllib.quote(uri)   #FIXME
        self.source = uri
        self.destination = destination
        resource.Resource.__init__(self)

    def getChild(self, name, request):
        self.info('getChild %s, %s' % (name, request))
        return self

    def render_GET(self,request):
        self.info('render GET %r' % (request))
        request.setResponseCode(200)
        if hasattr(self,'contentType'):
            request.setHeader('Content-Type', self.contentType)
        request.write('')

        headers = request.getAllHeaders()
        if('connection' in headers and
           headers['connection'] == 'close'):
            pass

        self.start(request)
        return server.NOT_DONE_YET

    def render_HEAD(self,request):
        self.info('render HEAD %r' % (request))
        request.setResponseCode(200)
        request.setHeader('Content-Type', self.contentType)
        request.write('')

    def requestFinished(self,result):
        self.info("requestFinished %r" % result)
        """ we need to find a way to destroy the pipeline here
        """
        #from twisted.internet import reactor
        #reactor.callLater(0, self.pipeline.set_state, gst.STATE_NULL)
        gobject.idle_add(self.cleanup)

    def on_message(self,bus,message):
        t = message.type
        print "on_message", t
        if t == gst.MESSAGE_ERROR:
            #err, debug = message.parse_error()
            #print "Error: %s" % err, debug
            self.cleanup()
        elif t == gst.MESSAGE_EOS:
            self.cleanup()

    def cleanup(self):
        self.pipeline.set_state(gst.STATE_NULL)


class PCMTranscoder(BaseTranscoder):
    contentType = 'audio/L16;rate=44100;channels=2'

    def start(self,request=None):
        self.info("PCMTranscoder start %r %r" % (request,self.source))
        self.pipeline = gst.parse_launch(
            "%s ! decodebin ! audioconvert name=conv" % self.source)

        conv = self.pipeline.get_by_name('conv')
        caps = gst.Caps("audio/x-raw-int,rate=44100,endianness=4321,channels=2,width=16,depth=16,signed=true")
        filter = gst.element_factory_make("capsfilter", "filter")
        filter.set_property("caps", caps)
        self.pipeline.add(filter)
        conv.link(filter)

        sink = DataSink(destination=self.destination,request=request)
        self.pipeline.add(sink)
        filter.link(sink)
        self.pipeline.set_state(gst.STATE_PLAYING)

        d = request.notifyFinish()
        d.addBoth(self.requestFinished)


class WAVTranscoder(BaseTranscoder):

    contentType = 'audio/x-wav'

    def start(self,request=None):
        self.info("start %r", request)
        self.pipeline = gst.parse_launch(
            "%s ! decodebin ! audioconvert ! wavenc name=enc" % self.source)
        enc = self.pipeline.get_by_name('enc')
        sink = DataSink(destination=self.destination,request=request)
        self.pipeline.add(sink)
        enc.link(sink)
        #bus = self.pipeline.get_bus()
        #bus.connect('message', self.on_message)
        self.pipeline.set_state(gst.STATE_PLAYING)

        d = request.notifyFinish()
        d.addBoth(self.requestFinished)


class MP3Transcoder(BaseTranscoder):

    contentType = 'audio/mpeg'

    def start(self,request=None):
        self.info("start %r", request)
        self.pipeline = gst.parse_launch(
            "%s ! decodebin ! audioconvert ! lame name=enc" % self.source)
        enc = self.pipeline.get_by_name('enc')
        sink = DataSink(destination=self.destination,request=request)
        self.pipeline.add(sink)
        enc.link(sink)
        self.pipeline.set_state(gst.STATE_PLAYING)

        d = request.notifyFinish()
        d.addBoth(self.requestFinished)


class MP4Transcoder(BaseTranscoder):
    """ Only works if H264 inside Quicktime/MP4 container is input
        Source has to be a valid uri
    """
    contentType = 'video/mp4'

    def start(self,request=None):
        self.info("start %r", request)
        self.pipeline = gst.parse_launch(
            "%s ! qtdemux name=d ! queue ! h264parse ! mp4mux name=mux d. ! queue ! mux." % self.source)
        mux = self.pipeline.get_by_name('mux')
        sink = DataSink(destination=self.destination,request=request)
        self.pipeline.add(sink)
        mux.link(sink)
        self.pipeline.set_state(gst.STATE_PLAYING)

        d = request.notifyFinish()
        d.addBoth(self.requestFinished)


class MP2TSTranscoder(BaseTranscoder):

    contentType = 'video/mpeg'

    def start(self,request=None):
        self.info("start %r", request)
        ### FIXME
        self.pipeline = gst.parse_launch(
            "%s ! decodebin2 ! insert proper pipeline here ! mpegtsmux name=mux" % self.source)
        enc = self.pipeline.get_by_name('mux')
        sink = DataSink(destination=self.destination,request=request)
        self.pipeline.add(sink)
        enc.link(sink)
        self.pipeline.set_state(gst.STATE_PLAYING)

        d = request.notifyFinish()
        d.addBoth(self.requestFinished)


class JPEGThumbTranscoder(BaseTranscoder):
    """ should create a valid thumbnail according to the DLNA spec
        neither width nor height must exceed 160px
    """
    contentType = 'image/jpeg'

    def start(self,request=None):
        self.info("start %r", request)
        """ what we actually want here is a pipeline that calls
            us when it knows about the size of the original image,
            and allows us now to adjust the caps-filter with the
            calculated values for width and height

            new_width = 160
            new_height = 160
            if original_width > 160:
                new_heigth = int(float(original_height) * (160.0/float(original_width)))
                if new_height > 160:
                    new_width = int(float(new_width) * (160.0/float(new_height)))
            elif original_height > 160:
                new_width = int(float(original_width) * (160.0/float(original_height)))
        """
        self.pipeline = gst.parse_launch(
            "%s ! jpegdec ! videoscale ! video/x-raw-yuv,width=160,height=160 ! jpegenc name=enc" % self.source)
        enc = self.pipeline.get_by_name('enc')
        sink = DataSink(destination=self.destination,request=request)
        self.pipeline.add(sink)
        enc.link(sink)
        self.pipeline.set_state(gst.STATE_PLAYING)

        d = request.notifyFinish()
        d.addBoth(self.requestFinished)
