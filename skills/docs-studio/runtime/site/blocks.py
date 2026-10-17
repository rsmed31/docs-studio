"""Visual building blocks for the docs site: icons, card grids, steppers, bars, timelines, kanban
boards. Diagram presets (flow, sequence, zones, charts ...) live in the `presets` package.

Pure functions: each takes the directive body (lines) and an `inline` callable that renders
inline Markdown, and returns an HTML string. build.py wraps the result so the Edit mode can
copy the original Markdown back out. Standard library only.
"""
from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import Any

Inline = Callable[[str], str]

# --------------------------------------------------------------------------- #
# Icons (24x24, stroke only; they take the surrounding text colour)             #
# --------------------------------------------------------------------------- #
_I = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5"/>',
    "pen": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "check": '<path d="M22 11.1V12a10 10 0 1 1-5.9-9.1"/><path d="M22 4L12 14l-3-3"/>',
    "refresh": '<path d="M23 4v6h-6"/><path d="M20.5 15a9 9 0 1 1-2.1-9.4L23 10"/>',
    "layers": '<path d="M12 2L2 7l10 5 10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',
    "mic": '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v4M8 23h8"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
    "send": '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
    "compass": '<circle cx="12" cy="12" r="10"/><path d="M16.2 7.8l-2.1 6.3-6.3 2.1 2.1-6.3z"/>',
    "tool": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z"/>',
    "film": '<rect x="2" y="2" width="20" height="20" rx="2.2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "video": '<path d="M23 7l-7 5 7 5z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "dollar": '<path d="M12 1v22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "cpu": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
    "server": '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "cloud": '<path d="M18 10h-1.3A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>',
    "type": '<path d="M4 7V4h16v3M9 20h6M12 4v16"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "play": '<path d="M5 3l14 9-14 9z"/>',
    "zap": '<path d="M13 2L3 14h9l-1 8 10-12h-9z"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
    "trend": '<path d="M23 6l-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
    "wave": '<path d="M2 12h3l3-8 3 16 3-12 3 8 2-4h3"/>',
    "sliders": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "code": '<path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/>',
    "grid": '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.7-4 3-9 3s-9-1.3-9-3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/>',
    "route": '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "repeat": '<path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
    "star": '<path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8-6.2-3.3-6.2 3.3L7 14.2 2 9.3l6.9-1z"/>',
}


def icon(name: str, size: int = 22) -> str:
    inner = _I.get((name or "").strip().lower())
    if not inner:
        return ""
    return (f'<svg class="ico-svg" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{inner}</svg>')


ICON_NAMES = sorted(_I)

STATUS_LABEL = {"done": "Built", "built": "Built", "running": "In progress", "planned": "Planned"}


def status_key(value: str) -> str:
    v = (value or "").strip().lower()
    v = {"built": "done", "in progress": "running", "in-progress": "running"}.get(v, v)
    return v if v in {"done", "running", "planned"} else ""


def badge(status: str) -> str:
    key = status_key(status)
    return f'<span class="badge {key}">{STATUS_LABEL[key]}</span>' if key else ""


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _fields(line: str, count: int) -> list[str]:
    """`a | b | c` split on a pipe with spaces around it; padded to `count` fields."""
    parts = [p.strip() for p in re.split(r"(?<=\s)\|(?=\s|$)", line.strip(), maxsplit=count - 1)]
    return parts + [""] * (count - len(parts))


def _items(body: list[str]) -> list[str]:
    """List items (`- text`), with indented continuation lines joined to the item."""
    out: list[str] = []
    for raw in body:
        m = re.match(r"^\s*[-*]\s+(.*)$", raw)
        if m:
            out.append(m.group(1).strip())
        elif raw.strip() and out:
            out[-1] += " " + raw.strip()
    return out


def _strip_links(markup: str) -> str:
    return re.sub(r"</?a\b[^>]*>", "", markup)


# --------------------------------------------------------------------------- #
# cards                                                                        #
# --------------------------------------------------------------------------- #
def cards(opts: str, body: list[str], inline: Inline) -> str:
    """`- icon | Title | text | meta | status | link` per card. Options: 2, 3, 4, mini."""
    words = opts.split()
    cols = next((w for w in words if w in {"2", "3", "4"}), "3")
    mini = "mini" in words
    big = "big" in words
    out = []
    for line in _items(body):
        ico, title, text, meta, status, link = _fields(line, 6)
        linked = link.startswith("#") or link.startswith("http")
        text_html = inline(text) if text else ""
        meta_html = inline(meta) if meta else ""
        if linked:
            text_html, meta_html = _strip_links(text_html), _strip_links(meta_html)
        top = f'<span class="ico">{icon(ico)}</span>' if icon(ico) else ""
        b = badge(status)
        head = f'<div class="card-top">{top}{b}</div>' if (top or b) else ""
        inner = (f'{head}<div class="card-title">{inline(title)}</div>'
                 + (f'<p class="card-text">{text_html}</p>' if text_html else "")
                 + (f'<p class="card-meta">{meta_html}</p>' if meta_html else ""))
        if linked:
            ext = ' target="_blank" rel="noopener noreferrer"' if link.startswith("http") else ""
            out.append(f'<a class="card link" href="{_esc(link)}"{ext}>{inner}<span class="card-go" aria-hidden="true">&rarr;</span></a>')
        else:
            out.append(f'<div class="card">{inner}</div>')
    return f'<div class="cards cols-{cols}{" mini" if mini else ""}{" big" if big else ""}">{"".join(out)}</div>'


# --------------------------------------------------------------------------- #
# steps (a horizontal stepper that wraps on small screens)                     #
# --------------------------------------------------------------------------- #
def steps(opts: str, body: list[str], inline: Inline) -> str:
    """`- Title | one line | link | status` per step."""
    out = []
    for n, line in enumerate(_items(body), 1):
        title, text, link, status = _fields(line, 4)
        tag = "a" if link else "div"
        href = f' href="{_esc(link)}"' if link else ""
        out.append(f'<li><{tag} class="step"{href}><span class="num">{n}</span><span class="s-title">{inline(title)}</span>'
                   f'<span class="s-text">{_strip_links(inline(text))}</span>{badge(status)}</{tag}></li>')
    return f'<ol class="steps">{"".join(out)}</ol>'


# --------------------------------------------------------------------------- #
# bars                                                                         #
# --------------------------------------------------------------------------- #
def bars(opts: str, body: list[str], inline: Inline) -> str:
    """`- Label | number | note | tone` per bar. The option is the unit prefix (for example $)."""
    unit = opts.strip()
    rows = []
    for line in _items(body):
        label, value, note, tone = _fields(line, 4)
        try:
            number = float(value)
        except ValueError:
            continue
        rows.append((label, number, value, note, tone))
    top = max((r[1] for r in rows), default=1.0) or 1.0
    out = []
    for label, number, value, note, tone in rows:
        width = max(2.0, min(100.0, number / top * 100))
        tone_cls = f" {tone}" if tone in {"ok", "warn", "danger", "info"} else ""
        out.append(f'<div class="bar-row"><div class="bar-label">{inline(label)}</div>'
                   f'<div class="bar-track"><div class="bar-fill{tone_cls}" style="width:{width:.1f}%"></div></div>'
                   f'<div class="bar-val">{_esc(unit)}{_esc(value)}</div>'
                   + (f'<div class="bar-note">{inline(note)}</div>' if note else "") + "</div>")
    return f'<div class="bars">{"".join(out)}</div>'


# --------------------------------------------------------------------------- #
# timeline                                                                     #
# --------------------------------------------------------------------------- #
def timeline(opts: str, body: list[str], inline: Inline) -> str:
    """`- date | Title | text | link | status` per entry."""
    out = []
    for line in _items(body):
        date, title, text, link, status = _fields(line, 5)
        head = f'<a href="{_esc(link)}">{_strip_links(inline(title))}</a>' if link else inline(title)
        out.append(f'<li><span class="tl-date">{_esc(date)}</span><div class="tl-body"><div class="tl-title">{head} {badge(status)}</div>'
                   f'<p>{inline(text)}</p></div></li>')
    return f'<ol class="timeline">{"".join(out)}</ol>'


# --------------------------------------------------------------------------- #
# kanban                                                                       #
# --------------------------------------------------------------------------- #
KANBAN_STATUS = {"built": "done", "done": "done", "in progress": "running", "running": "running", "planned": "planned"}


def kanban_parse(body: list[str]) -> list[tuple[str, str, list[list[str]]]]:
    cols: list[tuple[str, str, list[list[str]]]] = []
    for raw in body:
        s = raw.strip()
        m = re.match(r"^#{1,4}\s+(.*)$", s)
        if m:
            title = m.group(1).strip()
            cols.append((title, KANBAN_STATUS.get(title.lower(), ""), []))
            continue
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m and cols:
            cols[-1][2].append(_fields(m.group(1), 3))
    return cols


def kanban(opts: str, body: list[str], inline: Inline) -> str:
    """`## Built` / `## In progress` / `## Planned`, then `- ID | what | tag` per package."""
    cols = kanban_parse(body)
    out = []
    for title, status, items in cols:
        lis = []
        for ident, what, tag in items:
            lis.append(f'<li class="kitem"><span class="k-id">{_esc(ident)}</span><span class="k-what">{inline(what)}</span>'
                       + (f'<span class="k-tag">{_esc(tag)}</span>' if tag else "") + "</li>")
        out.append(f'<section class="kcol {status}"><header><h4 class="k-head">{_esc(title)}</h4><span class="k-count">{len(items)}</span></header>'
                   f'<ul>{"".join(lis)}</ul></section>')
    flt = ('<div class="kfilter-wrap"><input class="kfilter" type="search" placeholder="Filter packages" '
           'aria-label="Filter packages" autocomplete="off"></div>')
    return f'{flt}<div class="kanban">{"".join(out)}</div>'


def kanban_counts(body: list[str]) -> dict[str, int]:
    return {status: len(items) for _t, status, items in kanban_parse(body) if status}


# --------------------------------------------------------------------------- #
# status board (docs/board/board.yaml)                                         #
# --------------------------------------------------------------------------- #
#: Set by build.py before the pages are rendered: {"board": <canonical board>, "etag": str}.
BOARD: dict[str, Any] = {}


def board_counts() -> dict[str, int]:
    """Cards per overall status (done, running, planned) for the build progress bar."""
    data = BOARD.get("board") or {"columns": [], "cards": []}
    status = {c["id"]: c["status"] for c in data["columns"]}
    totals = {"done": 0, "running": 0, "planned": 0}
    for card in data["cards"]:
        key = status.get(card["column"], "planned")
        totals["planned" if key == "blocked" else key] += 1
    return totals


def board(opts: str, body: list[str], inline: Inline) -> str:
    """`:::board`. The interactive board is built by board.js from the data in the page; this is the
    read-only version for browsers without scripts (and the text the search can read)."""
    data = BOARD.get("board") or {"columns": [], "cards": []}
    out = []
    for col in data["columns"]:
        cards = [c for c in data["cards"] if c["column"] == col["id"]]
        lis = "".join(f'<li class="kitem"><span class="k-id">{_esc(c.get("package") or c["id"])}</span><span class="k-what">{_esc(c["title"])}</span>'
                      f'<span class="k-tag">{_esc(c["owner"])}</span></li>' for c in cards)
        out.append(f'<section class="kcol {col["status"]}"><header><h4 class="k-head">{_esc(col["title"])}</h4><span class="k-count">{len(cards)}</span></header>'
                   f'<ul>{lis}</ul></section>')
    return f'<div id="board-root" class="board-app"><div class="kanban">{"".join(out)}</div></div>'


DIRECTIVES: dict[str, Callable[[str, list[str], Inline], str]] = {
    "cards": cards, "steps": steps, "bars": bars, "timeline": timeline, "kanban": kanban, "board": board,
}
