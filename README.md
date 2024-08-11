# vlc-scheduler

A python-based vlc scheduler for local videos. It was inspired by https://github.com/EugeneDae/VLC-Scheduler.

## Features

- Schedule images and videos based on priorities and times
- Play sequential stream, interrupt them with timed events
- Schedule and play video at specific times

### TODO

- [ ] Repeat group up to N times
- [ ] Repeat every clip up to N times
- [ ] Improve performance

## Fast start (linux)

Call

```bash
./prepare.sh
```

to create the python virtual environment and install dependencies.

Then

```bash
./start.sh
```

to open VLC and start the scheduling.

Schedulings are defined in yaml files in the `./scheduling/` folder

## Application config

Default application configuration is in `config.yaml` file.
It includes generic vlc parameters and where scheduling reads files.

Set `scheduling.path` to a valid glob string, e.g. `./scheduling/**.yaml`.

## Scheduling

You can configure schedules adding them to
the correct search path defined in the `config.yaml`.

You can find examples in the `examples` folder.

Schedules are yaml files in the following format

```yaml
sources:
  - source: "./glob/path1/**"
  - source: "./glob/path2/**"
```

A schedule file MUST contain `groups` and their parameters.

Other global parameters are:

`start_at: int | str = now()` start time. Can be an absolute iso string `2024-08-01 11:12:13`,
or a relative time (evaluate from `now()`) in seconds `120` or a relative time in `hh:mm:ss` format. 
This is the default star time for all sources in the file.

`end_at: int | str = None` end time. Can be an absolute iso string or a relative (to `start_time`) time. 

### Source parameters

`source: string` is a valid glob string, it selects which files are parte of this source.

`priority: int = 100` smaller integer means higher priority. Specify a low priority (e.g. 100) for background videos, 
and higher priority (e.g. 0) for important videos that must interrupt background videos.

`loop: bool = False` loop the full group. It **requires** an `end_at` time

`start_at: int | str`: start time for this source, default is file `start_at`. You can specify an absolute isoformat
date or a relative (to file `start_at`) time.

`end_at: int | str`: end time for this source, default is `start_at` + all video play times.

> e.g. start the source group at specific time (ISO format, current pc time)
> ```yaml
> sources:
>   - source: ./videos/background/**
>     start_at: "2024-08-01 16:88"
> ```
> 
> e.g. start the source group 5 minute after the scheduler start
> ```yaml
> sources:
>   - source: ./videos
>     start_at: "5m"
> ```
> e.g. start the source group 5 minute after the file base date
> ```yaml
> start_at: "2024-08-01 16:88"
> sources:
>   - source: ./videos/background/**
>     start_at: 300
> ```

`clip_play_duration = int | str` time delta the video must be scheduled (e.g. `15m 5s` or `00:15:05`). Can be shorter or longer than

`clip_loop = false` put the single clip in loop, useful if play time is greater than clip duration.

`clip_repeat_interval` start clip every interval time, this is the start time, it should be greater than clip play duration or they will overlap.

`clip_stop_if_interrupted = true` avoid to reschedule the remaining clip time if it was interrupted by a higher priority clip.

`clip_restart_after_interruption` restart the clip after interruption

`clip_continue_after_interruption` reschedule the clip if interrupted, starts at the same cursor where it was interrupted

`clip_skip_time_after_interruption` reschedule the clip if interrupted, take in account the elapsed time consumed by the interrupting clip, as if we just change between two channels

### Time formats

Accepted time formats are:

`YYYY-MM-DD hh:mm:ss` isoformat for absolute times

`hh:mm:ss` simple hour, minutes, seconds format for relative times and deltas

`10h 3m 2s` for relative times and deltas, you can specify only one or two items (e.g `60s`, `1m`)

`1234` simple numbers are evaluated in seconds

## VLC

### Tweaks

### Troubleshooting

#### Black screen flashes between clips

As mitigation, check real time priority in VLC settings
```
VLC > Tools > Settings > Advanced Settings > Advanced > Allow real-time-priority
```

#### VLC logo between clips

Uncheck VLC logo in VLC settings
```
VLC > Tools > Settings > Advanced Settings > Interface > Main interfaces > Qt > Display background cone or art
```

