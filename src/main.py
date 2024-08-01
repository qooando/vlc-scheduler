import asyncio
import sys
import typing
from datetime import datetime, timedelta
import glob
import os
from asyncio import PriorityQueue
from dataclasses import dataclass, Field, field, asdict

import yaml
import logging

from vlc import VLCLauncher, VLCHTTPClient

VLC_PLAYLIST_INDEX_OFFSET = 3
VLC_PLAYLIST_FILE_REVERSE_INDEXES = {}

CONFIGFILE = os.getenv('CONFIG') or "config.yaml"

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)

logging.getLogger("urllib3").setLevel(logging.WARNING)


def _next_index():
    INDEX = 0
    while True:
        yield INDEX
        INDEX += 1


NEXT_INDEX = _next_index()


@dataclass
class ScheduleFile:
    schedule_at: str | int | datetime = field(default_factory=datetime.now)
    groups: [typing.Any] = field(default_factory=list)


@dataclass
class Clip:
    id: int = field(default_factory=NEXT_INDEX.__next__)
    priority: int = 100
    schedule_at: datetime = None
    path: str = None
    parent: typing.Any = None

    reschedule_parent: bool = False
    cursor: int = 0
    cursor_stop_at: float = None
    vlc_playlist_id: int = None

    def __lt__(self, other):
        if self.schedule_at != other.schedule_at:
            return self.priority < other.priority
        else:
            return self.schedule_at < other.schedule_at


@dataclass
class Group:
    # evaluated
    id: int = field(default_factory=NEXT_INDEX.__next__)
    clip_paths: [str] = field(default_factory=list)
    clips: [Clip] = field(default_factory=list)
    clips_are_timed: bool = False
    clips_are_sequential: bool = False
    parent: ScheduleFile = None

    # from config
    priority: int = 100
    source: str = None
    loop: bool = False

    schedule_at: str | int | datetime = 0

    # # reproduction interval measured from START to START
    # # time between the END of a clip and the next one
    # interleave: int | None = None
    # repeat: int = 1
    # repeat_interval: int | None = None
    # sequential: bool = True
    # random: bool = False
    # on_air_period: int | None = None
    clip_period: int | timedelta | None = None  # how many seconds we play of the clips
    clip_interval: int | timedelta | None = None  # interval between sequential clip starts

    #
    # discard_if_preempted: bool = False
    # pause_if_preempted: bool = True
    # restart_if_preempted: bool = False

    def __lt__(self, other):
        if self.schedule_at != other.schedule_at:
            return self.priority < other.priority
        else:
            return self.schedule_at < other.schedule_at


class VideoScheduler:

    def __init__(self):
        self.config = yaml.safe_load(open(CONFIGFILE))
        self.clips = []
        self.tasks = []
        self.active = True
        self.group_start_timestamp_schedule = PriorityQueue()
        self.clip_priority_schedule = PriorityQueue()
        self.clip_start_timestamp_schedule = PriorityQueue()
        self.clip_on_air: Clip | None = None
        self.clip_on_wait: [Clip] = []
        self.vlc_clip_playlist_id: {} = {}

    async def load_scheduling(self):
        path = self.config["scheduling"]["path"]
        logger.info(f"Load scheduling from {path}")
        schedule_files = [x for x in glob.glob(path) if os.path.isfile(x)]

        for schedule_path in schedule_files:
            logger.debug(f"Load schedule {schedule_path}")
            schedule_file = ScheduleFile(**yaml.safe_load(open(schedule_path)))
            # fix times
            if isinstance(schedule_file.schedule_at, str):
                schedule_file.schedule_at = datetime.fromisoformat(schedule_file.schedule_at)
            if isinstance(schedule_file.schedule_at, int):
                schedule_file.schedule_at = datetime.now() + timedelta(seconds=schedule_file.schedule_at)

            await asyncio.gather(*[self._load_group(Group(parent=schedule_file, **x)) for x in schedule_file.groups])

    async def _load_group(self, group: Group):
        logger.debug(f"Add group {group}")

        group.clip_paths = sorted(glob.glob(group.source))
        await self._postprocess_group_after_load(group)
        await self._schedule_group(group)

    async def _schedule_group(self, group: Group):
        now = datetime.now()
        if group.schedule_at and now < group.schedule_at:
            await self.group_start_timestamp_schedule.put(
                tuple([group.schedule_at, group.priority, group.id, group])
            )
        else:
            if group.clips_are_timed:
                subtasks = [self.clip_start_timestamp_schedule.put(
                    [c.schedule_at, c.priority, c.id, c]
                ) for c in group.clips]
                await asyncio.gather(*subtasks)
            elif group.clips_are_sequential:
                subtasks = [self.clip_priority_schedule.put(
                    [c.priority, c.id, c]
                ) for c in group.clips]
                await asyncio.gather(*subtasks)
            else:
                raise Exception(f"Unknown group clips type")

    async def _postprocess_group_after_load(self, g):
        # fix times
        if isinstance(g.clip_interval, int):
            g.clip_interval = timedelta(seconds=g.clip_interval)
        if isinstance(g.clip_period, int):
            g.clip_period = timedelta(seconds=g.clip_period)
        if isinstance(g.schedule_at, str):
            g.schedule_at = datetime.fromisoformat(g.schedule_at)
        if isinstance(g.schedule_at, int):
            g.schedule_at = g.parent.schedule_at + timedelta(g.schedule_at)

        g.clips_are_sequential = g.clip_interval is None
        g.clips_are_timed = not g.clips_are_sequential

        # fix clips
        clip_n = len(g.clip_paths)
        if not g.clips and len(g.clip_paths) > 0:
            g.clips = []

            # start clip schedule time
            schedule_start_at = None
            if g.clips_are_timed:
                schedule_start_at = g.schedule_at or datetime.now()
            for i, p in enumerate(g.clip_paths):
                # schedule time
                schedule_clip_at = None
                if g.clips_are_timed:
                    schedule_clip_at = schedule_start_at + timedelta(seconds=i * g.clip_interval.total_seconds())
                # vlc playlist id
                vlc_playlist_id = None
                if p in VLC_PLAYLIST_FILE_REVERSE_INDEXES:
                    vlc_playlist_id = VLC_PLAYLIST_FILE_REVERSE_INDEXES[p]
                else:
                    self.vlc_client.enqueue(p)
                    VLC_PLAYLIST_FILE_REVERSE_INDEXES[p] = \
                        vlc_playlist_id = len(VLC_PLAYLIST_FILE_REVERSE_INDEXES) + VLC_PLAYLIST_INDEX_OFFSET

                clip = Clip(
                    path=p,
                    parent=g,
                    priority=g.priority,
                    schedule_at=schedule_clip_at,
                    vlc_playlist_id=vlc_playlist_id,
                    cursor=0,
                    cursor_stop_at=g.clip_period.total_seconds() if g.clip_period else None
                )
                # loop
                if g.clips_are_sequential and g.loop and i == clip_n - 1:
                    clip.reschedule_parent = True

                g.clips.append(clip)

    async def scheduler_task(self):
        try:
            while self.active:
                self.active = await self._schedule_tick()
                await asyncio.sleep(0.5)
        finally:
            self.vlc_client.stop()

    async def _schedule_tick(self):
        now = datetime.now()
        _next = self.group_start_timestamp_schedule._queue[0] \
            if not self.group_start_timestamp_schedule.empty() else None
        while _next is not None and now >= _next[0]:
            await self.group_start_timestamp_schedule.get()
            await self._schedule_group(_next[3])
            _next = self.group_start_timestamp_schedule._queue[0] \
                if not self.group_start_timestamp_schedule.empty() else None

        schedule_next = self.clip_on_air is None

        if self.clip_on_air:
            schedule_next = not (await self._check_clip_on_air())

        next_clip = None

        # preemption by start timestamp and priority
        if next_clip is None and not self.clip_start_timestamp_schedule.empty():
            _next = self.clip_start_timestamp_schedule._queue[0] \
                if not self.clip_start_timestamp_schedule.empty() else None
            while _next is not None and now >= _next[0]:
                # set as next clip if priority is higher or equal
                if self.clip_on_air is None or _next[3].priority <= self.clip_on_air.priority:
                    next_clip = _next[3]  # preemption
                    schedule_next = True
                # remove from queue
                await self.clip_start_timestamp_schedule.get()
                _next = self.clip_start_timestamp_schedule._queue[0] \
                    if not self.clip_start_timestamp_schedule.empty() else None

        if not schedule_next:
            return True

        if next_clip is None and not self.clip_priority_schedule.empty():
            _next = await self.clip_priority_schedule.get()
            next_clip = _next[2]

        if next_clip is None:
            return True

        await self._play_clip(next_clip)

        return True

    async def _play_clip(self, clip: Clip):
        logger.info(f"Play clip {clip.path}")
        self.vlc_client.play(clip.vlc_playlist_id, clip.cursor)
        self.vlc_client.seek(clip.cursor)
        self.clip_on_air = clip

    async def _check_clip_on_air(self):
        c = self.clip_on_air
        vlc_status = self.vlc_client.status()
        c.cursor = vlc_status["time"]

        stop = False

        if not stop and vlc_status["state"] == "stopped":
            c.cursor = 0
            if c.parent.clip_period:
                c.cursor_stop_at = c.parent.clip_period.total_seconds()
            stop = True

        if not stop and c.cursor_stop_at and c.cursor >= c.cursor_stop_at:
            c.cursor_stop_at += c.parent.clip_period.total_seconds()
            self.vlc_client.pause()
            stop = True

        if stop:
            if c.reschedule_parent:
                await self._schedule_group(c.parent)

        return not stop

    async def start_scheduling(self):
        if self.config["vlc"]["start"]:
            vlc_path = self.config["vlc"]["path"]["linux"]
            if sys.platform.startswith('win'):
                vlc_path = self.config["vlc"]["path"]["win"]
            if sys.platform == 'darwin':
                vlc_path = self.config["vlc"]["path"]["darwin"]
            self.vlc_launcher = VLCLauncher({
                "host": self.config["vlc"]["host"],
                "port": self.config["vlc"]["port"],
                "extraintf": self.config["vlc"]["extraintf"],
                "password": self.config["vlc"]["password"],
                "path": vlc_path,
                "options": self.config["vlc"]["options"]
            })
            await self.vlc_launcher.launch()
            # self.tasks.append(self.vlc_launcher.watch_exit())

        self.vlc_client = VLCHTTPClient({
            "host": self.config["vlc"]["host"],
            "port": self.config["vlc"]["port"],
            "password": self.config["vlc"]["password"]
        })

        self.vlc_client.loop(False)
        self.vlc_client.repeat(False)

        await self.load_scheduling()
        self.tasks.append(self.scheduler_task())

        # self.tasks.append(self.schedule_clip())

        logger.info("Start scheduling")
        try:
            await asyncio.gather(*self.tasks)
        finally:
            logger.info('Stop scheduling')


async def main():
    logger.info("Start")
    vs = VideoScheduler()
    await vs.start_scheduling()


if __name__ == "__main__":
    asyncio.run(main())
