import sys
import warnings

import requests.exceptions
import rich.console

from cloclify import client, output, parser, utils


def configure_warnings() -> None:
    # WORKAROUND for https://github.com/scrapinghub/dateparser/issues/1013
    warnings.filterwarnings(
        "ignore",
        message="The localize method is no longer necessary, as this time zone supports the fold attribute",
    )


def run() -> None:
    configure_warnings()

    argparser = parser.ArgumentParser()
    argparser.parse()

    cliclient = client.ClockifyClient(
        debug=argparser.debug, workspace=argparser.workspace
    )
    try:
        cliclient.fetch_info()
    except requests.exceptions.ConnectionError as e:
        raise utils.Error(str(e))

    console = rich.console.Console(highlight=False)

    if argparser.dump:
        return output.dump(console, cliclient, argparser)
    elif argparser.conky:
        return output.conky(console, cliclient, argparser)

    if argparser.entries:
        cliclient.validate(tags=argparser.tags, project=argparser.project)
        added = cliclient.add_entries(argparser.date, argparser.entries)
    else:
        added = set()

    entries = cliclient.get_entries_day(argparser.date)
    output.print_header(console, cliclient, argparser)
    output.print_entries(
        console=console,
        title=argparser.date.strftime(output.DAY_TITLE_FORMAT),
        entries=entries,
        debug=argparser.debug,
        highlight_ids=added,
    )


def main() -> int:
    try:
        run()
    except utils.Error as e:
        console = rich.console.Console(file=sys.stderr, highlight=False)
        console.print(f"[red]Error:[/red] {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
