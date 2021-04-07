import calendar
import dataclasses
import datetime
import os
from typing import Any, Dict, Iterator, List, Optional, Set

import requests
import rich

from cloclify.utils import (APIError, UsageError, _from_iso_timestamp,
                            _to_iso_timestamp)


@dataclasses.dataclass
class Entry:

    start: Optional[datetime.datetime] = None
    end: Optional[datetime.datetime] = None
    description: Optional[str] = None
    billable: bool = False
    project: Optional[str] = None
    project_color: Optional[str] = None
    tags: List[str] = dataclasses.field(default_factory=list)
    eid: Optional[str] = None

    def serialize(self, *, projects: Dict[str, Any], tags: Dict[str, Any]) -> Any:
        if self.start is None:
            # for PATCH
            assert self.end is not None
            return {
                "end": _to_iso_timestamp(self.end),
            }

        data: Dict[str, Any] = {}

        data["start"] = _to_iso_timestamp(self.start)

        if self.end is not None:
            data["end"] = _to_iso_timestamp(self.end)

        if self.description is not None:
            data["description"] = self.description

        data["billable"] = self.billable

        if self.project is not None:
            data["projectId"] = projects[self.project]["id"]

        if self.tags is not None:
            data["tagIds"] = [tags[tag]["id"] for tag in self.tags]

        return data

    @classmethod
    def deserialize(
        cls, data: Any, *, projects: Dict[str, Any], tags: Dict[str, Any]
    ) -> "Entry":
        entry = cls(data["description"])

        entry.start = _from_iso_timestamp(data["timeInterval"]["start"])

        if data["timeInterval"]["end"] is not None:
            entry.end = _from_iso_timestamp(data["timeInterval"]["end"])

        entry.description = data["description"]
        entry.billable = data["billable"]

        if data["projectId"] is not None:
            project = projects[data["projectId"]]
            entry.project = project["name"]
            entry.project_color = project["color"]

        if data["tagIds"] is not None:
            for tag_id in data["tagIds"]:
                entry.tags.append(tags[tag_id]["name"])

        entry.eid = data["id"]

        return entry


class ClockifyClient:

    API_URL = "https://api.clockify.me/api/v1"

    def __init__(self, debug: bool = False, workspace: str = None) -> None:
        self._debug = debug
        try:
            key = os.environ["CLOCKIFY_API_KEY"]
        except KeyError as e:
            raise UsageError(f"{e} not defined in environment")

        if workspace is None:
            try:
                self._workspace_name = os.environ["CLOCKIFY_WORKSPACE"]
            except KeyError as e:
                raise UsageError(
                    f"{e} not defined in environment and " "'^workspace' not given"
                )
        else:
            self._workspace_name = workspace

        self._headers = {"X-Api-Key": key}
        self._user_id = None
        self._workspace_id = None

        self._projects_by_name: Dict[str, str] = {}
        self._projects_by_id: Dict[str, str] = {}

        self._tags_by_name: Dict[str, str] = {}
        self._tags_by_id: Dict[str, str] = {}

    def _api_call(self, verb: str, path: str, **kwargs: Any) -> Any:
        if self._debug:
            rich.print(f"[u]{verb.upper()} {path}[/u]:", kwargs, "\n")

        func = getattr(requests, verb.lower())
        response = func(f"{self.API_URL}/{path}", headers=self._headers, **kwargs)
        if not response.ok:
            raise APIError(verb.upper(), path, response.status_code, response.json())

        r_data = response.json()
        if self._debug:
            rich.print(f"[u]Answer[/u]:", r_data, "\n")
        return r_data

    def _api_get(self, path: str, params: Dict[str, str] = None) -> Any:
        return self._api_call("get", path, params=params)

    def _api_post(self, path: str, data: Any) -> Any:
        return self._api_call("post", path, json=data)

    def _api_patch(self, path: str, data: Any) -> Any:
        return self._api_call("patch", path, json=data)

    def _fetch_workspace_id(self) -> None:
        workspaces = self._api_get("workspaces")
        for workspace in workspaces:
            if workspace["name"] == self._workspace_name:
                self._workspace_id = workspace["id"]
                return
        raise UsageError(
            f"No workspace [yellow]{self._workspace_name}[/yellow] " "found!"
        )

    def _fetch_user_id(self) -> None:
        info = self._api_get("user")
        self._user_id = info["id"]

    def _fetch_projects(self) -> None:
        projects = self._api_get(f"workspaces/{self._workspace_id}/projects")
        for proj in projects:
            self._projects_by_name[proj["name"]] = proj
            self._projects_by_id[proj["id"]] = proj

    def _fetch_tags(self) -> None:
        tags = self._api_get(f"workspaces/{self._workspace_id}/tags")
        for tag in tags:
            self._tags_by_name[tag["name"]] = tag
            self._tags_by_id[tag["id"]] = tag

    def fetch_info(self) -> None:
        self._fetch_workspace_id()
        self._fetch_user_id()
        self._fetch_projects()
        self._fetch_tags()

    def add_entries(self, date: datetime.date, entries: List[Entry]) -> Set[str]:
        added_ids = set()
        for entry in entries:
            data = entry.serialize(
                projects=self._projects_by_name,
                tags=self._tags_by_name,
            )

            if entry.start is None:
                # Finishing a started entry
                endpoint = (
                    f"workspaces/{self._workspace_id}/user/{self._user_id}/time-entries"
                )
                r_data = self._api_patch(endpoint, data)
            else:
                # Adding a new entry
                endpoint = f"workspaces/{self._workspace_id}/time-entries"
                r_data = self._api_post(endpoint, data)

            # XXX Maybe do some sanity checks on the returned data?

            added_ids.add(r_data["id"])
        return added_ids

    def get_entries_day(self, date: datetime.date) -> Iterator[Entry]:
        start = datetime.datetime.combine(date, datetime.time())
        end = start + datetime.timedelta(days=1)
        return self._get_entries(start, end)

    def get_entries_month(self, date: datetime.date) -> Iterator[Entry]:
        assert date.day == 1, date
        first_date = datetime.date(date.year, date.month, 1)
        _first_weekday, last_day = calendar.monthrange(date.year, date.month)
        last_date = datetime.date(date.year, date.month, last_day)

        start = datetime.datetime.combine(first_date, datetime.time())
        end = datetime.datetime.combine(last_date, datetime.time.max)
        return self._get_entries(start, end)

    def _get_entries(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> Iterator[Entry]:
        endpoint = f"workspaces/{self._workspace_id}/user/{self._user_id}/time-entries"
        params = {
            "start": _to_iso_timestamp(start),
            "end": _to_iso_timestamp(end),
        }
        data = self._api_get(endpoint, params)
        for entry in data:
            yield Entry.deserialize(
                entry, projects=self._projects_by_id, tags=self._tags_by_id
            )

    def validate(self, *, tags: List[str], project: Optional[str]) -> None:
        for tag in tags:
            if tag not in self._tags_by_name:
                raise UsageError(f"Unknown tag {tag}")

        if project is not None and project not in self._projects_by_name:
            raise UsageError(f"Unknown project {project}")
