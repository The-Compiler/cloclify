import contextlib
import datetime
import itertools
import collections
from typing import AbstractSet, Iterable

import dateutil
import rich.align
import rich.box
import rich.console
import rich.padding
import rich.panel
import rich.rule
import rich.table

from cloclify import client


def timedelta_str(delta):
    h, rem = divmod(delta.seconds, 3600)
    m, s = divmod(rem, 60)
    dec = h + m / 60
    prefix = f"{delta.days} days, " if delta.days != 0 else ""
    return f"{prefix}{h:02}:{m:02}:{s:02} ({round(dec, 2)})"


def print_entries(
    console: rich.console.Console,
    date: datetime.date,
    entries: Iterable[client.Entry],
    *,
    debug: bool,
    highlight_ids: AbstractSet[str] = frozenset(),
    center: bool = False,
) -> None:
    date_str = date.strftime("%a, %Y-%m-%d")
    table = rich.table.Table(
        title=date_str,
        box=rich.box.ROUNDED,
    )
    table.add_column("Description", style="yellow")
    table.add_column("Start", style="cyan")
    table.add_column("End", style="cyan")
    table.add_column("Project")
    table.add_column("Tags", style="blue")
    table.add_column(":gear:")  # icons

    total = datetime.timedelta()
    project_totals = collections.defaultdict(datetime.timedelta)

    for entry in reversed(list(entries)):
        if debug:
            console.print(entry, highlight=True)

        data = []

        data.append(entry.description)

        assert entry.start is not None, entry
        data.append(entry.start.strftime("%H:%M"))

        if entry.end is None:
            data.append(":clock3:")
            now = datetime.datetime.now(dateutil.tz.tzlocal())
            duration = now - entry.start
        else:
            data.append(entry.end.strftime("%H:%M"))
            duration = entry.end - entry.start

        total += duration
        proj_key = (entry.project or "Other", entry.project_color or "default")
        project_totals[proj_key] += duration

        if entry.project is None:
            data.append("")
        else:
            data.append(f"[{entry.project_color}]{entry.project}[/{entry.project_color}]")

        data.append(", ".join(entry.tags))

        icon = ""
        if entry.eid in highlight_ids:
            icon += ":sparkles:"
        if entry.billable:
            icon += ":heavy_dollar_sign:"
        data.append(icon)

        style = None
        if highlight_ids and entry.eid not in highlight_ids:
            style = rich.style.Style(dim=True)

        table.add_row(*data, style=style)

    renderable = rich.align.Align(table, "center") if center else table
    console.print(renderable)

    justify = "center" if center else None
    console.print(f"[b]Total: {timedelta_str(total)}[/b]", justify=justify)
    for (proj, color), tag_total in sorted(project_totals.items()):
        console.print(
            f"[{color}]{proj}[/{color}]: {timedelta_str(tag_total)}",
            justify=justify,
        )


def dump(console, client, parser) -> None:
    """Dump all entries for the month given in 'date'."""
    entries = client.get_entries_month(parser.dump)

    separator = rich.padding.Padding(rich.rule.Rule(), (1, 0))

    pager = console.pager(styles=True) if parser.pager else contextlib.nullcontext()

    with pager:
        for date, day_entries in itertools.groupby(
            reversed(list(entries)), key=lambda e: e.start.date()
        ):
            print_entries(
                console,
                date,
                reversed(list(day_entries)),
                debug=parser.debug,
                center=True,
            )
            console.print(separator)
