#!/usr/bin/python3

import os
import sys
import datetime

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


def parse_args(args):
    date = None
    timespans = []

    for arg in args:
        if ':' in arg and '-' in arg:
            # Looks like a timespan
            try:
                start_str, end_str = arg.split('-')
            except ValueError:
                raise UsageError(f"Couldn't parse timespan {arg} (too many '-')")
            start_time = datetime.datetime.strptime(start_str, '%H:%M').time()
            end_time = datetime.datetime.strptime(end_str, '%H:%M').time()
            timespans.append((start_time, end_time))
        elif arg[0] == '+':
            # Looks like a tag
            raise UsageError("Tags are not supported yet")
        else:
            # Anything else is parsed as (possibly relative) date
            if date is not None:
                raise UsageError("Multiple dates")

            midnight = datetime.datetime.combine(datetime.datetime.now(), datetime.time())
            parsed = dateparser.parse(arg, settings={'RELATIVE_BASE': midnight})

            if parsed is None:
                raise UsageError(f"Couldn't parse date {arg}")

            if parsed.time() != datetime.time():
                raise UsageError(f"Date {arg} contains unexpected time")

            date = parsed.date()

    if date is None:
        date = datetime.datetime.today()

    return date, timespans


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
        raise UsageError("Not implemented yet")

    def get_entries(self, date):
        endpoint = f'workspaces/{self._workspace_id}/user/{self._user_id}/time-entries'
        start = datetime.datetime.combine(date, datetime.time())
        end = start + datetime.timedelta(days=1)
        params = {
            'start': start.isoformat() + 'Z',
            'end': end.isoformat() + 'Z',
        }
        return self._api_get(endpoint, params)


def _parse_iso_timestamp(timestamp):
    utc = dateutil.parser.isoparse(timestamp)
    return utc.astimezone(dateutil.tz.tzlocal())


def print_entries(date, entries):
    console = rich.console.Console(highlight=False)
    table = rich.table.Table(title=f'Time entries for {date}', box=rich.box.ROUNDED)

    table.add_column("Start", style='cyan')
    table.add_column("End", style='cyan')
    table.add_column("Description", style='yellow')

    for entry in entries:
        start = _parse_iso_timestamp(entry['timeInterval']['start'])
        end = _parse_iso_timestamp(entry['timeInterval']['end'])
        description = entry['description']
        table.add_row(start.strftime('%H:%M'), end.strftime('%H:%M'), description)

    console.print(table)


def run():
    date, timespans = parse_args(sys.argv[1:])

    client = ClockifyClient()
    client.fetch_info()

    if timespans:
        client.add_timespans(date, timespans)

    entries = client.get_entries(date)
    print_entries(date, reversed(entries))


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
