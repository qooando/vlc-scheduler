from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
import typing

import yaml


def _next_index():
    INDEX = 0
    while True:
        yield INDEX
        INDEX += 1


NEXT_INDEX = _next_index()


@dataclass
class ScheduleFile:
    start_at: str | int | datetime = field(default_factory=datetime.now)
    end_at: str | int | datetime = None
    sources: [typing.Any] = field(default_factory=list)


@dataclass
class ScheduleClip:
    id: int = field(default_factory=NEXT_INDEX.__next__)
    parent: typing.Any = None
    path: str = None
    priority: int = 100
    start_at: str | int | datetime = None
    end_at: str | int | datetime = None
    start_cursor: int = 0
    duration: timedelta = None
    play_duration: timedelta = None
    loop: bool = False

    vlc_playlist_id: int = None
    cursor_start_at: timedelta = field(default_factory=lambda: timedelta(seconds=0))
    cursor_end_at: timedelta = None

    background: bool = False

    def __lt__(self, other):
        if self.start_at == other.start_at:
            return self.priority < other.priority
        return self.start_at < other.start_at


def _yaml_schedule_clip_representation(dumper, data: ScheduleClip):
    d = {
        "path": data.path,
        "start_at": data.start_at,
        "end_at": data.end_at,
        "duration": data.duration,
        "play_duration": data.play_duration,
        "cursor_start_at": data.cursor_start_at,
        "cursor_end_at": data.cursor_end_at
    }
    if data.loop:
        d["loop"] = data.loop
    return dumper.represent_dict(d)


yaml.add_representer(ScheduleClip, _yaml_schedule_clip_representation)


@dataclass
class ScheduleSource:
    id: int = field(default_factory=NEXT_INDEX.__next__)
    parent: ScheduleFile = None

    clip_paths: [str] = field(default_factory=list)
    clips: [ScheduleClip] = field(default_factory=list)
    clips_are_cadenced: bool = False
    clips_are_sequential: bool = False

    priority: int = 100
    source: str = None
    loop: bool = False
    start_at: str | int | datetime = None
    end_at: str | int | datetime = None
    duration: timedelta = None

    clip_play_duration: int | timedelta | None = None  # how many seconds we play of the clips
    clip_repeat_interval: int | timedelta | None = None  # interval between sequential clip starts
    clip_loop: bool = False

    clip_stop_if_interrupted: bool = True
    clip_restart_after_interruption: bool = False
    clip_continue_after_interruption: bool = False
    clip_skip_time_after_interruption: bool = False

    # clip_continue_from_break: bool = False
    # clip_skip_and_continue: bool = False
