"""Limit the presentation duration of FFmpeg-produced MP4/MOV files.

Video packets include reordered reference frames after the requested endpoint.
Keep those packets for decoding, but shorten the movie and track edit lists so
players stop presenting frames at the selected end. No media data is changed.
"""
import math
import struct
from pathlib import Path


class ContainerTimingError(ValueError):
    pass


def limit_presentation(path, seconds):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ContainerTimingError('Invalid presentation duration')
    with Path(path).open('r+b') as stream:
        stream.seek(0, 2); file_size = stream.tell()
        def boxes(start, end):
            position = start
            while position < end:
                if end - position < 8: raise ContainerTimingError('Truncated MP4 box')
                stream.seek(position); size, kind = struct.unpack('>I4s', stream.read(8)); header = 8
                if size == 1:
                    raw = stream.read(8)
                    if len(raw) != 8: raise ContainerTimingError('Truncated MP4 box')
                    size = struct.unpack('>Q', raw)[0]; header = 16
                elif size == 0: size = end - position
                if size < header or size > end - position: raise ContainerTimingError('Invalid MP4 box size')
                yield kind, position + header, position + size
                position += size
        def number(offset, size, end):
            if offset + size > end: raise ContainerTimingError('Truncated MP4 timing box')
            stream.seek(offset); data = stream.read(size)
            if len(data) != size: raise ContainerTimingError('Truncated MP4 timing value')
            return int.from_bytes(data, 'big')
        roots = list(boxes(0, file_size))
        movies = [(start, end) for kind, start, end in roots if kind == b'moov']
        if len(movies) != 1: raise ContainerTimingError('Missing or ambiguous MP4 movie')
        children = list(boxes(*movies[0])); headers = [(a,b) for kind,a,b in children if kind == b'mvhd']
        if len(headers) != 1: raise ContainerTimingError('Missing MP4 movie header')
        start, end = headers[0]; version = number(start, 1, end)
        if version not in (0, 1): raise ContainerTimingError('Unsupported MP4 header version')
        scale = number(start + (20 if version else 12), 4, end)
        if not scale: raise ContainerTimingError('Invalid MP4 timescale')
        target = max(1, round(seconds * scale)); patches = []
        def clamp(offset, size, end, maximum):
            value = number(offset, size, end)
            if value > maximum: patches.append((offset, maximum.to_bytes(size, 'big')))
            return min(value, maximum)
        clamp(start + (24 if version else 16), 8 if version else 4, end, target)
        tracks = [(a,b) for kind,a,b in children if kind == b'trak']
        if not tracks: raise ContainerTimingError('MP4 has no tracks')
        for track_start, track_end in tracks:
            track = list(boxes(track_start, track_end))
            headers = [(a,b) for kind,a,b in track if kind == b'tkhd']
            edits = [(a,b) for kind,a,b in track if kind == b'edts']
            if len(headers) != 1 or len(edits) != 1: raise ContainerTimingError('Missing MP4 track edit list')
            a, b = headers[0]; version = number(a, 1, b)
            if version not in (0, 1): raise ContainerTimingError('Unsupported MP4 track header')
            clamp(a + (28 if version else 20), 8 if version else 4, b, target)
            lists = [(x,y) for kind,x,y in boxes(*edits[0]) if kind == b'elst']
            if len(lists) != 1: raise ContainerTimingError('Missing MP4 edit list')
            a, b = lists[0]; version = number(a, 1, b)
            if version not in (0, 1): raise ContainerTimingError('Unsupported MP4 edit list')
            count = number(a+4, 4, b); size = 8 if version else 4; entry_size = 20 if version else 12
            if not count or count > 1000 or a + 8 + count * entry_size > b:
                raise ContainerTimingError('Invalid MP4 edit list')
            remaining = target
            for i in range(count):
                remaining -= clamp(a + 8 + i * entry_size, size, b, remaining)
        for offset, data in patches:
            stream.seek(offset); stream.write(data)
