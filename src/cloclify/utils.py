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


def to_iso_timestamp(dt: datetime.datetime, *, timezone=dateutil.tz.UTC) -> str:
    """Convert time to the (weird) format clockify expects.

    Clockify mentions needing ISO-8601 times, but it *always* expects a Z
    suffix, even if the time isn't UTC... hell.
    """
    return dt.astimezone(timezone).isoformat().split("+")[0] + "Z"
