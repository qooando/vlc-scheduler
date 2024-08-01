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

from src.vlc import VLCLauncher, VLCHTTPClient

VLC_PLAYLIST_START_INDEX = 3
CONFIGFILE = os.getenv('CONFIG') or "config.yaml"

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)

logging.getLogger("urllib3").setLevel(logging.WARNING)


def next_index():
    INDEX = 0
    while True:
        yield INDEX
        INDEX += 1


NEXT_INDEX = next_index()


@dataclass
class Clip:
    id: int = field(default_factory=NEXT_INDEX.__next__)
    priority: int = 100
    start_timestamp: float = None
    path: str = None
    parent: typing.Any = None

    reschedule_parent: bool = False
    cursor: int = 0
    cursor_stop_at: int = None
    vlc_playlist_id: int = None

    def __lt__(self, other):
        if self.start_timestamp != other.start_timestamp:
            return self.priority < other.priority
        else:
            return self.start_timestamp < other.start_timestamp


@dataclass
class Group:
    # evaluated
    id: int = field(default_factory=NEXT_INDEX.__next__)
    start_timestamp: float = None
    end_timestamp: float = None
    clip_paths: [str] = field(default_factory=list)
    clips: [Clip] = field(default_factory=list)
    clips_are_timed: bool = False
    clips_are_sequential: bool = False

    # from config
    priority: int = 100
    source: str = None
    # # reproduction interval measured from START to START
    # # time between the END of a clip and the next one
    # interleave: int | None = None
    # repeat: int = 1
    # repeat_interval: int | None = None
    loop: bool = False
    # sequential: bool = True
    # random: bool = False
    # on_air_period: int | None = None
    clip_interval: int | None = None  # interval between sequential clip starts
    clip_period: int | None = None  # how many seconds we play of the clips
    #
    # discard_if_preempted: bool = False
    # pause_if_preempted: bool = True
    # restart_if_preempted: bool = False

    start_at: str = None
    end_at: str = None
    relative_start_at: int = None
    relative_end_at: int = None
    daily_start_at: str = None
    daily_end_at: str = None

    def __lt__(self, other):
        if self.start_timestamp != other.start_timestamp:
            return self.priority < other.priority
        else:
            return self.start_timestamp < other.start_timestamp


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
        scheduling_sources = [x for x in glob.glob(path) if os.path.isfile(x)]

        for scheduling_source in scheduling_sources:
            logger.debug(f"Load scheduling from {scheduling_source}")
            scheduling_data = yaml.safe_load(open(scheduling_source))
            new_channel = scheduling_data["groups"]
            await asyncio.gather(*[self._add_group(Group(**x)) for x in new_channel])

    async def _add_group(self, group: Group):
        logger.debug(f"Add group {group}")

        group.clip_paths = sorted(glob.glob(group.source))
        # find times and find start/end timestamps
        if not group.start_timestamp and group.relative_start_at:
            group.start_timestamp = datetime.timestamp(datetime.now() + timedelta(seconds=group.relative_start_at))
        if not group.start_timestamp and group.start_at:
            group.start_timestamp = datetime.timestamp(datetime.fromisoformat(group.start_at))
        if not group.start_timestamp and group.daily_start_at:
            dnow = datetime.now()
            din = datetime.fromisoformat(group.daily_start_at)
            d = din.replace(year=dnow.year, month=dnow.month, day=dnow.day)
            group.start = datetime.timestamp(d)
        if not group.end_timestamp and group.relative_end_at:
            group.end_timestamp = datetime.timestamp(datetime.now() + timedelta(seconds=group.relative_end_at))
        if not group.end_timestamp and group.end_at:
            group.end_timestamp = datetime.timestamp(datetime.fromisoformat(group.end_at))
        if not group.end_timestamp and group.daily_end_at:
            dnow = datetime.now()
            din = datetime.fromisoformat(group.daily_end_at)
            d = din.replace(year=dnow.year, month=dnow.month, day=dnow.day)
            group.end = datetime.timestamp(d)

        group.clips_are_sequential = group.clip_interval is None
        group.clips_are_timed = not group.clips_are_sequential

        if not group.clips and len(group.clip_paths) > 0:
            group.clips = []
            first_clip_start_timestamp = group.start_timestamp
            if not first_clip_start_timestamp and group.clips_are_timed:
                first_clip_start_timestamp = datetime.timestamp(datetime.now())
            clip_num = len(group.clip_paths)
            for clip_index, clip_path in enumerate(group.clip_paths):
                clip_start_timestamp = None
                if group.clips_are_timed:
                    clip_start_timestamp = first_clip_start_timestamp + clip_index * group.clip_interval
                clip = Clip(
                    priority=group.priority,
                    start_timestamp=clip_start_timestamp,
                    path=clip_path,
                    parent=group,
                    cursor=0,
                    cursor_stop_at=group.clip_period
                )
                if group.clips_are_sequential and group.loop and clip_index == clip_num - 1:
                    clip.reschedule_parent = True
                group.clips.append(clip)

        await self._schedule_group(group)

    async def _schedule_group(self, group: Group):
        if group.start_timestamp and datetime.timestamp(datetime.now()) < group.start_timestamp:
            await self.group_start_timestamp_schedule.put(
                tuple([group.start_timestamp, group.priority, group.id, group])
            )
        else:
            if group.clips_are_timed:
                subtasks = [self.clip_start_timestamp_schedule.put(
                    [c.start_timestamp, c.priority, c.id, c]
                ) for c in group.clips]
                await asyncio.gather(*subtasks)
            elif group.clips_are_sequential:
                subtasks = [self.clip_priority_schedule.put(
                    [c.priority, c.id, c]
                ) for c in group.clips]
                await asyncio.gather(*subtasks)
            else:
                raise Exception(f"Unknown group clips type")

    async def scheduler_task(self):
        try:
            while self.active:
                self.active = await self._schedule_tick()
                await asyncio.sleep(0.5)
        finally:
            self.vlc_client.stop()

    async def _schedule_tick(self):
        now = datetime.timestamp(datetime.now())
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
            return False

        await self._play_clip(next_clip)

        return True

    async def _play_clip(self, clip: Clip):
        logger.info(f"Play clip {clip}")

        if not clip.vlc_playlist_id:
            if clip.path in self.vlc_clip_playlist_id:
                clip.vlc_playlist_id = self.vlc_clip_playlist_id[clip.path]
            self.vlc_client.enqueue(clip.path)
            self.vlc_clip_playlist_id[clip.path] = clip.vlc_playlist_id = (
                    len(self.vlc_clip_playlist_id) + VLC_PLAYLIST_START_INDEX
            )
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
            c.cursor_stop_at = c.parent.clip_period
            stop = True

        if not stop and c.cursor >= c.cursor_stop_at:
            c.cursor_stop_at += c.parent.clip_period
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
