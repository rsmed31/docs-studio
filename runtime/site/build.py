#!/usr/bin/env python3
"""Build the project documentation site: ONE self-contained docs/site/index.html.

    python docs/site/build.py [--out PATH] [--repo PATH] [--check] [--no-scan]

Written pages     docs/site/src/*.md       (Claude or you write these: Markdown + diagram directives)
Scanned pages     docs/site/scan.py        (read from the repository on every build: overview, folder
                                            structure, module graph, git activity, dependencies, TODOs)
Diagram presets   docs/site/presets/       (flow, sequence, zones, tree, charts ... with animations)
Visual blocks     docs/site/blocks.py      (cards, steps, bars, timeline, kanban, board, icons)
Theme             docs/site/theme/         (inlined into the output)
Config            docs/studio.json

Standard library plus PyYAML. Runs offline. Nothing is written but the output file.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # noqa: F401  (the board needs it)
except ImportError:                                                    # pragma: no cover
    sys.exit("docs-studio needs PyYAML:  python -m pip install pyyaml")

SITE_DIR = Path(__file__).resolve().parent
DOCS_DIR = SITE_DIR.parent
DEFAULT_REPO = DOCS_DIR.parent
for _p in (SITE_DIR, DOCS_DIR / "board"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
import blocks                                                          # noqa: E402
import board as boardlib                                               # noqa: E402
import presets                                                         # noqa: E402
import scan as scanlib                                                 # noqa: E402

DEFAULT_CONFIG: dict[str, Any] = {
    "name": "", "port": 0, "animation": "auto", "language": "en",
    "features": {"board": True, "whiteboard": True},
    "scan": {"enabled": True, "ignore": [], "disable": []},
    "strict_scan": False,
}


def load_config(docs_dir: Path = DOCS_DIR) -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    path = docs_dir / "studio.json"
    if path.is_file():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"warning: {path} is not valid JSON ({exc}); using defaults", file=sys.stderr)
            user = {}
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    if not cfg.get("name"):
        cfg["name"] = DEFAULT_REPO.name.replace("-", " ").replace("_", " ").title()
    return cfg


# --------------------------------------------------------------------------- #
# Small HTML helpers                                                           #
# --------------------------------------------------------------------------- #


class Raw(str):
    """A string that is already HTML."""


def esc(value: Any) -> str:
    return value if isinstance(value, Raw) else html.escape(str(value), quote=True)


def code(value: Any) -> Raw:
    return Raw(f"<code>{esc(value)}</code>")


def badge(text: str, kind: str = "") -> Raw:
    return Raw(f'<span class="badge {esc(kind or text.lower().replace(" ", "-"))}">{esc(text)}</span>')


def table(headers: list[str], rows: list[list[Any]], *, cls: str = "") -> Raw:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return Raw(f'<div class="tablewrap"><table class="{esc(cls)}"><thead><tr>{head}</tr></thead>'
               f"<tbody>{body}</tbody></table></div>")


def details(summary: Any, inner: Any, *, open_: bool = False) -> Raw:
    return Raw(f'<details{" open" if open_ else ""}><summary>{esc(summary)}</summary>{esc(inner)}</details>')


def para(text: Any, cls: str = "") -> Raw:
    return Raw(f'<p{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{esc(text)}</p>')


def h(level: int, text: str) -> Raw:
    return Raw(f"<h{level}>{esc(text)}</h{level}>")


def first_paragraph(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:stop + 1] if stop > 80 else cut.rsplit(" ", 1)[0] + "...")


def slugify(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    slug = re.sub(r"[^a-z0-9]+", "-", html.unescape(text).lower()).strip("-")
    return slug or "section"


# --------------------------------------------------------------------------- #
# Markdown (the subset the written pages use)                                  #
# --------------------------------------------------------------------------- #
CALLOUTS = {"note": "Note", "tip": "Tip", "warn": "Careful", "planned": "Planned, not built",
            "decision": "Owner decision", "done": "Built", "running": "In progress",
            "open": "Open question"}


#: Scanned Markdown by name, for `{{auto:name}}` embeds (filled by build.py before pages render).
AUTO: dict[str, str] = {}


class Markdown:
    """A small, strict Markdown renderer: headings, paragraphs, nested lists, tables,
    fenced code, block quotes, ::: callouts, {{svg:name}} figures and inline markup."""

    def __init__(self, src_dir: Path) -> None:
        self.src_dir = src_dir
        self.kanban_totals: dict[str, int] = {}

    # inline ------------------------------------------------------------ #
    def inline(self, text: str) -> str:
        stash: list[str] = []

        def keep(markup: str) -> str:
            stash.append(markup)
            return f"\x00{len(stash) - 1}\x00"

        text = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{html.escape(m.group(1))}</code>"), text)
        text = html.escape(text, quote=False)
        text = re.sub(r"\[\[([a-z -]+)\]\]",
                      lambda m: keep(f'<span class="badge {blocks.status_key(m.group(1)) or m.group(1).replace(" ", "-")}">'
                                     f'{blocks.STATUS_LABEL.get(blocks.status_key(m.group(1)), m.group(1))}</span>'),
                      text)

        def link(m: re.Match) -> str:
            label, url = m.group(1), html.unescape(m.group(2)).strip()
            if url.startswith("#"):
                return keep(f'<a href="{html.escape(url)}" class="internal">{label}</a>')
            return keep(f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">{label}</a>')

        text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
        text = re.sub(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"<em>\1</em>", text)
        return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)

    # blocks ------------------------------------------------------------ #
    def render(self, text: str) -> str:
        lines = text.replace("\r\n", "\n").split("\n")
        return self._blocks(lines)

    def _blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            if stripped.startswith("```"):
                lang = stripped[3:].strip()
                j = i + 1
                body: list[str] = []
                while j < n and not lines[j].strip().startswith("```"):
                    body.append(lines[j])
                    j += 1
                out.append(f'<pre><code class="lang-{html.escape(lang)}">{html.escape(chr(10).join(body))}</code></pre>')
                i = j + 1
                continue
            if stripped.startswith(":::"):
                head = stripped[3:].strip()
                kind, _, rest = head.partition(" ")
                j, depth, body = i + 1, 1, []
                while j < n:
                    s = lines[j].strip()
                    if s == ":::":
                        depth -= 1
                        if depth == 0:
                            break
                    elif s.startswith(":::"):
                        depth += 1
                    body.append(lines[j])
                    j += 1
                if kind == "details":
                    out.append(self._details(rest, body))
                elif kind == "levels":
                    out.append(self._levels(body))
                elif kind in blocks.DIRECTIVES:
                    if kind in ("kanban", "board"):
                        counts = blocks.board_counts() if kind == "board" else blocks.kanban_counts(body)
                        for k, v in counts.items():
                            self.kanban_totals[k] = self.kanban_totals.get(k, 0) + v
                    source = ":::" + head + chr(10) + chr(10).join(body) + chr(10) + ":::"
                    out.append(self._viz(kind, source, blocks.DIRECTIVES[kind](rest, body, self.inline)))
                else:
                    label = CALLOUTS.get(kind, kind.title() or "Note")
                    out.append(f'<aside class="callout {html.escape(kind or "note")}">'
                               f'<div class="callout-title">{html.escape(label)}</div>{self._blocks(body)}</aside>')
                i = j + 1
                continue
            m = re.match(r"^\{\{status-bar\}\}$", stripped)
            if m:
                out.append(self._viz("status-bar", "{{status-bar}}", "<!--status-bar-->"))
                i += 1
                continue
            m = re.match(r"^\{\{auto:([\w-]+)\}\}$", stripped)
            if m:
                inner = self.render(AUTO[m.group(1)]) if m.group(1) in AUTO else f"<p>(no scanned content named {html.escape(m.group(1))})</p>"
                out.append(self._viz("auto", "{{auto:" + m.group(1) + "}}", inner))
                i += 1
                continue
            m = re.match(r"^\{\{svg:([\w-]+)(?:\|(.*))?\}\}$", stripped)
            if m:
                out.append(self._figure(m.group(1), m.group(2) or ""))
                i += 1
                continue
            m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
            if m:
                level = max(2, len(m.group(1)))
                out.append(f"<h{level}>{self.inline(m.group(2).strip())}</h{level}>")
                i += 1
                continue
            if re.match(r"^(-{3,}|\*{3,})$", stripped):
                out.append("<hr>")
                i += 1
                continue
            if stripped.startswith("|") and i + 1 < n and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
                j = i
                rows: list[str] = []
                while j < n and lines[j].strip().startswith("|"):
                    rows.append(lines[j].strip())
                    j += 1
                out.append(self._table(rows))
                i = j
                continue
            if stripped.startswith(">"):
                j = i
                body = []
                while j < n and lines[j].strip().startswith(">"):
                    body.append(re.sub(r"^\s*>\s?", "", lines[j]))
                    j += 1
                out.append(f"<blockquote>{self._blocks(body)}</blockquote>")
                i = j
                continue
            if re.match(r"^(\s*)([-*]|\d+\.)\s+", line):
                j, html_list = self._list(lines, i)
                out.append(html_list)
                i = j
                continue
            if stripped.startswith("<") and re.match(r"^<(div|figure|details|svg|table|p|ul|ol)\b", stripped):
                j = i
                body = []
                while j < n and lines[j].strip():
                    body.append(lines[j])
                    j += 1
                out.append("\n".join(body))
                i = j
                continue
            j = i
            body = []
            while j < n and lines[j].strip() and not self._starts_block(lines[j]):
                body.append(lines[j].strip())
                j += 1
            out.append(f"<p>{self.inline(' '.join(body))}</p>")
            i = max(j, i + 1)
        return "\n".join(out)

    @staticmethod
    def _starts_block(line: str) -> bool:
        s = line.strip()
        return bool(s.startswith(("```", ":::", ">", "|", "#")) or re.match(r"^([-*]|\d+\.)\s+", s)
                    or re.match(r"^\{\{svg:", s))

    def _list(self, lines: list[str], start: int) -> tuple[int, str]:
        base = len(lines[start]) - len(lines[start].lstrip())
        ordered = bool(re.match(r"^\s*\d+\.\s+", lines[start]))
        tag = "ol" if ordered else "ul"
        items: list[str] = []
        i = start
        n = len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                # a blank line ends the list unless the next line continues it
                k = i + 1
                while k < n and not lines[k].strip():
                    k += 1
                if k < n and re.match(r"^\s*([-*]|\d+\.)\s+", lines[k]) and len(lines[k]) - len(lines[k].lstrip()) >= base:
                    i = k
                    continue
                break
            indent = len(line) - len(line.lstrip())
            m = re.match(r"^\s*([-*]|\d+\.)\s+(.*)$", line)
            if indent < base or (indent == base and not m):
                break
            if indent > base and m:
                # nested list belongs to the previous item
                j, nested = self._list(lines, i)
                if items:
                    items[-1] += nested
                i = j
                continue
            if indent == base and m:
                if bool(re.match(r"\d+\.", m.group(1))) != ordered:
                    break
                items.append(self.inline(m.group(2)))
                i += 1
                continue
            # continuation line of the current item
            if items:
                items[-1] += " " + self.inline(line.strip())
            i += 1
        return i, f"<{tag}>" + "".join(f"<li>{item}</li>" for item in items) + f"</{tag}>"

    def _table(self, rows: list[str]) -> str:
        def cells(row: str) -> list[str]:
            row = row.strip()
            row = row[1:] if row.startswith("|") else row
            row = row[:-1] if row.endswith("|") else row
            return [c.strip() for c in re.split(r"(?<!\\)\|", row)]

        head = cells(rows[0])
        body = [cells(r) for r in rows[2:]]
        th = "".join(f"<th>{self.inline(c)}</th>" for c in head)
        tb = "".join("<tr>" + "".join(f"<td>{self.inline(c.replace(chr(92) + '|', '|'))}</td>" for c in r) + "</tr>"
                     for r in body)
        return f'<div class="tablewrap"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'

    @staticmethod
    def _viz(kind: str, source: str, inner: str) -> str:
        """A visual block: not editable in place; the Edit mode copies `data-md` back out."""
        return f'<div class="viz viz-{kind}" data-md="{html.escape(source, quote=True)}" contenteditable="false">{inner}</div>'

    def _levels(self, body: list[str]) -> str:
        """`:::levels` with `@@ Name` lines: one panel per level and a toggle to switch."""
        panels: list[tuple[str, list[str]]] = []
        for line in body:
            if line.strip().startswith("@@ "):
                panels.append((line.strip()[3:].strip(), []))
            elif panels:
                panels[-1][1].append(line)
        if not panels:
            return ""
        buttons = "".join(
            f'<button type="button" role="tab" class="lv-btn{" on" if k == 0 else ""}" data-lv="{k}" '
            f'aria-selected="{"true" if k == 0 else "false"}">{self.inline(name)}</button>'
            for k, (name, _) in enumerate(panels))
        bodies = "".join(
            f'<div class="lv-panel" role="tabpanel" data-lv="{k}"{"" if k == 0 else " hidden"}>{self._blocks(lines)}</div>'
            for k, (_, lines) in enumerate(panels))
        return f'<div class="levels"><div class="lv-bar" role="tablist" aria-label="Level of detail">{buttons}</div>{bodies}</div>'

    def _details(self, rest: str, body: list[str]) -> str:
        rest = rest.strip()
        opened = rest.startswith("open ")
        title = rest[5:].strip() if opened else rest
        plain = re.sub(r"\[\[[a-z -]+\]\]", "", title).strip() or "Details"
        return (f'<details class="sec" data-title="{html.escape(plain, quote=True)}"{" open data-open-default" if opened else ""}>'
                f"<summary>{self.inline(title)}</summary>{self._blocks(body)}</details>")

    def _figure(self, name: str, caption: str) -> str:
        path = self.src_dir / "_assets" / f"{name}.svg"
        svg = path.read_text(encoding="utf-8") if path.is_file() else f"<p>(missing diagram {html.escape(name)})</p>"
        cap = f"<figcaption>{self.inline(caption)}</figcaption>" if caption else ""
        return f'<figure class="diagram" contenteditable="false" data-svg="{html.escape(name)}">{svg}{cap}</figure>'


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
    return meta, text[end + 5:].lstrip("\n")


# --------------------------------------------------------------------------- #
# Pages                                                                        #
# --------------------------------------------------------------------------- #
@dataclass
class Page:
    id: str
    title: str
    group: str
    order: float
    kind: str                       # "written" | "generated"
    status: str = ""
    summary: str = ""
    body: str = ""
    source: str = ""
    markdown: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    headings: list[tuple[int, str, str]] = field(default_factory=list)
    layout: str = ""




# --------------------------------------------------------------------------- #
# Build report and repository facts                                            #
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, name: str, state: str, detail: str = "") -> None:
        self.rows.append((name, state, detail))


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def commit(self) -> str:
        try:
            sha = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                 timeout=15, check=False).stdout.strip()
            branch = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                                    text=True, timeout=15, check=False).stdout.strip()
            return f"{sha} on {branch}" if sha else "no commit yet"
        except (OSError, subprocess.SubprocessError):
            return "no git history"


SECRET_PATTERNS = [
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer value", re.compile(r"Bearer\s+(?!YOUR|<|\.\.\.|xxx|token)[A-Za-z0-9._-]{32,}")),
]
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
STRICT_PATTERNS = [("ip address", IPV4), ("remote shell", re.compile(r"\bssh\b", re.I)), ("long hex secret", re.compile(r"\b[0-9a-f]{40,}\b"))]


def scan_for_secrets(page_html: str, strict: bool = False) -> list[str]:
    hits = []
    for label, pattern in SECRET_PATTERNS + (STRICT_PATTERNS if strict else []):
        m = pattern.search(page_html)
        if m:
            hits.append(f"{label}: {m.group(0)[:40]!r}")
    return hits


# --------------------------------------------------------------------------- #
# Pages                                                                        #
# --------------------------------------------------------------------------- #
STATUS_LABELS = {"done": "Built", "running": "In progress", "planned": "Planned", "generated": "Generated", "": ""}
ALIASES = {"overview": "home"}
GROUP_ICONS = {"Start here": "compass", "Auto": "cpu", "Reference": "database", "Guides": "book", "How it works": "route",
               "Decisions & roadmap": "flag", "Running it": "server", "Architecture": "layers"}


def load_written(md: Markdown) -> list[Page]:
    pages = []
    src = SITE_DIR / "src"
    for path in sorted(src.glob("*.md")) if src.is_dir() else []:
        if path.name.startswith("_"):
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        pid = meta.get("id") or re.sub(r"^\d+-", "", path.stem)
        pages.append(Page(id=pid, title=meta.get("title", pid.replace("-", " ").title()), group=meta.get("group", "Guides"),
                          order=float(meta.get("order", 50)), kind="written", status=blocks.status_key(meta.get("status", "")),
                          summary=meta.get("summary", ""), body=md.render(body), layout=meta.get("layout", ""),
                          source=f"{DOCS_DIR.name}/site/src/{path.name}", markdown=body, meta=meta))
    return pages


def load_scanned(md: Markdown, raw: list[dict]) -> list[Page]:
    pages = []
    for d in raw:
        pages.append(Page(id=d["id"], title=d["title"], group=d.get("group", "Auto"), order=float(d.get("order", 300)),
                          kind="generated", status="generated", summary=d.get("summary", ""), body=md.render(d["markdown"]),
                          source="the repository (scanned at build time)"))
    return pages


def build_report_page(repo: Repo, report: Report, pages: list[Page], added: list[str]) -> Page:
    badge_kind = {"ok": "ok", "skipped": "info", "failed": "warn", "warn": "warn"}
    rows = [[code(n), badge(s, badge_kind.get(s, "")), d] for n, s, d in report.rows]
    names = sorted({p.name for p in presets.catalog()})
    body = (f"<p>Built {esc(dt.datetime.now().strftime('%Y-%m-%d %H:%M'))} from {esc(repo.commit())}. "
            f"{sum(1 for p in pages if p.kind == 'written')} written pages, {sum(1 for p in pages if p.kind == 'generated')} scanned pages.</p>"
            f"{table(['Step', 'Result', 'Detail'], rows) if rows else ''}"
            f"<p>{len(names)} diagram presets available: {esc(', '.join(names))}.</p>")
    return Page(id="build-report", title="Build report", group="Auto", order=390, kind="generated", status="generated",
                summary="What this build scanned, from which commit, and which presets exist.", body=body, source="docs/site/build.py")


HEADING_RE = re.compile(r"<h([234])(?:\s+[^>]*)?>(.*?)</h\1>|<details class=\"sec([^\"]*)\" data-title=\"([^\"]*)\"", re.S)


def assign_headings(page: Page) -> None:
    used: set[str] = set()
    page.body = page.body.replace('id="@', f'id="{page.id}--')

    def unique(base: str) -> str:
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        return slug

    def repl(m: re.Match) -> str:
        if m.group(1):
            level, inner = int(m.group(1)), m.group(2)
            slug = unique(slugify(inner))
            text = re.sub(r"<[^>]+>", "", html.unescape(inner)).strip()
            page.headings.append((level, slug, text))
            return (f'<h{level} id="{html.escape(page.id)}--{slug}">{inner}'
                    f'<a class="anchor" href="#{html.escape(page.id)}/{slug}" aria-label="Link to this section">#</a></h{level}>')
        text = html.unescape(m.group(4))
        slug = unique(slugify(text))
        page.headings.append((2, slug, text))
        return f'<details id="{html.escape(page.id)}--{slug}" class="sec{m.group(3)}" data-title="{m.group(4)}"'

    page.body = HEADING_RE.sub(repl, page.body)


def render_nav(pages: list[Page]) -> str:
    groups: dict[str, list[Page]] = {}
    for p in sorted(pages, key=lambda p: p.order):
        groups.setdefault(p.group, []).append(p)
    out = []
    chevron = '<svg class="chev" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    for group, items in groups.items():
        gid = slugify(group)
        out.append(f'<div class="nav-group" data-group="{gid}"><button type="button" class="nav-title" aria-expanded="false" aria-controls="grp-{gid}">'
                   f'<span class="ico">{blocks.icon(GROUP_ICONS.get(group, "folder"), 18)}</span><span class="nav-title-t">{esc(group)}</span>{chevron}</button>'
                   f'<div class="nav-items" id="grp-{gid}">')
        for p in items:
            st = p.status if p.status in {"done", "running", "planned"} else ""
            dot = f'<span class="dot {st}" title="{esc(STATUS_LABELS.get(st, ""))}"></span>' if st else '<span class="dot none"></span>'
            out.append(f'<a class="nav-link" href="#{esc(p.id)}" data-page="{esc(p.id)}" data-group="{gid}">{dot}<span>{esc(p.title)}</span></a>')
        out.append("</div></div>")
    return "\n".join(out)


def status_chip(p: Page) -> str:
    if p.kind == "generated":
        return '<span class="badge generated">Generated</span>' if p.status == "generated" else f'<span class="badge planned">Planned</span>'
    return f'<span class="badge {esc(p.status)}">{esc(STATUS_LABELS.get(p.status, p.status))}</span>' if p.status else ""


def render_page(p: Page, prev: Page | None, nxt: Page | None) -> str:
    home = p.layout == "home"
    wide = p.layout == "board"
    refpage = p.kind == "generated"
    banner = ""
    if refpage and p.id != "build-report":
        banner = ('<div class="gen-banner"><strong>Scanned</strong> from the repository every time the docs are built, so it cannot drift. '
                  'Read-only: change the code (or add a scanner in <code>docs/site/scanners/</code>), not this page.</div>')
    refbar = ""
    if refpage and 'class="sec refsec"' in p.body:
        refbar = ('<div class="refbar"><input class="page-filter" type="search" placeholder="Filter this page" aria-label="Filter this page" autocomplete="off">'
                  '<button type="button" class="btn small" data-act="expand-all">Expand all</button>'
                  '<button type="button" class="btn small" data-act="collapse-all">Collapse all</button></div>')
    toc = "".join(f'<a class="toc-l{lvl}" href="#{esc(p.id)}/{esc(slug)}">{esc(text)}</a>' for lvl, slug, text in p.headings if lvl <= 2)
    toc_html = (f'<nav class="toc" aria-label="On this page"><div class="toc-title">On this page</div>{toc}</nav>'
                if toc and not home and not wide else "")
    editable = ' data-editable="1"' if p.kind == "written" and not wide else ""
    expander = ('<div class="page-tools"><button type="button" class="btn small ghost" data-act="expand-all">Expand all sections</button>'
                '<button type="button" class="btn small ghost" data-act="collapse-all">Collapse all</button></div>'
                if p.kind == "written" and not home and p.body.count('class="sec') >= 2 else "")
    foot = ""
    if p.kind == "written" and not wide:
        foot = (f'<div class="page-foot"><span class="muted">Source: <code>{esc(p.source)}</code></span>'
                f'<button type="button" class="btn small ghost" data-act="copy-page">Copy page as Markdown</button>'
                f'<button type="button" class="btn small ghost edit-only" data-act="reset-page">Reset page</button></div>')
    pager = ""
    if prev or nxt:
        pager = ('<nav class="pager" aria-label="Previous and next page">'
                 + (f'<a class="prev" href="#{esc(prev.id)}"><small>Previous</small><span>{esc(prev.title)}</span></a>' if prev else "<span></span>")
                 + (f'<a class="next" href="#{esc(nxt.id)}"><small>Next</small><span>{esc(nxt.title)}</span></a>' if nxt else "<span></span>")
                 + "</nav>")
    crumb = f'<span class="crumb-g">{esc(p.group)}</span>'
    return (f'<article class="page{" home" if home else ""}{" wide" if wide else ""}" id="page-{esc(p.id)}" data-page="{esc(p.id)}" data-kind="{p.kind}" data-group="{slugify(p.group)}" hidden>'
            f'<header class="page-head"><div class="eyebrow">{crumb} {status_chip(p)}</div><h1>{esc(p.title)}</h1>'
            f'<p class="lede">{esc(p.summary)}</p></header>{banner}{refbar}{expander}'
            f'<div class="page-grid"><div class="page-body md"{editable}>{p.body}</div>{toc_html}</div>'
            f'{foot}{pager}</article>')


def status_bar(totals: dict[str, int], link: str = "#board") -> str:
    total = sum(totals.values())
    if not total:
        return ""
    segs = "".join(f'<span class="seg {k}" style="flex:{totals.get(k, 0)}" title="{totals.get(k, 0)} {STATUS_LABELS[k].lower()}"></span>'
                   for k in ("done", "running", "planned") if totals.get(k))
    legend = "".join(f'<span class="lg-item"><i class="lg {k}"></i><b>{totals.get(k, 0)}</b> {STATUS_LABELS[k].lower()}</span>' for k in ("done", "running", "planned"))
    return (f'<a class="statusbar" href="{link}"><div class="sb-head"><strong>Where the work stands</strong><span class="sb-go">Open the status board &rarr;</span></div>'
            f'<div class="sb-track">{segs}</div><div class="sb-legend">{legend}</div></a>')

def assemble(pages: list[Page], repo: Repo, md: Markdown, config: dict[str, Any], inputs: str = "") -> str:
    th = SITE_DIR / "theme"
    shell = (th / "shell.html").read_text(encoding="utf-8")
    css = "\n".join((th / n).read_text(encoding="utf-8") for n in ("site.css", "board.css", "presets.css"))
    js = (th / "site.js").read_text(encoding="utf-8")
    board_js = (th / "board.js").read_text(encoding="utf-8")
    presets_js = (th / "presets.js").read_text(encoding="utf-8")
    board_blob = json.dumps({**blocks.BOARD, "path": f"{DOCS_DIR.name}/board/board.yaml"}, ensure_ascii=False).replace("</", "<\\/")
    data = {p.id: {"title": p.title, "kind": p.kind, "md": p.markdown, "source": p.source, "meta": p.meta}
            for p in pages if p.kind == "written"}
    blob = json.dumps({"pages": data, "aliases": ALIASES}, ensure_ascii=False).replace("</", "<\\/")
    public_cfg = json.dumps({"name": config["name"], "features": config["features"], "animation": config["animation"]}).replace("</", "<\\/")
    build_id = hashlib.sha1("".join(STAMPS.sub("Built", p.body) for p in pages).encode("utf-8")).hexdigest()[:10]
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    guide = [p for p in sorted(pages, key=lambda p: p.order) if p.kind == "written"]
    rendered = []
    for p in sorted(pages, key=lambda p: p.order):
        prev = nxt = None
        if p in guide:
            k = guide.index(p)
            prev, nxt = (guide[k - 1] if k > 0 else None), (guide[k + 1] if k + 1 < len(guide) else None)
        rendered.append(render_page(p, prev, nxt))
    board_page = next((p.id for p in pages if p.layout == "board"), "board")
    body = "\n".join(rendered).replace("<!--status-bar-->", status_bar(md.kanban_totals, "#" + board_page))
    home = "home" if any(p.id == "home" for p in pages) else (sorted(pages, key=lambda p: p.order)[0].id if pages else "")
    name = esc(config["name"])
    foot = (f"The pages in <code>{DOCS_DIR.name}/site/src/*.md</code> are written for this project; the <em>Auto</em> pages are scanned from the "
            f"repository on every build. Run <code>python {DOCS_DIR.name}/site/studio.py build</code> to rebuild, "
            f"<code>python {DOCS_DIR.name}/site/studio.py start</code> to serve it with the editable board and whiteboard.")
    return (shell.replace("{{CSS}}", css).replace("{{JS}}", js).replace("{{NAV}}", render_nav(pages))
            .replace("{{PAGES}}", body).replace("{{PAGE_DATA}}", blob).replace("{{CONFIG}}", public_cfg)
            .replace("{{BOARD_JS}}", board_js).replace("{{PRESETS_JS}}", presets_js).replace("{{BOARD_DATA}}", board_blob)
            .replace("{{INPUTS}}", inputs).replace("{{BUILD_ID}}", build_id).replace("{{BUILT}}", stamp)
            .replace("{{COMMIT}}", esc(repo.commit())).replace("{{HOME}}", home).replace("{{TITLE}}", f"{name} docs")
            .replace("{{BRAND}}", f"{name} <em>docs</em>").replace("{{FOOTNOTE}}", foot))


# --------------------------------------------------------------------------- #
# Freshness: a hash of every input, embedded in the page, checked by --check   #
# --------------------------------------------------------------------------- #
SITE_INPUTS = ["src/**/*", "theme/*", "presets/*.py", "presets_custom/*.py", "scanners/*.py", "diagrams/*", "*.py"]
INPUTS_META = re.compile(r'<meta name="docs-inputs" content="([0-9a-f]*)">')
STAMPS = re.compile(r"Built \d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?(?:<br>| from )(?:[^<]*?(?=\.\s\d+ written pages)|[^<]*)")


def inputs_hash(repo_root: Path) -> str:
    """One hash over the site sources, the board, studio.json and the repository's tracked files."""
    digest = hashlib.sha1()
    files: dict[str, Path] = {}
    for pattern in SITE_INPUTS:
        for path in SITE_DIR.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files["site/" + path.relative_to(SITE_DIR).as_posix()] = path
    for extra in (DOCS_DIR / "board" / "board.yaml", DOCS_DIR / "studio.json"):
        if extra.is_file():
            files["docs/" + extra.name] = extra
    for key in sorted(files):
        digest.update(f"{key}\0{hashlib.sha1(files[key].read_bytes().replace(chr(13).encode() + chr(10).encode(), chr(10).encode())).hexdigest()}\n".encode())
    try:
        tracked = subprocess.run(["git", "-C", str(repo_root), "ls-files", "-s"], capture_output=True, text=True, timeout=60,
                                 check=False, encoding="utf-8", errors="replace").stdout
        skip = (f"{DOCS_DIR.name}/site/index.html", f"{DOCS_DIR.name}/.studio/", f"{DOCS_DIR.name}/whiteboard/")
        digest.update("\n".join(ln for ln in tracked.splitlines() if not any(s in ln for s in skip)).encode("utf-8", "replace"))
    except (OSError, subprocess.SubprocessError):
        pass
    return digest.hexdigest()[:16]


def same_apart_from_stamps(path: Path, new: str) -> bool:
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return STAMPS.sub("Built", old) == STAMPS.sub("Built", new)


def check_fresh(page: Path, repo_root: Path) -> int:
    """0 when the page was built from the current inputs, 1 when it is stale or missing."""
    if not page.exists():
        print(f"STALE: {page} does not exist. Run: python {DOCS_DIR.name}/site/studio.py build", file=sys.stderr)
        return 1
    m = INPUTS_META.search(page.read_text(encoding="utf-8"))
    current = inputs_hash(repo_root)
    if not m or m.group(1) != current:
        print(f"STALE: {page} was built from different sources. Run: python {DOCS_DIR.name}/site/studio.py build", file=sys.stderr)
        return 1
    print(f"docs are up to date (inputs {current})")
    return 0


def build(out_path: Path, repo_root: Path, scan: bool = True, quiet: bool = False) -> int:
    config = load_config()
    repo = Repo(repo_root.resolve())
    try:
        board = boardlib.load(DOCS_DIR / "board" / "board.yaml")
    except boardlib.BoardError as exc:
        print(f"{DOCS_DIR.name}/board/board.yaml is invalid:", *exc.errors, sep="\n  - ", file=sys.stderr)
        return 2
    blocks.BOARD.update({"board": board, "etag": boardlib.etag_of(board)})
    added = presets.install(blocks.DIRECTIVES, {"animation": config["animation"]}, SITE_DIR / "presets_custom")
    AUTO.clear()
    md = Markdown(SITE_DIR / "src")
    report = Report()
    if added:
        report.add("custom presets", "ok", ", ".join(added))
    scanned_raw: list[dict] = []
    if scan and config["scan"].get("enabled", True):
        scanned_raw, rows = scanlib.run_all(repo.root, DOCS_DIR.name, config, SITE_DIR / "scanners")
        for r in rows:
            report.add(*r)
        for d in scanned_raw:
            AUTO[d["id"]] = d["markdown"]            # written pages can embed these with {{auto:id}}
    written = load_written(md)
    scanned = load_scanned(md, scanned_raw)
    pages = written + scanned
    if not config["features"].get("whiteboard", True):
        pages = [p for p in pages if p.id != "whiteboard"]
    pages.append(build_report_page(repo, report, pages, added))
    if not any(p.kind == "written" for p in pages):
        pages.insert(0, Page(id="home", title=config["name"], group="Start here", order=1, kind="written",
                             summary="No pages written yet.", markdown="",
                             body="<p>No guide pages exist yet. Ask Claude to run the docs-studio skill to write them, "
                                  f"or add Markdown files to <code>{DOCS_DIR.name}/site/src/</code>.</p>", source=""))
    for p in pages:
        assign_headings(p)
    out = assemble(pages, repo, md, config, inputs_hash(repo.root))
    hits = scan_for_secrets(out, bool(config.get("strict_scan")))
    if hits:
        print("Refusing to write: the page contains something shaped like a secret:", file=sys.stderr)
        for hit in hits:
            print("  -", hit, file=sys.stderr)
        return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kept = same_apart_from_stamps(out_path, out)
    if not kept:
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
    if not quiet:
        print(f"{'kept (only the build date and commit changed)' if kept else 'wrote'} {out_path} ({len(out) // 1024} KB): "
              f"{len(written)} written, {len(scanned)} scanned pages")
        for name, state, detail in report.rows:
            if state in ("failed",):
                print(f"  {state}: {name}: {detail}")
    return 1 if any(s == "failed" for _n, s, _d in report.rows) and os.environ.get("DOCS_STRICT") else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the documentation site.")
    parser.add_argument("--out", type=Path, default=SITE_DIR / "index.html")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO, help="the checkout to scan")
    parser.add_argument("--check", action="store_true", help="build nothing: exit 1 when the page is stale")
    parser.add_argument("--no-scan", action="store_true", help="skip the repository scan (written pages only)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        return check_fresh(args.out, args.repo.resolve())
    return build(args.out, args.repo, not args.no_scan, args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
