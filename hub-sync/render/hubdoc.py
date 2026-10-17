#!/usr/bin/env python3
"""hub-sync renderer: docs-studio's Markdown, diagram presets (with animations) and repository scanners,
used to turn what Claude writes, and what the repository contains, into hub pages.

    python hubdoc.py render              stdin {id,title,groupTitle,lede,md} -> stdout {html}
    python hubdoc.py scan [--push]       scan the repository (CLAUDE_PROJECT_DIR or cwd) into Auto pages
    python hubdoc.py install-git-hook    rescan and push after every commit (a post-commit hook)
    python hubdoc.py presets             the diagram vocabulary (for Claude)

Uses the skill runtime (skills/docs-studio/runtime/site: blocks, presets, scan); the Markdown renderer below mirrors build.py.
Standard library only.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent.parent / "skills" / "docs-studio" / "runtime" / "site"     # one copy: the skill's runtime
REFERENCE = RUNTIME.parent.parent / "references"
sys.path.insert(0, str(RUNTIME))
import blocks                                                          # noqa: E402
import presets                                                         # noqa: E402
import scan                                                            # noqa: E402


# ---- from docs-studio build.py: HTML helpers ----
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

# ---- from docs-studio build.py: Markdown ----
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

# ---- from docs-studio build.py: secret patterns, heading ids ----
SECRET_PATTERNS = [
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer value", re.compile(r"Bearer\s+(?!YOUR|<|\.\.\.|xxx|token)[A-Za-z0-9._-]{32,}")),
]

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

# --------------------------------------------------------------------------- #
# Hub pages: the same markup as a docs-studio site, pushed to the project hub   #
# --------------------------------------------------------------------------- #
STATUS_LABELS = {"done": "Built", "running": "In progress", "planned": "Planned", "generated": "Generated", "": ""}
AUTO_GROUP = {"id": "auto", "title": "Auto", "icon": "cpu"}


class _Page:
    def __init__(self, pid: str, body: str) -> None:
        self.id, self.body, self.headings = pid, body, []


def redact(markup: str) -> tuple[str, list[str]]:
    """Scanned pages leave the machine: blank out anything shaped like a credential."""
    hits = []
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(markup):
            hits.append(label)
            markup = pattern.sub("[redacted]", markup)
    return markup, hits


def page_html(pid: str, title: str, group_title: str, lede: str, md_text: str, *, generated: bool = False, status: str = "") -> str:
    """Inner HTML of one page (what goes inside <article class="page">), like docs-studio's render_page."""
    presets.reset_ids()
    page = _Page(pid, MD.render(md_text))
    assign_headings(page)
    toc = "".join(f'<a class="toc-l{lvl}" href="#{esc(pid)}/{esc(slug)}">{esc(text)}</a>' for lvl, slug, text in page.headings if lvl <= 2)
    toc_html = f'<nav class="toc" aria-label="On this page"><div class="toc-title">On this page</div>{toc}</nav>' if toc else ""
    chip = '<span class="badge generated">Generated</span>' if generated else (
        f'<span class="badge {esc(status)}">{esc(STATUS_LABELS.get(status, status))}</span>' if status else "")
    banner = ('<div class="gen-banner"><strong>Scanned</strong> from the repository after each commit, so it cannot drift. '
              "Read-only: change the code, not this page.</div>") if generated else ""
    expander = ('<div class="page-tools"><button type="button" class="btn small ghost" data-act="expand-all">Expand all sections</button>'
                '<button type="button" class="btn small ghost" data-act="collapse-all">Collapse all</button></div>'
                if page.body.count('class="sec') >= 2 else "")
    editable = "" if generated else ' data-editable="1"'
    return (f'<header class="page-head"><div class="eyebrow"><span class="crumb-g">{esc(group_title)}</span> {chip}</div><h1>{esc(title)}</h1>'
            + (f'<p class="lede">{esc(lede)}</p>' if lede else "") + f"</header>{banner}{expander}"
            f'<div class="page-grid"><div class="page-body md"{editable}>{page.body}</div>{toc_html}</div>')


def hub_call(method: str, path: str, body: Any = None) -> Any:
    url, project, token = (os.environ.get(k, "").strip() for k in ("HUB_URL", "HUB_PROJECT", "HUB_TOKEN"))
    if not (url and project and token):
        raise SystemExit("HUB_URL, HUB_PROJECT and HUB_TOKEN must be set")
    req = urllib.request.Request(f"{url.rstrip('/')}/api/hub/projects/{project}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Hub-Project": project})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def cmd_render() -> int:
    """stdin {id,title,groupTitle,lede,md,status} -> stdout {html}"""
    d = json.loads(sys.stdin.read() or "{}")
    body = re.sub(r"^#\s+.*\n+", "", str(d.get("md", "")).replace("\r\n", "\n"))     # the title is the page heading already
    markup, hits = redact(page_html(d["id"], d.get("title") or d["id"], d.get("groupTitle") or "Pages", d.get("lede") or "", body, status=d.get("status", "")))
    sys.stdout.write(json.dumps({"html": markup, "redacted": hits}))
    return 0


def _cache_path(root: Path) -> Path:
    key = hashlib.sha1(f"{os.environ.get('HUB_URL', '')}|{os.environ.get('HUB_PROJECT', '')}|{root}".encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"hub-scan-{key}.json"


def cmd_scan(root: Path, push: bool, quiet: bool, force: bool) -> int:
    say = (lambda *a: None) if quiet else print
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    cache_file = _cache_path(root)
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {"head": "", "pages": {}}
    if push and not force and head and cache.get("head") == head:
        say(f"already scanned {head[:7]}")
        return 0
    raw, report = scan.run_all(root, "docs", {"scan": {"enabled": True, "ignore": [r"^\.claude/"], "disable": []}})
    for name, state, detail in report:
        say(f"  {name}: {state} {detail}")
    pages = []
    for d in raw:
        pid = re.sub(r"[^a-z0-9-]+", "-", "auto-" + re.sub(r"^scan-", "", str(d["id"]).lower()))[:40].strip("-")
        markup, hits = redact(page_html(pid, d["title"], AUTO_GROUP["title"], d.get("summary", ""), d["markdown"], generated=True))
        if hits:
            say(f"  {pid}: redacted {', '.join(hits)}")
        pages.append({"id": pid, "title": d["title"], "format": "html", "body": markup, "kind": "generated", "group": AUTO_GROUP["id"],
                      "groupTitle": AUTO_GROUP["title"], "order": 2000 + float(d.get("order", 300)), "lede": d.get("summary", ""),
                      "md": d["markdown"], "quiet": True})
    if not push:
        for p in pages:
            say(f"{p['id']}: {p['title']} ({len(p['body']) // 1024} KB)")
        return 0
    nav = hub_call("GET", "/nav")
    if not any(g.get("id") == AUTO_GROUP["id"] for g in nav.get("groups", [])):
        nav.setdefault("groups", []).append({"id": AUTO_GROUP["id"], "title": AUTO_GROUP["title"], "icon": blocks.icon(AUTO_GROUP["icon"], 18)})
        hub_call("PUT", "/nav", nav)
    changed = []
    fresh = {}
    for p in pages:
        digest = hashlib.sha1(p["body"].encode()).hexdigest()
        fresh[p["id"]] = digest
        if force or cache.get("pages", {}).get(p["id"]) != digest:
            hub_call("PUT", f"/docs/{p['id']}", p)
            changed.append(p["title"])
    gone = [pid for pid in cache.get("pages", {}) if pid not in fresh]
    for pid in gone:
        try:
            hub_call("DELETE", f"/docs/{pid}")
        except urllib.error.HTTPError:
            pass
    if changed or gone:
        hub_call("POST", "/activity", {"kind": "docs", "summary": f"Auto pages rescanned at {head[:7] or 'working tree'}: "
                                       + (", ".join(changed) if changed else "no change") + (f"; removed {len(gone)}" if gone else "")})
    cache_file.write_text(json.dumps({"head": head, "pages": fresh}), encoding="utf-8")
    say(f"pushed {len(changed)} changed page(s), removed {len(gone)}, at {head[:7]}")
    return 0


def cmd_install_git_hook(root: Path) -> int:
    hook = root / ".git" / "hooks" / "post-commit"
    if not (root / ".git").is_dir():
        raise SystemExit("not a git repository (or a worktree: add the hook in the main checkout)")
    line = f'"{sys.executable}" "{Path(__file__).resolve()}" scan --push --quiet >/dev/null 2>&1 &   # hub-sync auto pages'
    text = hook.read_text(encoding="utf-8") if hook.exists() else "#!/bin/sh\n"
    if "hub-sync auto pages" in text:
        print("already installed")
        return 0
    hook.write_text(text.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    print(f"installed {hook} (needs HUB_URL, HUB_PROJECT, HUB_TOKEN in the environment git runs in)")
    return 0


def main(argv: list[str]) -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    cmd = argv[0] if argv else "help"
    if cmd == "render":
        return cmd_render()
    if cmd == "scan":
        return cmd_scan(root, "--push" in argv, "--quiet" in argv, "--force" in argv)
    if cmd == "install-git-hook":
        return cmd_install_git_hook(root)
    if cmd == "presets":
        print((REFERENCE / "presets.md").read_text(encoding="utf-8"))
        return 0
    print(__doc__)
    return 0 if cmd == "help" else 2


MD = Markdown(Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()) / "docs" / "site" / "src")
presets.install(blocks.DIRECTIVES, {"animation": "auto"})

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
