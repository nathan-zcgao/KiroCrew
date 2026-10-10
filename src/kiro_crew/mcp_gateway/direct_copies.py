"""Measure what the per-session copies of an MCP server cost right now.

The MCP page offers to share a server and says what that saves. The number has
to be a measurement of THIS host, never an estimate: it is read from the process
table, and when nothing can be read the page shows no number at all.

A copy is a process that runs one of the server's declared launches -- its
absolute command as ``argv[0]`` (or ``argv[1]``, for a script run by an
interpreter) followed by that launch's declared args -- together with every
process below it. The args are part of the match because one binary often
serves several servers under different subcommands. Bare command names
(``npx``, ``node``) are not matched: they name every process of that program,
not this server's copies, so counting them would report memory the server does
not use.

Linux only (``/proc``). Elsewhere, and on any read failure, a server simply has
no measurement. Standard library only; BLOCKING, so call it off the event loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

#: The marker every gateway-side helper carries in its argv. A stub or the
#: shared daemon is never a per-session copy of the server it fronts.
_GATEWAY_MODULE_MARKER = "kiro_crew.mcp_gateway"


@dataclass(frozen=True)
class DirectCopies:
    """The per-session copies of one server running now."""

    copies: int
    rss_bytes: int

    @property
    def saves_bytes(self) -> int | None:
        """What one shared copy would save, from the measured copies.

        Sharing leaves one copy running, so the saving is everything except one
        average copy. ``None`` when fewer than two copies run: there is nothing
        to save, and a number would claim otherwise.
        """
        if self.copies < 2 or self.rss_bytes <= 0:
            return None
        return self.rss_bytes - self.rss_bytes // self.copies


def _read_cmdline(proc_root: Path, pid: int) -> list[str]:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [os.fsdecode(part) for part in raw.split(b"\0") if part]


def _read_ppid(proc_root: Path, pid: int) -> int | None:
    try:
        stat = (proc_root / str(pid) / "stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    # ``comm`` is parenthesised and may contain spaces or ``)``; the fields
    # after the LAST ``)`` are fixed: state, then ppid.
    tail = stat.rpartition(")")[2].split()
    try:
        return int(tail[1])
    except (IndexError, ValueError):
        return None


def _read_rss(proc_root: Path, pid: int, page_size: int) -> int:
    try:
        fields = (proc_root / str(pid) / "statm").read_text(encoding="ascii").split()
        return int(fields[1]) * page_size
    except (OSError, ValueError, IndexError):
        return 0


def _matches(argv: list[str], launches: frozenset[tuple[str, ...]]) -> bool:
    """Whether *argv* runs one of *launches*: its command, then its declared args.

    The args matter: one binary often serves several servers under different
    subcommands, and matching the command alone would count all of them.
    """
    if not argv or any(_GATEWAY_MODULE_MARKER in part for part in argv):
        return False
    for start in (0, 1):
        if len(argv) <= start:
            break
        for command, *args in launches:
            if argv[start] == command and argv[start + 1 : start + 1 + len(args)] == args:
                return True
    return False


def measure(
    launches_by_server: Mapping[str, Iterable[Sequence[str] | str]],
    *,
    proc_root: Path = Path("/proc"),
    page_size: int | None = None,
) -> dict[str, DirectCopies]:
    """``{server: DirectCopies}`` for every server with at least one copy running.

    *launches_by_server* maps a server name to the launches its specs declare,
    each ``(command, *args)`` (a bare string is a command with no args). Only
    absolute commands are matched. A server absent from the result has no
    measurement -- not "zero copies", which this cannot tell apart from "not
    readable".
    """
    wanted: dict[str, frozenset[tuple[str, ...]]] = {}
    for server, launches in launches_by_server.items():
        found: set[tuple[str, ...]] = set()
        for launch in launches:
            parts = (launch,) if isinstance(launch, str) else tuple(str(p) for p in launch)
            if not parts or not os.path.isabs(parts[0]):
                continue
            found.add(parts)
            found.add((os.path.realpath(parts[0]), *parts[1:]))
        if found:
            wanted[server] = frozenset(found)
    if not wanted or not proc_root.is_dir():
        return {}
    if page_size is None:
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
        except (AttributeError, OSError, ValueError):
            return {}
    try:
        pids = [int(entry.name) for entry in proc_root.iterdir() if entry.name.isdigit()]
    except OSError:
        return {}

    argv_of = {pid: _read_cmdline(proc_root, pid) for pid in pids}
    parent_of = {pid: _read_ppid(proc_root, pid) for pid in pids}
    children: dict[int, list[int]] = {}
    for pid, ppid in parent_of.items():
        if ppid is not None:
            children.setdefault(ppid, []).append(pid)

    def _subtree_rss(root: int) -> int:
        total = 0
        stack = [root]
        seen: set[int] = set()
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            total += _read_rss(proc_root, pid, page_size)
            stack.extend(children.get(pid, ()))
        return total

    out: dict[str, DirectCopies] = {}
    for server, commands in wanted.items():
        roots = [pid for pid in pids if _matches(argv_of[pid], commands)]
        root_set = set(roots)
        # A copy that forks a child running the same command is ONE copy.
        roots = [pid for pid in roots if parent_of.get(pid) not in root_set]
        if not roots:
            continue
        out[server] = DirectCopies(len(roots), sum(_subtree_rss(pid) for pid in roots))
    return out
