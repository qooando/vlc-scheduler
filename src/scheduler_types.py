from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
import typing

import yaml

from src.timeutils import fmod_delta


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

    def change_start_time(self, new_start: datetime):
        assert new_start
        self.start_at = new_start
        self.end_at = self.start_at + self.play_duration

    def crop_start_time(self, delta: timedelta):
        assert delta.total_seconds() >= 0
        self.start_at = min(self.start_at + delta, self.end_at)
        self.play_duration = min(self.play_duration, self.end_at - self.start_at)
        self.cursor_start_at = min(self.cursor_start_at + delta, self.cursor_end_at)
        self.cursor_end_at = self.cursor_start_at + self.play_duration

    def crop_end_time(self, delta: timedelta):
        assert delta.total_seconds() >= 0
        self.end_at = max(self.start_at, self.end_at - delta)
        self.play_duration = min(self.play_duration, self.end_at - self.start_at)
        self.cursor_end_at = fmod_delta(self.cursor_start_at + self.play_duration, self.duration)

    def change_cursor_start_at(self, new_cursor: timedelta):
        self.cursor_start_at = new_cursor
        self.cursor_end_at = self.cursor_start_at + self.play_duration

    # def crop_cursor_start_at(self, delta: timedelta):
    #     assert delta.total_seconds() >= 0
    #     self.play_duration = max(timedelta(0), self.play_duration - delta)
    #     self.cursor_start_at = self.cursor_end_at - self.play_duration
    #     self.end_at = self.start_at + self.play_duration

    # def change_play_duration(self, new_play_duration: timedelta):
    #     self.play_duration = new_play_duration
    #     self.end_at = self.start_at + self.play_duration
    #     self.cursor_end_at = fmod_delta(self.cursor_start_at + self.play_duration, self.duration)
    #
    # def delta_play_duration(self, delta: timedelta):
    #     self.play_duration = max(timedelta(0), self.play_duration + delta)
    #     self.end_at = self.start_at + self.play_duration
    #     self.cursor_end_at = fmod_delta(self.cursor_start_at + self.play_duration, self.duration)

    def clone(self):
        return ScheduleClip(**asdict(self))


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
