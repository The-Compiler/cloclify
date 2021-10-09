import datetime

import dateutil.parser
import dateutil.tz


class Error(Exception):
    pass


class UsageError(Error):
    pass


class APIError(Error):
    def __init__(self, method: str, path: str, status: int, data: str) -> None:
        super().__init__(f"API {method} to {path} failed with {status}: {data}")


def from_iso_timestamp(timestamp: str, timezone: datetime.tzinfo) -> datetime.datetime:
    utc = dateutil.parser.isoparse(timestamp)
    return utc.astimezone(timezone)


def to_iso_timestamp(dt: datetime.datetime) -> str:
    return dt.astimezone(dateutil.tz.UTC).isoformat().replace("+00:00", "Z")
