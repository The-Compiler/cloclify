#!/usr/bin/python3

import os
import sys
import datetime
import argparse

import requests
import dateparser
import dateutil.parser
import dateutil.tz
import rich.console
import rich.table
import rich.box


class Error(Exception):
    pass


class UsageError(Error):
    pass


class APIError(Error):

    def __init__(self, method, path, status, data):
        super().__init__(f'API {method} to {path} failed with {status}: {data}')


class ArgumentParser:

    def __init__(self):
        self.date = None
        self.timespans = []
        self.debug = None

        self._parser = argparse.ArgumentParser()
        self._parser.add_argument('inputs', help='A date or time range', nargs='*')
        self._parser.add_argument('--debug', help='Enable debug output', action='store_true')

    def _parse_timespan(self, arg):
        try:
            start_str, end_str = arg.split('-')
        except ValueError:
            raise UsageError(f"Couldn't parse timespan {arg} (too many '-')")
        start_time = datetime.datetime.strptime(start_str, '%H:%M').time()
        end_time = datetime.datetime.strptime(end_str, '%H:%M').time()
        self.timespans.append((start_time, end_time))

    def _parse_date(self, arg):
        if self.date is not None:
            raise UsageError("Multiple dates")

        midnight = datetime.datetime.combine(datetime.datetime.now(), datetime.time())
        parsed = dateparser.parse(arg, settings={'RELATIVE_BASE': midnight})

        if parsed is None:
            raise UsageError(f"Couldn't parse date {arg}")

        if parsed.time() != datetime.time():
            raise UsageError(f"Date {arg} contains unexpected time")

        self.date = parsed.date()

    def _parse_description(self, arg):
        raise UsageError("Descriptions are not supported yet")

    def _parse_project(self, arg):
        raise UsageError("Projects are not supported yet")

    def _parse_tag(self, arg):
        raise UsageError("Tags are not supported yet")

    def _parse_billable(self, arg):
        raise UsageError("Billable is not supported yet")

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
            elif arg == '$':
                self._parse_billable()
            elif arg == '.':
                self._parse_date(arg[1:])
            else:
                self._parse_description(arg)

        if self.date is None:
            self.date = datetime.datetime.today().date()


class ClockifyClient:

    API_URL = 'https://api.clockify.me/api/v1'

    def __init__(self):
        try:
            key = os.environ['CLOCKIFY_API_KEY']
            self._workspace_name = os.environ['CLOCKIFY_WORKSPACE']
        except KeyError as e:
            raise UsageError(f"{e} not defined in environment")

        self._headers = {'X-Api-Key': key}
        self._user_id = None
        self._workspace_id = None

    def _api_get(self, path, params=None):
        response = requests.get(f'{self.API_URL}/{path}', headers=self._headers, params=params)
        if not response.ok:
            raise APIError('GET', path, response.status_code, response.json())
        return response.json()

    def _api_post(self, path, data):
        response = requests.post(f'{self.API_URL}/{path}', headers=self._headers, json=data)
        if not response.ok:
            raise APIError('POST', path, response.status_code, response.json())
        return response.json()

    def _fetch_workspace_id(self):
        workspaces = self._api_get('workspaces')
        for workspace in workspaces:
            if workspace['name'] == self._workspace_name:
                return workspace['id']
        raise UsageError(f'No workspace {name} found!')

    def _fetch_user_id(self):
        info = self._api_get('user')
        return info['id']

    def fetch_info(self):
        self._workspace_id = self._fetch_workspace_id()
        self._user_id = self._fetch_user_id()

    def add_timespans(self, date, timespans):
        raise UsageError("Adding timespans is not implemented yet")

    def get_entries(self, date):
        endpoint = f'workspaces/{self._workspace_id}/user/{self._user_id}/time-entries'
        start = datetime.datetime.combine(date, datetime.time())
        end = start + datetime.timedelta(days=1)
        params = {
            'start': start.isoformat() + 'Z',
            'end': end.isoformat() + 'Z',
            'hydrated': True,  # request full project/tag/task entries
        }
        return self._api_get(endpoint, params)


def _parse_iso_timestamp(timestamp):
    utc = dateutil.parser.isoparse(timestamp)
    return utc.astimezone(dateutil.tz.tzlocal())


def print_entries(date, entries, debug):
    console = rich.console.Console(highlight=False)
    table = rich.table.Table(title=f'Time entries for {date}', box=rich.box.ROUNDED)

    table.add_column("Description", style='yellow')
    table.add_column("Start", style='cyan')
    table.add_column("End", style='cyan')
    table.add_column("Project")
    table.add_column("Tags", style='blue')
    table.add_column("$", style='green')

    for entry in entries:
        if debug:
            console.print(entry, highlight=True)

        data = []

        description = entry['description']
        data.append(description)

        start = _parse_iso_timestamp(entry['timeInterval']['start'])
        data.append(start.strftime('%H:%M'))

        end = entry['timeInterval']['end']
        if end is None:
            data.append(':clock3:')
        else:
            data.append(_parse_iso_timestamp(end).strftime('%H:%M'))

        if entry['project'] is None:
            data.append('')
        else:
            proj_name = entry['project']['name']
            proj_color = entry['project']['color']
            data.append(f'[{proj_color}]{proj_name}[/{proj_color}]')

        tags = ', '.join(tag['name'] for tag in entry['tags'])
        data.append(tags)

        billable = ':dollar:' if entry['billable'] else ''
        data.append(billable)

        table.add_row(*data)

    console.print(table)


def run():
    parser = ArgumentParser()
    parser.parse()

    client = ClockifyClient()
    client.fetch_info()

    if parser.timespans:
        client.add_timespans(parser.date, parser.timespans)

    entries = client.get_entries(parser.date)
    print_entries(parser.date, reversed(entries), debug=parser.debug)


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
