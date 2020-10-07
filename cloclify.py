#!/usr/bin/python3

import os
import sys
import datetime
import argparse
import dataclasses
from typing import (List, Dict, Any, Set, AbstractSet, Iterator, Iterable, Tuple,
                    Optional)

import requests
import dateparser
import dateutil.parser
import dateutil.tz
import rich.console
import rich.table
import rich.box
import rich.panel


class Error(Exception):
    pass


class UsageError(Error):
    pass


class APIError(Error):

    def __init__(self, method: str, path: str, status: int, data: str) -> None:
        super().__init__(f'API {method} to {path} failed with {status}: {data}')


Timespan = Tuple[Optional[datetime.datetime], Optional[datetime.datetime]]


class ArgumentParser:

    """Arguments are parsed based on how they look:

    HH:MM-HH:MM    Add a new time entry based on the given times.

    {HH:MM         "Clock in" at the given time.
    }HH:MM         "Clock out" at the given time.

    {now           Clock in now
    start          (convenience alias)

    }now           Clock out now
    end            (convenience alias)

    +tag           Add the given tag to all specified time entries.
    @project       Set the given project for all specified time entries.
    $              Mark all specified time entries as billable.
    ^workspace     Add all entries to the given workspace.
                   (If not given, the CLOCKIFY_WORKSPACE envvar is used)

    .date          Show/edit time entries for the given date.
                   Can be relative (".yesterday", ".5 days ago") or absolute
                   (".2020-10-01"). Make sure to quote spaces.

    description    Any arguments without a prefix are parsed as description.
                   Quoting is optional, as multiple arguments will be space-joined.

    Examples:

    $ cloclify start @qutebrowser issue1234   # Start working on a project
    $ cloclify stop                           # Take a break

    $ cloclify {12:30 @qutebrowser issue1235  # Retroactively start "stopwatch mode"
    $ cloclify }17:00                         # Retroactively stop working

    # Add a manual time entry
    # Project: "secretproject"
    # Tags: "collab", "external"
    # Billable: true
    # Date: yesterday
    # Time: 13:00 to 17:00

    $ cloclify @secretproject +collab +external $ .yesterday 13:00-17:00
    """

    def __init__(self) -> None:
        self._timespans: List[Timespan] = []
        self._description: str = ""
        self._billable: bool = False

        self.date: datetime.date = datetime.datetime.now().date()
        self.entries: List[Entry] = []
        self.debug: bool = False
        self.tags: List[str] = []
        self.project: Optional[str] = None
        self.workspace: Optional[str] = None

        self._parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=self.__doc__
        )
        self._parser.add_argument('inputs', help="An argument like described above.",
                                  metavar='input', nargs='*')
        self._parser.add_argument('--debug', help='Enable debug output', action='store_true')

    def _parse_time(self, time_str: str) -> datetime.datetime:
        if time_str == 'now':
            return datetime.datetime.now()

        try:
            time = datetime.datetime.strptime(time_str, '%H:%M').time()
        except ValueError as e:
            raise UsageError(str(e))
        return datetime.datetime.combine(self.date, time)

    def _parse_timespan(self, arg: str) -> None:
        try:
            start_str, end_str = arg.split('-')
        except ValueError:
            raise UsageError(f"Couldn't parse timespan {arg} (too many '-')")

        start_dt = self._parse_time(start_str)
        end_dt = self._parse_time(end_str)
        self._timespans.append((start_dt, end_dt))

    def _parse_start(self, arg: str) -> None:
        dt = self._parse_time(arg)
        self._timespans.append((dt, None))

    def _parse_stop(self, arg: str) -> None:
        dt = self._parse_time(arg)
        self._timespans.append((None, dt))

    def _parse_date(self, arg: str) -> None:
        if self.date != datetime.datetime.now().date():
            raise UsageError("Multiple dates")

        midnight = datetime.datetime.combine(datetime.datetime.now(), datetime.time())
        parsed = dateparser.parse(arg, settings={'RELATIVE_BASE': midnight})

        if parsed is None:
            raise UsageError(f"Couldn't parse date {arg}")

        if parsed.time() != datetime.time():
            raise UsageError(f"Date {arg} contains unexpected time")

        self.date = parsed.date()

    def _parse_description(self, arg: str) -> None:
        if self._description:
            self._description += ' ' + arg
        else:
            self._description = arg

    def _parse_project(self, arg: str) -> None:
        self.project = arg

    def _parse_tag(self, arg: str) -> None:
        self.tags.append(arg)

    def _parse_workspace(self, arg: str) -> None:
        if self.workspace is not None:
            raise UsageError(f"Multiple workspaces: {self.workspace}, {arg}")
        self.workspace = arg

    def _parse_billable(self, arg: str) -> None:
        if arg:
            raise UsageError(f"Invalid billable arg {arg}")
        self._billable = True

    def parse(self, args: List[str] = None) -> None:
        parsed = self._parser.parse_args(args)
        self.debug = parsed.debug

        for arg in parsed.inputs:
            if ':' in arg and '-' in arg:
                self._parse_timespan(arg)
            elif arg[0] == '+':
                self._parse_tag(arg[1:])
            elif arg[0] == '@':
                self._parse_project(arg[1:])
            elif arg[0] == '$':
                self._parse_billable(arg[1:])
            elif arg[0] == '.':
                self._parse_date(arg[1:])
            elif arg[0] == '^':
                self._parse_workspace(arg[1:])
            elif arg[0] == '{':
                self._parse_start(arg[1:])
            elif arg[0] == '}':
                self._parse_stop(arg[1:])
            elif arg == 'start':
                self._parse_start('now')
            elif arg == 'stop':
                self._parse_stop('now')
            else:
                self._parse_description(arg)

        self.entries = [Entry(
            start=start_dt,
            end=end_dt,
            description=self._description,
            billable=self._billable,
            project=self.project,
        ) for (start_dt, end_dt) in self._timespans]

        has_new_entries = any(entry.start is not None for entry in self.entries)
        if not has_new_entries:
            if self._description:
                raise UsageError(f"Description {self._description} given without new entries")
            elif self._billable:
                raise UsageError("Billable given without new entries")
            elif self.project:
                raise UsageError(f"Project {self.project} given without new entries")
            elif self.tags:
                raise UsageError(f"Tags {self.tags} given without new entries")
            elif self.workspace:
                raise UsageError(f"Workspace {self.workspace} given without new entries")


class ClockifyClient:

    API_URL = 'https://api.clockify.me/api/v1'

    def __init__(self, debug: bool = False, workspace: str = None) -> None:
        self._debug = debug
        try:
            key = os.environ['CLOCKIFY_API_KEY']
        except KeyError as e:
            raise UsageError(f"{e} not defined in environment")

        if workspace is None:
            try:
                self._workspace_name = os.environ['CLOCKIFY_WORKSPACE']
            except KeyError as e:
                raise UsageError(f"{e} not defined in environment and "
                                  "'^workspace' not given")
        else:
            self._workspace_name = workspace

        self._headers = {'X-Api-Key': key}
        self._user_id = None
        self._workspace_id = None

        self._projects_by_name: Dict[str, str] = {}
        self._projects_by_id: Dict[str, str] = {}

        self._tags_by_name: Dict[str, str] = {}
        self._tags_by_id: Dict[str, str] = {}

    def _api_call(self, verb: str, path: str, **kwargs: Any) -> Any:
        if self._debug:
            rich.print(f'[u]{verb.upper()} {path}[/u]:', kwargs, '\n')

        func = getattr(requests, verb.lower())
        response = func(f'{self.API_URL}/{path}', headers=self._headers, **kwargs)
        if not response.ok:
            raise APIError(verb.upper(), path, response.status_code, response.json())

        r_data = response.json()
        if self._debug:
            rich.print(f'[u]Answer[/u]:', r_data, '\n')
        return r_data

    def _api_get(self, path: str, params: Dict[str, str] = None) -> Any:
        return self._api_call('get', path, params=params)

    def _api_post(self, path: str, data: Any) -> Any:
        return self._api_call('post', path, json=data)

    def _api_patch(self, path: str, data: Any) -> Any:
        return self._api_call('patch', path, json=data)

    def _fetch_workspace_id(self) -> None:
        workspaces = self._api_get('workspaces')
        for workspace in workspaces:
            if workspace['name'] == self._workspace_name:
                self._workspace_id = workspace['id']
                return
        raise UsageError(f'No workspace [yellow]{self._workspace_name}[/yellow] '
                          'found!')

    def _fetch_user_id(self) -> None:
        info = self._api_get('user')
        self._user_id = info['id']

    def _fetch_projects(self) -> None:
        projects = self._api_get(f'workspaces/{self._workspace_id}/projects')
        for proj in projects:
            self._projects_by_name[proj['name']] = proj
            self._projects_by_id[proj['id']] = proj

    def _fetch_tags(self) -> None:
        tags = self._api_get(f'workspaces/{self._workspace_id}/tags')
        for tag in tags:
            self._tags_by_name[tag['name']] = tag
            self._tags_by_id[tag['id']] = tag

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
                endpoint = f'workspaces/{self._workspace_id}/user/{self._user_id}/time-entries'
                r_data = self._api_patch(endpoint, data)
            else:
                # Adding a new entry
                endpoint = f'workspaces/{self._workspace_id}/time-entries'
                r_data = self._api_post(endpoint, data)

            # XXX Maybe do some sanity checks on the returned data?

            added_ids.add(r_data['id'])
        return added_ids

    def get_entries(self, date: datetime.date) -> Iterator[Entry]:
        endpoint = f'workspaces/{self._workspace_id}/user/{self._user_id}/time-entries'
        start = datetime.datetime.combine(date, datetime.time())
        end = start + datetime.timedelta(days=1)
        params = {
            'start': _to_iso_timestamp(start),
            'end': _to_iso_timestamp(end),
        }
        data = self._api_get(endpoint, params)
        for entry in data:
            yield Entry.deserialize(
                entry,
                projects=self._projects_by_id,
                tags=self._tags_by_id
            )

    def validate(self, *, tags: List[str], project: Optional[str]) -> None:
        for tag in tags:
            if tag not in self._tags_by_name:
                raise UsageError(f"Unknown tag {tag}")

        if project is not None and project not in self._projects_by_name:
            raise UsageError(f"Unknown project {project}")


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
                'end': _to_iso_timestamp(self.end),
            }

        data: Dict[str, Any] = {}

        data['start'] = _to_iso_timestamp(self.start)

        if self.end is not None:
            data['end'] = _to_iso_timestamp(self.end)

        if self.description is not None:
            data['description'] = self.description

        data['billable'] = self.billable

        if self.project is not None:
            data['projectId'] = projects[self.project]['id']

        if self.tags is not None:
            data['tagIds'] = [tags[tag]['id'] for tag in self.tags]

        return data

    @classmethod
    def deserialize(
            cls,
            data: Any, *,
            projects: Dict[str, Any],
            tags: Dict[str, Any]
    ) -> 'Entry':
        entry = cls(data['description'])

        entry.start = _from_iso_timestamp(data['timeInterval']['start'])

        if data['timeInterval']['end'] is not None:
            entry.end = _from_iso_timestamp(data['timeInterval']['end'])

        entry.description = data['description']
        entry.billable = data['billable']

        if data['projectId'] is not None:
            project = projects[data['projectId']]
            entry.project = project['name']
            entry.project_color = project['color']

        if data['tagIds'] is not None:
            for tag_id in data['tagIds']:
                entry.tags.append(tags[tag_id]['name'])

        entry.eid = data['id']

        return entry


def _from_iso_timestamp(timestamp: str) -> datetime.datetime:
    utc = dateutil.parser.isoparse(timestamp)
    return utc.astimezone(dateutil.tz.tzlocal())


def _to_iso_timestamp(dt: datetime.datetime) -> str:
    return dt.astimezone(dateutil.tz.UTC).isoformat().replace('+00:00', 'Z')


def print_entries(
        date: datetime.date,
        entries: Iterable[Entry],
        debug: bool,
        highlight_ids: AbstractSet[str] = frozenset(),
    ) -> None:
    console = rich.console.Console(highlight=False)

    table = rich.table.Table(title=f'Time entries for {date}', box=rich.box.ROUNDED)
    table.add_column("Description", style='yellow')
    table.add_column("Start", style='cyan')
    table.add_column("End", style='cyan')
    table.add_column("Project")
    table.add_column("Tags", style='blue')
    table.add_column(":gear:")  # icons

    for entry in reversed(list(entries)):
        if debug:
            console.print(entry, highlight=True)

        data = []

        data.append(entry.description)

        assert entry.start is not None, entry
        data.append(entry.start.strftime('%H:%M'))

        if entry.end is None:
            data.append(':clock3:')
        else:
            data.append(entry.end.strftime('%H:%M'))

        if entry.project is None:
            data.append('')
        else:
            data.append(f'[{entry.project_color}]{entry.project}[/{entry.project_color}]')

        data.append(', '.join(entry.tags))

        icon = ''
        if entry.eid in highlight_ids:
            icon += ':sparkles:'
        if entry.billable:
            icon += ':heavy_dollar_sign:'
        data.append(icon)

        style = None
        if highlight_ids and entry.eid not in highlight_ids:
            style = rich.style.Style(dim=True)

        table.add_row(*data, style=style)

    console.print(table)


def run() -> None:
    parser = ArgumentParser()
    parser.parse()

    client = ClockifyClient(debug=parser.debug, workspace=parser.workspace)
    client.fetch_info()

    if parser.entries:
        client.validate(tags=parser.tags, project=parser.project)
        added = client.add_entries(parser.date, parser.entries)
    else:
        added = set()

    entries = client.get_entries(parser.date)
    print_entries(parser.date, entries, debug=parser.debug, highlight_ids=added)


def main() -> int:
    try:
        run()
    except Error as e:
        console = rich.console.Console(file=sys.stderr, highlight=False)
        console.print(f'[red]Error:[/red] {e}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
