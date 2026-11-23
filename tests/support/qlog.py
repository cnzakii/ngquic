"""Frames read back from qlog records."""

import json


def sent_frames(records, frame_type):
    return [
        frame
        for data in records
        for record in data.split(b"\x1e")
        if record.strip()
        for event in [json.loads(record)]
        if event.get("name") == "transport:packet_sent"
        for frame in event["data"]["frames"]
        if frame["frame_type"] == frame_type
    ]
