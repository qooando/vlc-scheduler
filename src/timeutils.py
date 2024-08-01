from datetime import datetime, timedelta
import pytimeparse


def string_to_delta(data):
    return timedelta(seconds=pytimeparse.parse(data))


def string_to_date(data):
    return datetime.fromisoformat(data)
