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


DAY_TITLE_FORMAT = "%a, %Y-%m-%d (week %W)"


def timedelta_str(delta):
    h, rem = divmod(delta.seconds, 3600)
    m, s = divmod(rem, 60)
    dec = h + m / 60
    prefix = f"{delta.days} days, " if delta.days != 0 else ""
    return f"{prefix}{h:02}:{m:02}:{s:02} ({round(dec, 2)})"


def print_entries(
    *,
    console: rich.console.Console,
    title: str,
    entries: Iterable[client.Entry],
    debug: bool,
    highlight_ids: AbstractSet[str] = frozenset(),
    center: bool = False,
    only_totals: bool = False,
) -> None:
    table = rich.table.Table(
        title=title,
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

    if not only_totals:
        renderable = rich.align.Align(table, "center") if center else table
        console.print(renderable)

    justify = "center" if center else None
    grid = rich.table.Table.grid()
    grid.add_column()
    grid.add_column()
    grid.add_row("Total: ", timedelta_str(total), style="bold")
    for (proj, color), tag_total in sorted(project_totals.items()):
        grid.add_row(f"[{color}]{proj}[/{color}]: ", timedelta_str(tag_total))
    console.print(grid, justify=justify)


def conky(console, client, parser) -> None:
    """Output for conky's exec(i) with lemonbar."""
    entries = list(client.get_entries_day(parser.date))
    running = [e for e in entries if e.end is None]

    parts = []
    if running:
        for entry in running:
            project = entry.project or "Other"
            color = entry.project_color or "#fffff"
            parts.append('%{F' + color + '}' + project + '%{F-}')

    finished_count = len(entries) - len(running)
    now = datetime.datetime.now()

    if finished_count:
        if parts:
            parts.append("+")
        parts.append(str(finished_count))
    elif running:
        # don't need to append "none" if a task is running
        pass
    elif 0 <= now.date().weekday() < 5 and 8 <= now.time().hour <= 18:
        # roughly working hours
        parts.append("%{B<color>} none %{B-}".replace('<color>', parser.conky_error_color))
    else:
        # roughly non-working hours
        parts.append("none")

    console.print(' '.join(parts))


def print_header(console, client, parser) -> None:
    """Print an overview of configured filters."""
    grid = rich.table.Table.grid()
    grid.add_column()
    grid.add_column()
    grid.add_row("[yellow]Workspace: [/yellow]", client.workspace_name)
    if parser.project is not None:
        # FIXME get project color?
        grid.add_row("[cyan]Project: [/cyan]", parser.project)
    if parser.tags:
        grid.add_row("[blue]Tags: [/blue]", ', '.join(parser.tags))

    separator = rich.padding.Padding(rich.rule.Rule(), (0, 0, 1, 0))
    console.print(grid)
    console.print(separator)


def dump(console, client, parser) -> None:
    """Dump all entries for the month given in 'date'."""
    separator = rich.padding.Padding(rich.rule.Rule(), (1, 0))
    pager = console.pager(styles=True) if parser.pager else contextlib.nullcontext()

    if parser.dump_mode == parser.DumpMode.YEAR:
        entries = client.get_entries_year(parser.dump)
    elif parser.dump_mode == parser.DumpMode.MONTH:
        entries = client.get_entries_month(parser.dump)
    else:
        assert False  # unreachable

    filtered = [
        entry for entry in entries
        if (parser.project is None or entry.project == parser.project) and
        (not parser.tags or set(parser.tags).issubset(entry.tags))
    ]

    with pager:
        print_header(console, client, parser)
        for date, day_entries in itertools.groupby(
            reversed(filtered),
            key=lambda e: e.start.date()
        ):
            print_entries(
                console=console,
                title=date.strftime(DAY_TITLE_FORMAT),
                entries=reversed(list(day_entries)),
                debug=parser.debug,
                center=True,
            )
            console.print(separator)

        # FIXME this feels a bit hackish - can we split print_entries?
        print_entries(
            console=console,
            title="",
            entries=filtered,
            debug=False,
            only_totals=True,
            center=True,
        )
