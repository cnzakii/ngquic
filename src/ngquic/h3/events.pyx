# cython: embedsignature=True, freethreading_compatible=True, language_level=3

from ..events cimport Event


cdef class RequestReceived(Event):
    __match_args__ = ("stream_id", "headers", "end_stream")

    def __init__(self, stream_id, headers, end_stream):
        self.stream_id = stream_id
        self.headers = headers
        self.end_stream = end_stream


cdef class ResponseReceived(Event):
    __match_args__ = ("stream_id", "headers", "end_stream")

    def __init__(self, stream_id, headers, end_stream):
        self.stream_id = stream_id
        self.headers = headers
        self.end_stream = end_stream


cdef class InformationalResponseReceived(Event):
    __match_args__ = ("stream_id", "headers")

    def __init__(self, stream_id, headers):
        self.stream_id = stream_id
        self.headers = headers


cdef class TrailersReceived(Event):
    __match_args__ = ("stream_id", "headers")

    def __init__(self, stream_id, headers):
        self.stream_id = stream_id
        self.headers = headers


cdef class DataReceived(Event):
    __match_args__ = ("stream_id", "data", "end_stream")

    def __init__(self, stream_id, data, end_stream):
        self.stream_id = stream_id
        self.data = data
        self.end_stream = end_stream


cdef class DatagramReceived(Event):
    __match_args__ = ("stream_id", "data")

    def __init__(self, stream_id, data):
        self.stream_id = stream_id
        self.data = data


cdef class GoAwayReceived(Event):
    __match_args__ = ("id",)

    def __init__(self, id):
        self.id = id


cdef class SettingsReceived(Event):
    __match_args__ = ("settings",)

    def __init__(self, settings):
        self.settings = settings


cdef class OriginReceived(Event):
    __match_args__ = ("origins",)

    def __init__(self, origins):
        self.origins = origins
