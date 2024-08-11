import asyncio
import csv
import sys
import typing
from datetime import datetime, timedelta
import glob
import os
from asyncio import PriorityQueue, QueueEmpty
from dataclasses import dataclass, Field, field, asdict, replace

import yaml
import logging

from src.config import ALL_YAML_FILE, FILTERED_YAML_FILE, FILTERED_CSV_FILE
from src.timeutils import to_delta, to_date, video_duration
from src.types import ScheduleFile, ScheduleSource, ScheduleClip
from vlc import VLCLauncher, VLCHTTPClient

CONFIGFILE = os.getenv('CONFIG') or "config.yaml"

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)

logging.getLogger("urllib3").setLevel(logging.WARNING)


class ScheduleBuilder:
    def __init__(self):
        self.config = yaml.safe_load(open(CONFIGFILE))
        self._all_prioritized_clips = PriorityQueue()
        self.schedule = []

    async def load_schedule_files(self):
        path = self.config["scheduling"]["path"]
        logger.info(f"Load schedules from {path}")
        schedule_files = [x for x in glob.glob(path) if os.path.isfile(x)]

        for schedule_path in schedule_files:
            await self._load_schedule_file(schedule_path)

    async def _load_schedule_file(self, schedule_path):
        assert schedule_path
        try:
            schedule_data = yaml.safe_load(open(schedule_path))
            if not schedule_data:
                # logger.debug(f"Schedule {schedule_path} is empty")
                return
            logger.info(f"Load schedule {schedule_path}")
            schedule_file = ScheduleFile(**schedule_data)
        except TypeError as e:
            logger.warning(f"Load failed: {e}")
            return

        file_start_at = schedule_file.start_at = to_date(schedule_file.start_at, start_date=datetime.now(),
                                                         default=datetime.now())
        file_end_at = schedule_file.end_at = to_date(schedule_file.end_at, start_date=file_start_at, default=None)

        if not schedule_file.sources:
            return

        sources = [ScheduleSource(parent=schedule_file, **x) for x in schedule_file.sources]

        for s in sources:
            await self._load_schedule_source(s, start_at=file_start_at, end_at=file_end_at)

    async def _load_schedule_source(self, s, start_at: datetime, end_at: datetime):
        assert (s)
        logger.debug(f"Add source {s.source}")
        s.clip_paths = sorted(glob.glob(s.source))
        source_start_at = s.start_at = to_date(s.start_at, start_date=start_at, default=start_at)
        s.end_at = to_date(s.end_at, start_date=source_start_at, default=None)
        clip_repeat_interval = s.clip_repeat_interval = to_delta(s.clip_repeat_interval, start_date=source_start_at,
                                                                 default=None)
        clip_play_duration = s.clip_play_duration = to_delta(s.clip_play_duration, start_date=source_start_at,
                                                             default=None)

        are_sequential = s.clips_are_sequential = s.clip_repeat_interval is None
        are_cadenced = s.clips_are_cadenced = not s.clips_are_sequential

        if s.clips or not s.clip_paths:
            return s

        s.clips = []

        clip_start_at = source_start_at

        for i, p in enumerate(s.clip_paths):
            clip = await self._load_schedule_clip(
                p, clip_index=i, parent=s,
                clip_start_at=clip_start_at,
                clip_play_duration=clip_play_duration,
                clip_loop=s.clip_loop
            )

            if are_sequential:
                clip_start_at += clip.duration
            elif are_cadenced:
                clip_start_at += clip_repeat_interval
                if clip_repeat_interval < clip.duration:
                    logger.warning(f"Clip repeat interval {clip_repeat_interval} < clip duration {clip.duration}")
            else:
                raise NotImplemented()

    async def _load_schedule_clip(self,
                                  clip_path: str,
                                  clip_index: int,
                                  parent: ScheduleSource,
                                  clip_start_at: datetime,
                                  clip_play_duration: timedelta,
                                  clip_loop: bool):
        logger.debug(f"Add clip {clip_path}")
        assert clip_path
        assert parent
        assert clip_start_at

        clip_duration = video_duration(clip_path)
        clip_play_duration = clip_play_duration or clip_duration

        c = ScheduleClip(
            priority=parent.priority,
            parent=parent,
            path=clip_path,
            start_at=clip_start_at,
            end_at=to_date(clip_play_duration, clip_start_at, default=None),
            duration=clip_duration,
            play_duration=clip_play_duration,
            loop=clip_loop,  # end_at can be after actual video end, thus loop it
            cursor_start_at=timedelta(seconds=0),
            cursor_end_at=clip_play_duration
        )

        await self._all_prioritized_clips.put(c)
        return c

    async def process_schedule(self):
        await self.load_schedule_files()

        p = self._all_prioritized_clips
        s = self.schedule

        last_clip: ScheduleClip | None = None
        while not p.empty():
            to_insert = await p.get()
            if not last_clip:
                s.append(to_insert)
                last_clip = s[-1]
                continue

            # if to_insert.start_at < last_clip.start_at:
            #     raise ValueError(f"Clips are not ordered by increasing time")
            # if to_insert.start_at == last_clip.start_at:
            #     if to_insert.priority < last_clip.priority:
            #         raise ValueError(f"Clips are not ordered by increasing priority")
            #     continue # ignore same priority and same time
            # if to_insert.start_at < last_clip.end_at:
            #     if to_insert.priority >= last_clip.priority:
            #         # FIXME insert clip but eventually crop it
            #         pass
            # NOTE: here we need to insert the element, but previous one can be eventually split in two
            s.append(to_insert)
            last_clip = s[-1]

    async def save_schedule(self):
        prio_level = self.config["scheduling"]["outPriorityLevel"]
        outPath = self.config["scheduling"]["outDir"]
        os.makedirs(outPath, exist_ok=True)

        path = os.path.join(outPath, ALL_YAML_FILE)
        yaml.Dumper.ignore_aliases = lambda *args: True
        yaml.add_representer(timedelta, lambda dumper, data: dumper.represent_str(str(data)))
        yaml.dump({"schedule": self.schedule}, open(path, "w"))

        path = os.path.join(outPath, FILTERED_YAML_FILE)
        yaml.Dumper.ignore_aliases = lambda *args: True
        yaml.add_representer(timedelta, lambda dumper, data: dumper.represent_str(str(data)))
        yaml.dump({"schedule": [x for x in self.schedule if x.priority <= prio_level]}, open(path, "w"))

        path = os.path.join(outPath, FILTERED_CSV_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', newline='') as csvfile:
            w = csv.writer(csvfile,
                           delimiter=',',
                           quotechar='"',
                           quoting=csv.QUOTE_MINIMAL)
            w.writerow(['start_at', 'duration', 'path'])
            for s in self.schedule:
                if s.priority <= prio_level:
                    w.writerow([s.start_at, s.duration, s.path])


async def main():
    logger.info("Build schedule")
    sb = ScheduleBuilder()
    await sb.process_schedule()
    await sb.save_schedule()


if __name__ == "__main__":
    asyncio.run(main())
