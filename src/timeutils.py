import math
import re
from datetime import datetime, timedelta
import pytimeparse

re_hms_format = re.compile(r'^\s*(\d+[Hh])?\s*(\d+[Mm])?\s*(\d+[Ss])?$')
re_hms_format2 = re.compile(f'^(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>[\d.]+)$')


def to_date(data, start_date=datetime.now(), default=None):
    assert start_date
    if not data:
        return default
    if isinstance(data, datetime):
        return data
    if isinstance(data, timedelta):
        return start_date + data
    if isinstance(data, int | float):
        return start_date + timedelta(seconds=data)
    if isinstance(data, str):
        m = re_hms_format.match(data)
        if m:
            return start_date + timedelta(seconds=pytimeparse.parse(data))
        m = re_hms_format2.match(data)
        if m:
            d = m.groupdict()
            return start_date + timedelta(hours=int(d["hours"]), minutes=int(d["minutes"]), seconds=float(d["seconds"]))
        # absolute
        return datetime.fromisoformat(data)
    raise NotImplementedError(data)


def to_delta(data, start_date=datetime.now(), default=timedelta(seconds=0)):
    assert start_date
    if not data:
        return default
    if isinstance(data, timedelta):
        return data
    if isinstance(data, datetime):
        return start_date - data
    if isinstance(data, int | float):
        return timedelta(seconds=data)
    if isinstance(data, str):
        m = re_hms_format.match(data)
        if m:
            return timedelta(seconds=pytimeparse.parse(data))
        m = re_hms_format2.match(data)
        if m:
            d = m.groupdict()
            return timedelta(hours=int(d["hours"]), minutes=int(d["minutes"]), seconds=float(d["seconds"]))
        # absolute
        return datetime.fromisoformat(data) - start_date
    raise NotImplementedError(data)


def video_duration(path):
    from moviepy.editor import VideoFileClip
    clip = VideoFileClip(path)
    return timedelta(seconds=clip.duration)

    # cap = cv2.VideoCapture(path)
    # fps = cap.get(cv2.CAP_PROP_FPS)  # OpenCV v2.x used "CV_CAP_PROP_FPS"
    # frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # duration = frame_count / fps
    # return timedelta(seconds=duration)


def fmod_delta(a: timedelta, b: timedelta):
    return timedelta(
        seconds=math.fmod(a.total_seconds(), (b + timedelta(microseconds=1)).total_seconds())
    )
