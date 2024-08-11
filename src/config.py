import os

FILTERED_CSV_FILE = "scheduled.filtered.csv"
FILTERED_YAML_FILE = "scheduled.filtered.yaml"
ALL_YAML_FILE = "scheduled.all.yaml"
VLC_PLAYLIST_INDEX_OFFSET = 3
VLC_PLAYLIST_FILE_REVERSE_INDEXES = {}

CONFIGFILE = os.getenv('CONFIG') or "config.yaml"
