import asyncio
import sys
import typing
from datetime import datetime, timedelta
import glob
import os
from asyncio import PriorityQueue, QueueEmpty
from dataclasses import dataclass, Field, field, asdict, replace

import yaml
import logging

from src import build
from src.config import ALL_YAML_FILE, CONFIGFILE, VLC_PLAYLIST_FILE_REVERSE_INDEXES, VLC_PLAYLIST_INDEX_OFFSET
from src.timeutils import to_date, to_delta
from src.types import ScheduleClip, ScheduleFile, ScheduleSource
from vlc import VLCLauncher, VLCHTTPClient

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)

logging.getLogger("urllib3").setLevel(logging.WARNING)


class VideoScheduler:

    def __init__(self):
        self.config = yaml.safe_load(open(CONFIGFILE))
        self.clips = []
        self.tasks = []
        self.active = True
        self.group_start_timestamp_schedule = PriorityQueue()
        self.clip_priority_schedule = PriorityQueue()
        self.clip_start_timestamp_schedule = PriorityQueue()
        self.clip_on_air: ScheduleClip | None = None
        self.clip_on_wait: [ScheduleClip] = []
        self.vlc_clip_playlist_id: {} = {}
        self.polling_time = self.config["scheduling"]["polling_time"]

    async def load_schedule(self):
        schedule_path = os.path.join(self.config["scheduling"]["outDir"], ALL_YAML_FILE)
        data = yaml.safe_load(open(schedule_path))
        for clip_data in data["schedule"]:
            c = ScheduleClip(**clip_data)
            c.start_at = to_date(c.start_at)
            c.end_at = to_date(c.end_at)
            c.cursor_start_at = to_delta(c.cursor_start_at)
            c.cursor_end_at = to_delta(c.cursor_end_at)
            c.duration = to_delta(c.duration)
            if (c.path not in VLC_PLAYLIST_FILE_REVERSE_INDEXES):
                self.vlc_client.enqueue(c.path)
                VLC_PLAYLIST_FILE_REVERSE_INDEXES[c.path] \
                    = c.vlc_playlist_id \
                    = len(VLC_PLAYLIST_FILE_REVERSE_INDEXES) + VLC_PLAYLIST_INDEX_OFFSET
            else:
                c.vlc_playlist_id = VLC_PLAYLIST_FILE_REVERSE_INDEXES[c.path]

            self.clips.append(c)

    async def schedule_clip(self, clip: ScheduleClip):
        assert clip.vlc_playlist_id
        self.vlc_client.stop()
        self.vlc_client.play(clip.vlc_playlist_id)
        self.vlc_client.repeat(clip.loop)
        self.clip_on_air = clip

    async def task_schedule_clips(self):
        clips_to_air: [ScheduleClip] = [*self.clips]
        next_clip: ScheduleClip | None = None
        while clips_to_air or self.clip_on_air:

            now = datetime.now()
            curr_clip = self.clip_on_air
            if clips_to_air and clips_to_air[0] is not next_clip:
                next_clip = clips_to_air[0]
                logger.debug(f"Next clip: {next_clip.path}, scheduled at {next_clip.start_at}")

            # skip already ended
            while clips_to_air and now > next_clip.end_at:
                discarded = clips_to_air.pop(0)
                logger.debug(f"Discard clip: {discarded.path} ends at {discarded.end_at}")
                if clips_to_air:
                    next_clip = clips_to_air[0]

            if curr_clip and now > curr_clip.end_at:
                logger.debug(f"Stop clip: {curr_clip.path}")
                self.vlc_client.stop()
                self.clip_on_air = None
                curr_clip = None

            if next_clip and now > next_clip.start_at:
                if clips_to_air:
                    clips_to_air.pop(0)
                cursor = round((next_clip.cursor_start_at + (now - next_clip.start_at)).total_seconds())
                if cursor > next_clip.duration.total_seconds():
                    logger.warning(f"Cursor is bigger than duration")
                logger.info(f"Play clip: {next_clip.path} seek={cursor}")
                self.vlc_client.play(next_clip.vlc_playlist_id)
                self.vlc_client.seek(cursor)
                self.vlc_client.repeat(next_clip.loop)
                self.clip_on_air = next_clip
                next_clip = None

            await asyncio.sleep(self.polling_time or 0.5)

        logger.info(f"No more clips to air")

    async def _check_clip_on_air(self):
        c = self.clip_on_air
        vlc_status = self.vlc_client.status()
        c.cursor = vlc_status["time"]

        stop = False

        if not stop and vlc_status["state"] == "stopped":
            c.cursor = 0
            if c.parent.clip_play_duration:
                c.cursor_stop_at = c.parent.clip_play_duration.total_seconds()
            stop = True

        if not stop and c.cursor_stop_at and c.cursor >= c.cursor_stop_at:
            c.cursor_stop_at += c.parent.clip_play_duration.total_seconds()
            self.vlc_client.pause()
            stop = True

        return not stop

    async def start_scheduling(self, debug=False):
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
            }, debug=debug)
            await self.vlc_launcher.launch()
            # self.tasks.append(self.vlc_launcher.watch_exit())

        self.vlc_client = VLCHTTPClient({
            "host": self.config["vlc"]["host"],
            "port": self.config["vlc"]["port"],
            "password": self.config["vlc"]["password"]
        })

        self.vlc_client.loop(False)
        self.vlc_client.repeat(False)

        await self.load_schedule()
        self.tasks.append(self.task_schedule_clips())
        self.tasks.append(self.vlc_launcher.watch_exit())

        logger.info("Start scheduling")
        try:
            await asyncio.gather(*self.tasks)
        finally:
            logger.info('Stop scheduling')


async def main():
    logger.info("Start")
    vs = VideoScheduler()
    await vs.start_scheduling(debug=False)


if __name__ == "__main__":
    asyncio.run(main())
