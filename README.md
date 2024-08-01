# vlc-scheduler

A python-based vlc scheduler for local videos. It was inspired by https://github.com/EugeneDae/VLC-Scheduler.

## Features

- Schedule videos based on time and priorities
- Play sequential stream
- Schedule and play video at specific times

## Fast start

Call

```bash
chmod +x ./prepare.sh
./prepare.sh
```

to create virtual environment and install dependencies.

Then

```bash
chmod +x ./start.sh
./start.sh
```

to open VLC and start the scheduling.

## Application config

Default application configuration is in `config.yaml` file.
It includes generic vlc parameters and where scheduling reads files.

Set `scheduling.path` to a valid glob string, e.g. `./scheduling/**.yaml`.

## Schedulings

You can configure schedules adding them to
the correct search path defined in the `config.yaml`.

You can find examples in the `examples` folder.

Schedules are yaml files in the following format

```yaml
groups:
  - source: "./glob/path1/**"
  - source: "./glob/path2/**"
```

A schedule file MUST contain `groups` list of sources and
their parameters.

### Source parameters

#### Basic parameters

`source` is a valid glob string, it selects which files are parte of this source.
    
