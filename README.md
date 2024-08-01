# vlc-scheduler

A python-based vlc scheduler for local videos. It was inspired by https://github.com/EugeneDae/VLC-Scheduler.

## Features

- Schedule images and videos based on priorities and times
- Play sequential stream, interrupt them with timed events
- Schedule and play video at specific times

### TODO

- [ ] Repeat group up to N times
- [ ] Repeat every clip up to N times
- [ ] Pause and resume an preempted lower-priority video
- [ ] Stop a group at a specified time (absolute max time or relative to start time)
- [ ] Improve performance
- [ ] Accept a specific format string for relative times (instead to force seconds) e.g. "1h 20m 34s"

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
groups:
  - source: "./glob/path1/**"
  - source: "./glob/path2/**"
```

A schedule file MUST contain `groups` and their parameters.

Other global parameters are:

`schedule_at: int | str = now()` start reference time for this schedule, used as base for any other relative time in the
file. Can be relative to current time (using integer) or absolute (string).

Default to current date and time. If you specify an integer (in seconds) it is the delay from now.

### Source parameters

#### Basic

`source: string` is a valid glob string, it selects which files are parte of this source.

`priority: int = 100` smaller integer means higher priority.

`loop: bool = False` loop the group

`schedule_at: int | str = 0`: number of seconds (from the base schedule `start_at`) or an absolute iso datetime

> e.g. start the source group at specific time (ISO format, current pc time)
> ```yaml
> groups:
>   - source: ./videos/background/**
>     start_at: "2024-08-01 16:88"
> ```
> 
> e.g. start the source group 5 minute after the scheduler start
> ```yaml
> groups:
>   - source: ./videos
>     start_at: 300
> ```
> e.g. start the source group 5 minute after the file base date
> ```yaml
> schedule_at: "2024-08-01 16:88"
> groups:
>   - source: ./videos/background/**
>     schedule_at: 300
> ```

`clip_interval: int`: interval in seconds between clips (from start to the next clip start)

#### Clips

`clip_period: int` how many seconds of each clip must be

`clip_loop: bool = False` repeat clips

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

