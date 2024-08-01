# vlc-scheduler

A python-based vlc scheduler for local videos. It was inspired by https://github.com/EugeneDae/VLC-Scheduler.

## Features

- Schedule videos based on time and priorities
- Play sequential stream
- Schedule and play video at specific times

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

`schedule_at: str = now()` start reference time for this schedule, used as base for any other relative time in the file.
Default to current date and time. If you specify an integer (in seconds) it is the delay from now.

### Source parameters

#### Basic

`source: string` is a valid glob string, it selects which files are parte of this source.

`priority: int = 100` smaller integer means higher priority.

`loop: bool = True` loop the group

`start_at: int | str = 0`: number of seconds (from the base schedule `start_at`) or an absolute iso datetime

`clip_interval: int`: interval in seconds between clips (from start to the next clip start)

#### Clips

`clip_period: int` how many seconds of each clip must be

`clip_loop: bool = False` repeat clips

## Troubleshooting

### Black screen flashes between clips

It is mitigated settings vlc to real time scheduler in advanced configuration.
