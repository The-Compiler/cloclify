import os
import sys

import rich.console

from cloclify.parser import ArgumentParser
from cloclify.client import ClockifyClient
from cloclify.utils import Error
from cloclify.output import dump, print_entries

def run() -> None:
    parser = ArgumentParser()
    parser.parse()

    client = ClockifyClient(debug=parser.debug, workspace=parser.workspace)
    client.fetch_info()

    console = rich.console.Console(highlight=False)

    if parser.dump:
        return dump(console, client, parser)

    if parser.entries:
        client.validate(tags=parser.tags, project=parser.project)
        added = client.add_entries(parser.date, parser.entries)
    else:
        added = set()

    entries = client.get_entries_day(parser.date)
    print_entries(
        console, parser.date, entries, debug=parser.debug, highlight_ids=added
    )


def main() -> int:
    try:
        run()
    except Error as e:
        console = rich.console.Console(file=sys.stderr, highlight=False)
        console.print(f"[red]Error:[/red] {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
