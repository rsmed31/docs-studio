#!/usr/bin/env python3
"""Import a built docs-studio site into a Docs Studio hub project: every page as rendered (cards, diagrams,
reference tables), the sidebar groups with their icons, and the full status board.

    python import_site.py [--site docs/site/index.html] [--board docs/board/board.yaml] [--dry-run]

Run in the project (paths are relative to CLAUDE_PROJECT_DIR or the current folder). Needs HUB_URL,
HUB_PROJECT and HUB_TOKEN (the project's Settings page in the hub shows them). Rebuild the site first.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("needs PyYAML: python -m pip install pyyaml")

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default
URL, PROJECT, TOKEN = (os.environ.get(k, "").strip() for k in ("HUB_URL", "HUB_PROJECT", "HUB_TOKEN"))
DRY = "--dry-run" in sys.argv
if not DRY and not (URL and PROJECT and TOKEN):
    sys.exit("Set HUB_URL, HUB_PROJECT and HUB_TOKEN (copy the command from the project's Settings page), or use --dry-run.")


def call(method, path, body):
    req = urllib.request.Request(f"{URL.rstrip('/')}/api/hub/projects/{PROJECT}{path}", method=method, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}", "X-Hub-Project": PROJECT})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"FAILED {method} {path}: {e.code} {e.read().decode()[:300]}")


SITE = ROOT / arg("--site", "docs/site/index.html")
BOARD = ROOT / arg("--board", "docs/board/board.yaml")
if not SITE.is_file():
    sys.exit(f"no built docs site at {SITE} (build it, or pass --site)")
site = SITE.read_text(encoding="utf-8")

# ---- sidebar groups (order, titles, icons) ----
groups = []
for m in re.finditer(r'<div class="nav-group" data-group="([^"]+)">.*?<span class="ico">(.*?)</span><span class="nav-title-t">(.*?)</span>', site, re.S):
    groups.append({"id": m.group(1), "title": html.unescape(m.group(3)), "icon": m.group(2)})
group_title = {g["id"]: g["title"] for g in groups}
nav_order = [m.group(1) for m in re.finditer(r'<a class="nav-link" href="#[^"]*" data-page="([^"]+)"', site)]

# ---- page sources (Markdown, for search and for Claude) ----
data = json.loads(re.search(r'<script id="page-data" type="application/json">(.*?)</script>', site, re.S).group(1))
home = (data.get("aliases") or {}).get("overview") or "home"

# ---- pages, as rendered ----
pages = []
for m in re.finditer(r'<article class="page[^"]*" id="page-([^"]+)" data-page="[^"]+" data-kind="([^"]+)" data-group="([^"]*)"[^>]*>(.*?)</article>', site, re.S):
    pid, kind, group, body = m.group(1), m.group(2), m.group(3), m.group(4)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", pid):
        print(f"skip {pid}: id not usable")
        continue
    title = html.unescape(re.sub(r"<[^>]+>", "", (re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S) or [None, pid])[1])).strip()
    lede = html.unescape(re.sub(r"<[^>]+>", "", (re.search(r'<p class="lede">(.*?)</p>', body, re.S) or [None, ""])[1])).strip()
    pages.append({"id": pid, "title": title[:120], "format": "html", "body": body, "kind": "generated" if kind == "generated" else "written",
                  "group": group or "pages", "groupTitle": group_title.get(group, "Pages"), "lede": lede[:600],
                  "order": nav_order.index(pid) if pid in nav_order else 1000, "md": (data["pages"].get(pid) or {}).get("md", "")[:200000],
                  "quiet": True})

# ---- board (unchanged: same columns, cards, history and archive as board.yaml) ----
board = json.loads(json.dumps(yaml.safe_load(BOARD.read_text(encoding="utf-8")), default=str)) if BOARD.is_file() else None   # dates -> strings

print(f"board: {len(board['cards'])} cards, {len(board.get('archived') or [])} archived, {len(board['columns'])} columns" if board else "board: none found (skipped)")
print(f"sidebar: {len(groups)} groups, home page '{home}'")
print(f"pages: {len(pages)} ({sum(p['kind'] == 'written' for p in pages)} written, {sum(p['kind'] == 'generated' for p in pages)} generated)")
too_big = [p["id"] for p in pages if len(p["body"]) > 1_500_000]
if too_big:
    sys.exit(f"pages over 1.5 MB: {too_big}")
if DRY:
    for p in pages:
        print(f"  {p['order']:>4} {p['group']:<22} {p['id']:<28} {len(p['body']) // 1024:>5} KB  {p['title']}")
    sys.exit("dry run: nothing sent")

if board:
    call("PUT", "/board", board)
    print("board imported")
call("PUT", "/nav", {"home": home, "groups": groups})
print("sidebar imported")
for i, p in enumerate(pages, 1):
    call("PUT", f"/docs/{p['id']}", p)
    print(f"  [{i}/{len(pages)}] {p['id']}: {p['title']}")
call("POST", "/activity", {"kind": "docs", "summary": f"Imported {len(pages)} pages" + (" and the board" if board else "") + " from the docs-studio site"})
print(f"done: open {URL.rstrip('/')}/p/{PROJECT}")
