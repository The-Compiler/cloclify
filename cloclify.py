#!/usr/bin/python3

import os
import sys
import datetime
import argparse
import dataclasses
from typing import List

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

    def __init__(self, method, path, status, data):
        super().__init__(f'API {method} to {path} failed with {status}: {data}')


class ArgumentParser:

    def __init__(self):
        self._timespans = []
        self._description = ""
        self._billable = False

        self.date = datetime.datetime.now().date()
        self.entries = []
        self.debug = None
        self.tags = []
        self.project = None

        self._parser = argparse.ArgumentParser()
        self._parser.add_argument(
            'inputs',
            help='A date, time entry, or meta-information for all added entries',
            metavar='HH:MM-HH:MM|+tag|@project|$|.date|description',
            nargs='*')
        self._parser.add_argument('--debug', help='Enable debug output', action='store_true')

    def _parse_timespan(self, arg):
        try:
            start_str, end_str = arg.split('-')
        except ValueError:
            raise UsageError(f"Couldn't parse timespan {arg} (too many '-')")

        start_time = datetime.datetime.strptime(start_str, '%H:%M').time()
        end_time = datetime.datetime.strptime(end_str, '%H:%M').time()

        start_dt = datetime.datetime.combine(self.date, start_time)
        end_dt = datetime.datetime.combine(self.date, end_time)

        self._timespans.append((start_dt, end_dt))

    def _parse_date(self, arg):
        if self.date != datetime.datetime.now().date():
            raise UsageError("Multiple dates")

        midnight = datetime.datetime.combine(datetime.datetime.now(), datetime.time())
        parsed = dateparser.parse(arg, settings={'RELATIVE_BASE': midnight})

        if parsed is None:
            raise UsageError(f"Couldn't parse date {arg}")

        if parsed.time() != datetime.time():
            raise UsageError(f"Date {arg} contains unexpected time")

        self.date = parsed.date()

    def _parse_description(self, arg):
        if self._description:
            self._description += ' ' + arg
        else:
            self._description = arg

    def _parse_project(self, arg):
        self.project = arg

    def _parse_tag(self, arg):
        self.tags.append(arg)

    def _parse_billable(self, arg):
        if arg:
            raise UsageError(f"Invalid billable arg {arg}")
        self._billable = True

    def parse(self, args=None):
        parsed = self._parser.parse_args(args)
        self.debug = parsed.debug

        for arg in parsed.inputs:
            if ':' in arg and '-' in arg:
                self._parse_timespan(arg)
            elif arg[0] == '+':
                self._parse_tag(arg[1:])
            elif arg[0] == '@':
                self._parse_project(arg[1:])
            elif arg[0]  == '$':
                self._parse_billable(arg[1:])
            elif arg[0] == '.':
                self._parse_date(arg[1:])
            else:
                self._parse_description(arg)

        self.entries = [Entry(
            start=start_dt,
            end=end_dt,
            description=self._description,
            billable=self._billable,
            project=self.project,
            tags=self.tags,
        ) for (start_dt, end_dt) in self._timespans]


class ClockifyClient:

    API_URL = 'https://api.clockify.me/api/v1'

    def __init__(self, debug=False):
        self._debug = debug
        try:
            key = os.environ['CLOCKIFY_API_KEY']
            self._workspace_name = os.environ['CLOCKIFY_WORKSPACE']
        except KeyError as e:
            raise UsageError(f"{e} not defined in environment")

        self._headers = {'X-Api-Key': key}
        self._user_id = None
        self._workspace_id = None

        self._projects_by_name = {}
        self._projects_by_id = {}

        self._tags_by_name = {}
        self._tags_by_id = {}

    def _api_get(self, path, params=None):
        if self._debug:
            rich.print(f'[u]GET from {path}[/u]:', params, '\n')

        response = requests.get(f'{self.API_URL}/{path}', headers=self._headers, params=params)
        if not response.ok:
            raise APIError('GET', path, response.status_code, response.json())

        r_data = response.json()
        if self._debug:
            rich.print(f'[u]Answer[/u]:', r_data, '\n')
        return r_data

    def _api_post(self, path, data):
        if self._debug:
            rich.print(f'[u]POST to {path}[/u]:', data)

        response = requests.post(f'{self.API_URL}/{path}', headers=self._headers, json=data)
        if not response.ok:
            raise APIError('POST', path, response.status_code, response.json())

        r_data = response.json()
        if self._debug:
            rich.print(f'[u]Answer[/u]:', r_data, '\n')
        return r_data

    def _fetch_workspace_id(self):
        workspaces = self._api_get('workspaces')
        for workspace in workspaces:
            if workspace['name'] == self._workspace_name:
                self._workspace_id = workspace['id']
                return
        raise UsageError(f'No workspace {name} found!')

    def _fetch_user_id(self):
        info = self._api_get('user')
        self._user_id = info['id']

    def _fetch_projects(self):
        projects = self._api_get(f'workspaces/{self._workspace_id}/projects')
        for proj in projects:
            self._projects_by_name[proj['name']] = proj
            self._projects_by_id[proj['id']] = proj

    def _fetch_tags(self):
        tags = self._api_get(f'workspaces/{self._workspace_id}/tags')
        for tag in tags:
            self._tags_by_name[tag['name']] = tag
            self._tags_by_id[tag['id']] = tag

    def fetch_info(self):
        self._fetch_workspace_id()
        self._fetch_user_id()
        self._fetch_projects()
        self._fetch_tags()

    def add_entries(self, date, entries):
        endpoint = f'workspaces/{self._workspace_id}/time-entries'
        added_ids = set()
        for entry in entries:
            data = entry.serialize(
                projects=self._projects_by_name,
                tags=self._tags_by_name,
            )
            r_data = self._api_post(endpoint, data)
            # XXX Maybe do some sanity checks on the returned data?
            added_ids.add(r_data['id'])
        return added_ids

    def get_entries(self, date):
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

    def validate(self, *, tags, project):
        for tag in tags:
            if tag not in self._tags_by_name:
                raise UsageError(f"Unknown tag {tag}")

        if project is not None and project not in self._projects_by_name:
            raise UsageError(f"Unknown project {project}")


@dataclasses.dataclass
class Entry:

    start: datetime.datetime
    end: datetime.datetime = None
    description: str = None
    billable: bool = False
    project: str = None
    project_color: str = None
    tags: List[str] = dataclasses.field(default_factory=list)
    eid: str = None

    def serialize(self, *, projects, tags):
        data = {
            'start': _to_iso_timestamp(self.start),
        }

        if self.end is not None:
            data['end'] = _to_iso_timestamp(self.end)

        if self.description is not None:
            data['description'] = self.description

        if self.billable:
            data['billable'] = True

        if self.project is not None:
            data['projectId'] = projects[self.project]['id']

        if self.tags is not None:
            data['tagIds'] = [tags[tag]['id'] for tag in self.tags]

        return data

    @classmethod
    def deserialize(cls, data, *, projects, tags):
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


def _from_iso_timestamp(timestamp):
    utc = dateutil.parser.isoparse(timestamp)
    return utc.astimezone(dateutil.tz.tzlocal())


def _to_iso_timestamp(dt):
    return dt.astimezone(dateutil.tz.UTC).isoformat().replace('+00:00', 'Z')


def print_entries(date, entries, debug, highlight_ids=frozenset()):
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


def run():
    parser = ArgumentParser()
    parser.parse()

    client = ClockifyClient(debug=parser.debug)
    client.fetch_info()

    if parser.entries:
        client.validate(tags=parser.tags, project=parser.project)
        added = client.add_entries(parser.date, parser.entries)
    else:
        added = set()

    entries = client.get_entries(parser.date)
    print_entries(parser.date, entries, debug=parser.debug, highlight_ids=added)


def main():
    try:
        run()
    except Error as e:
        console = rich.console.Console(file=sys.stderr, highlight=False)
        console.print(f'[red]Error:[/red] {e}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
