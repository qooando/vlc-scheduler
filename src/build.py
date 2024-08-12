import asyncio
import csv
import math
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
from src.timeutils import to_delta, to_date, video_duration, fmod_delta
from src.scheduler_types import ScheduleFile, ScheduleSource, ScheduleClip
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
            await self._load_schedule_source(s, file_start_at=file_start_at, file_end_at=file_end_at)

    async def _load_schedule_source(self, s, file_start_at: datetime, file_end_at: datetime):
        assert (s)
        logger.debug(f"Add source {s.source}")

        source_clip_paths = s.clip_paths = sorted(glob.glob(s.source))
        source_start_at = s.start_at = to_date(s.start_at, start_date=file_start_at, default=file_start_at)
        source_end_at = s.end_at = to_date(s.end_at, start_date=source_start_at, default=file_end_at)
        clip_repeat_interval = s.clip_repeat_interval = to_delta(s.clip_repeat_interval, start_date=source_start_at,
                                                                 default=None)
        clip_play_duration = s.clip_play_duration = to_delta(s.clip_play_duration, start_date=source_start_at,
                                                             default=None)

        are_sequential = s.clips_are_sequential = s.clip_repeat_interval is None
        are_cadenced = s.clips_are_cadenced = not s.clips_are_sequential

        s.clip_stop_if_interrupted = (not s.clip_continue_after_interruption and
                                      not s.clip_restart_after_interruption and
                                      not s.clip_skip_time_after_interruption)

        s.clip_loop = s.clip_loop or s.clip_continue_after_interruption or s.clip_skip_time_after_interruption
        s.clip_loop = s.clip_loop or s.clip_continue_after_interruption or s.clip_skip_time_after_interruption

        if s.clips or not s.clip_paths:
            return s

        s.clips = []

        clip_start_at = source_start_at
        clip_end_at = None

        if s.loop and not s.end_at:
            raise ValueError(f"Loop source must specify an end_at time")

        clip_states = {}

        while not s.loop or (s.loop and s.end_at and (not clip_end_at or clip_end_at < s.end_at)):
            for i, p in enumerate(s.clip_paths):
                prev_state: ScheduleClip = clip_states[p] if p in clip_states else None

                clip_cursor_start_at = timedelta(0)

                if prev_state:
                    if s.clip_continue_after_interruption:
                        clip_cursor_start_at = prev_state.cursor_end_at
                    if s.clip_skip_time_after_interruption:
                        clip_cursor_start_at = prev_state.cursor_end_at + (clip_start_at - prev_state.end_at)
                        assert clip_cursor_start_at >= timedelta(0)

                if s.end_at and clip_start_at >= s.end_at:
                    break

                clip = await self._load_schedule_clip(
                    p, clip_index=i, parent=s,
                    clip_start_at=clip_start_at,
                    clip_max_end_at=s.end_at,
                    clip_play_duration=clip_play_duration,
                    clip_loop=s.clip_loop,
                    clip_cursor_start_at=clip_cursor_start_at
                )

                clip_states[p] = clip
                clip_end_at = clip.end_at

                if are_sequential:
                    clip_start_at += clip.play_duration
                elif are_cadenced:
                    clip_start_at += clip_repeat_interval
                    if clip_repeat_interval < clip.play_duration:
                        logger.warning(
                            f"Clip repeat interval {clip_repeat_interval} < clip duration {clip.play_duration}")
                else:
                    raise NotImplemented()
            if not s.loop:
                break

    async def _load_schedule_clip(self,
                                  clip_path: str,
                                  clip_index: int,
                                  parent: ScheduleSource,
                                  clip_start_at: datetime,
                                  clip_play_duration: timedelta,
                                  clip_loop: bool,
                                  clip_cursor_start_at: timedelta,
                                  clip_max_end_at: datetime):
        assert clip_path
        assert parent
        assert clip_start_at
        assert not clip_cursor_start_at or clip_cursor_start_at >= timedelta(0)

        clip_duration = video_duration(clip_path)
        clip_play_duration = clip_play_duration or clip_duration
        clip_cursor_start_at = fmod_delta(clip_cursor_start_at, clip_duration)
        clip_cursor_end_at = fmod_delta(clip_cursor_start_at + clip_play_duration, clip_duration)
        if clip_cursor_start_at.total_seconds() > clip_duration.total_seconds():
            logger.warning(f"Cursor start > clip duration")
        if clip_cursor_end_at.total_seconds() > clip_duration.total_seconds():
            logger.warning(f"Cursor end > clip duration")
        clip_end_at = to_date(clip_play_duration, clip_start_at, default=None)
        if clip_max_end_at:
            clip_end_at = min(clip_end_at, clip_max_end_at)

        c = ScheduleClip(
            priority=parent.priority,
            parent=parent,
            path=clip_path,
            start_at=clip_start_at,
            end_at=clip_end_at,
            duration=clip_duration,
            play_duration=clip_play_duration,
            loop=clip_loop,  # end_at can be after actual video end, thus loop it
            cursor_start_at=clip_cursor_start_at,
            cursor_end_at=clip_cursor_end_at
        )

        logger.debug(
            f"Add clip {clip_path} start {c.start_at} end {c.end_at}, cursor start {c.cursor_start_at} end {c.cursor_end_at}")

        await self._all_prioritized_clips.put(c)
        return c

    async def process_schedule(self):
        await self.load_schedule_files()

        prioritized = self._all_prioritized_clips
        schedule = self.schedule

        _prev: ScheduleClip | None = None
        while not prioritized.empty():
            _next: ScheduleClip = await prioritized.get()
            logger.debug(f"Reorder clip {_next.path}")

            if not _prev:
                schedule.append(_next)
                _prev = schedule[-1]
                continue

            if _next.start_at < _prev.start_at:
                raise ValueError(f"Clips are not ordered by increasing time")
            if _next.start_at == _prev.start_at:
                if _next.priority < _prev.priority:
                    raise ValueError(f"Clips are not ordered by increasing priority")
                # ignore same priority and same time
                logger.debug(f"Skip {_next.path}, same priority and time of _prev")
                continue
            if _next.start_at < _prev.end_at:
                if _next.priority >= _prev.priority:
                    if _next.end_at <= _prev.end_at:
                        # new clip is shorter and with lower priority, just skip
                        logger.debug(f"Skip {_next.path}, an higher priority clip start and ends before and after the clip")
                        continue
                    logger.debug(f"Crop low priority clip: {_next.path}")
                    _next_source: ScheduleSource = _next.parent
                    _next_old_start_at = _next_source.start_at
                    _next_source.start_at = _prev.start_at
                    _next.play_duration = min(_next.play_duration, _next.end_at - _next.start_at)
                    if _next_source.clip_restart_after_interruption:
                        pass
                    elif (_next_source.clip_continue_after_interruption or
                          _next_source.clip_skip_time_after_interruption):
                        _next.cursor_start_at = fmod_delta(
                            _next.cursor_start_at + _next.start_at - _next_old_start_at,
                            _next.play_duration
                        )
                    _next.cursor_end_at = _next.cursor_start_at + _next.play_duration
                    schedule.append(_next)
                else:
                    logger.debug(f"Insert high priority clip: {_prev.path}")
                    schedule.append(_next)

                    # crop previous clip, eventually split it in two
                    _prev_source: ScheduleSource = _prev.parent
                    _clone = _prev.clone()

                    crop_delta = _prev.end_at - _next.start_at
                    logger.debug(f"Crop clip {_prev.path} end by {crop_delta}")
                    _prev.crop_end_time(crop_delta)

                    if not _prev_source.clip_stop_if_interrupted:
                        # _clone.crop_start_time(_prev.play_duration)
                        # _clone.change_start_time(_next.end_at)

                        if _prev_source.clip_restart_after_interruption:
                            _clone.change_cursor_start_at(timedelta(0))
                            _clone.change_start_time(_next.end_at)

                        elif _prev_source.clip_continue_after_interruption:
                            _clone.crop_start_time(_prev.play_duration)
                            _clone.change_start_time(_next.end_at)

                        elif _prev_source.clip_skip_time_after_interruption:
                            _clone.crop_start_time(_prev.play_duration + _next.play_duration)

                        schedule.append(_clone)
            elif _next:
                schedule.append(_next)

            _prev = schedule[-1]

    async def save_schedule(self):
        prio_level = self.config["scheduling"]["outPriorityLevel"]
        outPath = self.config["scheduling"]["outDir"]
        os.makedirs(outPath, exist_ok=True)

        yaml.add_representer(timedelta, lambda dumper, data: dumper.represent_str(str(data)))
        yaml.add_representer(datetime, lambda dumper, data: dumper.represent_str(data.isoformat()))

        path = os.path.join(outPath, ALL_YAML_FILE)
        yaml.Dumper.ignore_aliases = lambda *args: True
        yaml.dump({"schedule": self.schedule}, open(path, "w"))

        path = os.path.join(outPath, FILTERED_YAML_FILE)
        yaml.Dumper.ignore_aliases = lambda *args: True
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
