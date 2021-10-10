import argparse
import datetime
import re
from typing import List, Optional, Tuple

import dateparser

from cloclify import client, utils

Timespan = Tuple[Optional[datetime.time], Optional[datetime.time]]


class ArgumentParser:

    """Arguments are parsed based on how they look:

    HH:MM-HH:MM    Add a new time entry based on the given times.

    HH:MM-/        "Clock in" at the given time.
    /-HH:MM        "Clock out" at the given time.

    now-/          Clock in now
    start          (convenience alias)

    /-now          Clock out now
    end            (convenience alias)

    +tag           Add the given tag to all specified time entries.
    @project       Set the given project for all specified time entries.
    $              Mark all specified time entries as billable.
    ^workspace     Add all entries to the given workspace.
                   (If not given, the current workspace or CLOCKIFY_WORKSPACE envvar is used)

    .date          Show/edit time entries for the given date.
                   Can be relative (".yesterday", ".5 days ago") or absolute
                   (".2020-10-01"). Make sure to quote spaces.

    description    Any arguments without a prefix are parsed as description.
                   Quoting is optional, as multiple arguments will be space-joined.

    Examples:

    $ cloclify start @qutebrowser issue1234   # Start working on a project
    $ cloclify stop                           # Take a break

    $ cloclify 12:30-/ @qutebrowser issue1235  # Retroactively start "stopwatch mode"
    $ cloclify /-17:00                         # Retroactively stop working

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
        self.entries: List[client.Entry] = []
        self.debug: bool = False
        self.dump: Optional[datetime.date] = None
        self.pager: bool = True
        self.tags: List[str] = []
        self.project: Optional[str] = None
        self.workspace: Optional[str] = None

        self._parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=self.__doc__,
        )
        self._parser.add_argument(
            "inputs",
            help="An argument like described above.",
            metavar="input",
            nargs="*",
        )
        self._parser.add_argument(
            "--debug", help="Enable debug output", action="store_true"
        )
        self._parser.add_argument(
            "--dump", help="Dump an entire month", action="store", metavar="YYYY-MM"
        )
        self._parser.add_argument(
            "--no-pager", help="Disable pager for --dump", action="store_true"
        )
        self._parser.add_argument(
            "--conky", help="Output a string for conky's execpi", action="store_true"
        )

    def _combine_date(
        self, time: Optional[datetime.time]
    ) -> Optional[datetime.datetime]:
        """Combine the given timestamp with the saved date."""
        if time is None:
            return None
        return datetime.datetime.combine(self.date, time)

    def _parse_time(self, time_str: str) -> datetime.time:
        if time_str == "now":
            now = datetime.datetime.now()
            if self.date != now.date():
                raise utils.UsageError("Can't combine 'now' with different date")
            return now.time()
        elif time_str == "/":
            return None

        try:
            return datetime.datetime.strptime(time_str, "%H:%M").time()
        except ValueError as e:
            raise utils.UsageError(str(e))

    def _parse_timespan(self, arg: str) -> None:
        try:
            start_str, end_str = arg.split("-")
        except ValueError:
            raise utils.UsageError(f"Couldn't parse timespan {arg} (too many '-')")

        start_time = self._parse_time(start_str)
        end_time = self._parse_time(end_str)

        if start_time is None and end_time is None:
            raise utils.UsageError("Either start or end time needs to be given")

        self._timespans.append((start_time, end_time))

    def _parse_date(self, arg: str) -> None:
        if self.date != datetime.datetime.now().date():
            raise utils.UsageError("Multiple dates")

        midnight = datetime.datetime.combine(datetime.datetime.now(), datetime.time())
        parsed = dateparser.parse(arg, settings={"RELATIVE_BASE": midnight})

        if parsed is None:
            raise utils.UsageError(f"Couldn't parse date {arg}")

        if parsed.time() != datetime.time():
            raise utils.UsageError(f"Date {arg} contains unexpected time")

        self.date = parsed.date()

    def _parse_description(self, arg: str) -> None:
        if self._description:
            self._description += " " + arg
        else:
            self._description = arg

    def _parse_project(self, arg: str) -> None:
        self.project = arg

    def _parse_tag(self, arg: str) -> None:
        self.tags.append(arg)

    def _parse_workspace(self, arg: str) -> None:
        if self.workspace is not None:
            raise utils.UsageError(f"Multiple workspaces: {self.workspace}, {arg}")
        self.workspace = arg

    def _parse_billable(self, arg: str) -> None:
        if arg:
            raise utils.UsageError(f"Invalid billable arg {arg}")
        self._billable = True

    def parse(self, args: List[str] = None) -> None:
        parsed = self._parser.parse_args(args)
        self.debug = parsed.debug
        self.pager = not parsed.no_pager
        self.conky = parsed.conky

        time_pattern = r"(\d\d?:\d\d?|/|now)"
        timespan_re = re.compile(f"{time_pattern}-{time_pattern}")

        for arg in parsed.inputs:
            if timespan_re.fullmatch(arg):
                self._parse_timespan(arg)
            elif arg[0] == "+":
                self._parse_tag(arg[1:])
            elif arg[0] == "@":
                self._parse_project(arg[1:])
            elif arg[0] == "$":
                self._parse_billable(arg[1:])
            elif arg[0] == ".":
                self._parse_date(arg[1:])
            elif arg[0] == "^":
                self._parse_workspace(arg[1:])
            elif arg == "start":
                self._parse_timespan("now-/")
            elif arg == "stop":
                self._parse_timespan("/-now")
            else:
                self._parse_description(arg)

        self.entries = [
            client.Entry(
                start=self._combine_date(start_time),
                end=self._combine_date(end_time),
                description=self._description,
                billable=self._billable,
                project=self.project,
            )
            for (start_time, end_time) in self._timespans
        ]

        if parsed.dump:
            try:
                self.dump = datetime.datetime.strptime(parsed.dump, "%Y-%m")
            except ValueError:
                raise utils.UsageError(f"Unparseable month {parsed.dump} (use YYYY-MM)")

        has_new_entries = any(entry.start is not None for entry in self.entries)
        if not has_new_entries:
            if self._description:
                raise utils.UsageError(
                    f"Description {self._description} given without new entries"
                )
            elif self._billable:
                raise utils.UsageError("Billable given without new entries")
            elif self.project:
                raise utils.UsageError(f"Project {self.project} given without new entries")
            elif self.tags:
                raise utils.UsageError(f"Tags {self.tags} given without new entries")

        if parsed.dump and self.date != datetime.datetime.now().date():
            raise utils.UsageError(f"Date {self.date} given with --dump")
