#!/usr/bin/env python3
"""docs-studio command line (project side). Everything the hooks and the skill call goes through here.

    python docs/site/studio.py start [--open]     start the docs server in the background (idempotent)
    python docs/site/studio.py stop | status | url
    python docs/site/studio.py build [--no-scan]  rebuild docs/site/index.html
    python docs/site/studio.py check              exit 1 when the built page is stale
    python docs/site/studio.py presets            list every diagram preset and animation
    python docs/site/studio.py reviewed           mark the written pages as up to date with the code
    python docs/site/studio.py changes            commits and areas changed since the pages were last reviewed
    python docs/site/studio.py icons              icon names for cards, zones and layers
    python docs/site/studio.py hosting netlify|vercel
    python docs/site/studio.py hook session-start | post-commit      (called by the hooks, never fails)

Standard library only (the build needs PyYAML).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
DOCS_DIR = SITE_DIR.parent
ROOT = DOCS_DIR.parent
STATE_DIR = DOCS_DIR / ".studio"
SERVER_FILE = STATE_DIR / "server.json"
REVIEW_FILE = STATE_DIR / "review.json"


def config() -> dict:
    try:
        return json.loads((DOCS_DIR / "studio.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def default_port() -> int:
    configured = int(config().get("port") or 0)
    if configured:
        return configured
    return 8700 + int(hashlib.sha1(str(ROOT).lower().encode()).hexdigest(), 16) % 100


def health(port: int, timeout: float = 1.2) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data if data.get("studio") else None
    except (OSError, ValueError):
        return None


def port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def running() -> int | None:
    """The port of this project's running server, or None."""
    try:
        state = json.loads(SERVER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    for port in dict.fromkeys([state.get("port"), default_port()]):
        if port:
            h = health(int(port))
            if h and Path(h.get("root", "")).resolve() == ROOT.resolve():
                return int(port)
    return None


def run_build(extra: list[str] | None = None, quiet: bool = False) -> int:
    cmd = [sys.executable, str(SITE_DIR / "build.py"), *(extra or [])]
    if quiet:
        cmd.append("--quiet")
    return subprocess.run(cmd, cwd=str(ROOT), check=False).returncode


def detach(cmd: list[str], log: Path) -> subprocess.Popen:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = open(log, "ab")
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": out, "cwd": str(ROOT)}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000200 | 0x00000008 | 0x08000000      # new group, detached, no window
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def start(open_browser: bool = False, quiet: bool = False) -> int:
    port = running()
    if port is None:
        if not (SITE_DIR / "index.html").exists():
            run_build(quiet=True)
        want = default_port()
        port = next((p for p in range(want, want + 60) if port_free(p)), 0)
        if not port:
            print("docs-studio: no free port found near", want, file=sys.stderr)
            return 1
        cmd = [sys.executable, str(SITE_DIR / "serve.py"), "--port", str(port), "--repo", str(ROOT)]
        if config().get("server", {}).get("commit_edits"):
            cmd.append("--commit")
        proc = detach(cmd, STATE_DIR / "server.log")
        for _ in range(40):
            if health(port):
                break
            time.sleep(0.15)
        else:
            print(f"docs-studio: the server did not answer on port {port}; see {STATE_DIR / 'server.log'}", file=sys.stderr)
            return 1
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SERVER_FILE.write_text(json.dumps({"port": port, "pid": proc.pid, "started": int(time.time())}), encoding="utf-8")
    url = f"http://localhost:{port}"
    if not quiet:
        print(f"docs-studio: {url}")
    if open_browser:
        webbrowser.open(url)
    return 0


def stop() -> int:
    try:
        state = json.loads(SERVER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("docs-studio: not running")
        return 0
    pid = int(state.get("pid", 0))
    if pid:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
            else:
                os.kill(pid, 15)
        except OSError:
            pass
    SERVER_FILE.unlink(missing_ok=True)
    print("docs-studio: stopped")
    return 0


def status() -> int:
    port = running()
    print(f"docs-studio: running at http://localhost:{port}" if port else "docs-studio: not running")
    return 0 if port else 1


# --------------------------------------------------------------------------- #
# Review tracking: how far the written pages are behind the code               #
# --------------------------------------------------------------------------- #
def read_review() -> dict:
    try:
        return json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"commits": 0, "areas": {}}


def mark_reviewed() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_FILE.write_text(json.dumps({"commits": 0, "areas": {}, "reviewed": int(time.time())}), encoding="utf-8")
    print("docs-studio: marked the written pages as up to date")
    return 0


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=30, check=False,
                              encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def post_commit() -> int:
    if os.environ.get("SKIP_DOCS_HOOKS") == "1":
        return 0
    changed = [p for p in git("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--root", "HEAD").splitlines() if p]
    prefix = DOCS_DIR.name + "/"
    outside = [p for p in changed if not p.startswith(prefix)]
    review = read_review()
    if outside:
        review["commits"] = int(review.get("commits", 0)) + 1
        areas = review.setdefault("areas", {})
        for p in outside:
            top = p.split("/")[0] if "/" in p else "(root)"
            areas[top] = areas.get(top, 0) + 1
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        REVIEW_FILE.write_text(json.dumps(review), encoding="utf-8")
    # rebuild in the background so the commit returns at once
    detach([sys.executable, str(SITE_DIR / "build.py"), "--quiet"], STATE_DIR / "build.log")
    n = review.get("commits", 0)
    print(f"docs-studio: rebuilding the docs in the background ({n} commit{'s' if n != 1 else ''} since the written pages were reviewed)")
    return 0


def session_start() -> int:
    start(quiet=True)
    port = running()
    review = read_review()
    n = int(review.get("commits", 0))
    lines = []
    if port:
        lines.append(f"The project docs studio is running at http://localhost:{port} (diagrams, status board, whiteboard). Mention the link once if the user asks about docs.")
    if n >= 3:
        areas = ", ".join(f"{k} ({v})" for k, v in sorted(review.get("areas", {}).items(), key=lambda kv: -kv[1])[:5])
        lines.append(f"{n} commits have touched the code since the written docs pages were last reviewed (areas: {areas}). "
                     "When it fits the conversation, offer to refresh the pages with the docs-studio skill (`refresh`).")
    if lines:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": " ".join(lines)}}))
    return 0


# --------------------------------------------------------------------------- #
# Hosting                                                                      #
# --------------------------------------------------------------------------- #
def hosting(target: str) -> int:
    d = DOCS_DIR.name
    if target == "vercel":
        path = ROOT / "vercel.json"
        if path.exists():
            print(f"vercel.json exists. Set  \"outputDirectory\": \"{d}/site\"  in it yourself.")
            return 1
        path.write_text(json.dumps({"$schema": "https://openapi.vercel.sh/vercel.json", "framework": None, "buildCommand": None,
                                    "installCommand": None, "outputDirectory": f"{d}/site"}, indent=2) + "\n", encoding="utf-8")
        print("wrote vercel.json (boards are kept in each visitor's browser on Vercel; no whiteboard backend)")
        return 0
    if target == "netlify":
        toml = ROOT / "netlify.toml"
        if toml.exists():
            print(f"netlify.toml exists. Add:  [build] base = \"{d}\", publish = \"site\"  and  [functions] directory = \"netlify/functions\"")
            return 1
        toml.write_text(f'[build]\n  base = "{d}"\n  publish = "site"\n\n[functions]\n  directory = "netlify/functions"\n  node_bundler = "esbuild"\n', encoding="utf-8")
        fn = DOCS_DIR / "netlify" / "functions"
        fn.mkdir(parents=True, exist_ok=True)
        src = SITE_DIR / "hosting"
        (fn / "whiteboards.mjs").write_text((src / "whiteboards.mjs").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        pkg = DOCS_DIR / "package.json"
        if not pkg.exists():
            pkg.write_text((src / "package.json").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        print("wrote netlify.toml, docs/netlify/functions/whiteboards.mjs (shared whiteboards via Netlify Blobs)")
        print("The whiteboard API has no login: protect the site if boards are private.")
        return 0
    print("usage: studio.py hosting netlify|vercel")
    return 2


def icons() -> int:
    sys.path.insert(0, str(SITE_DIR))
    import blocks
    print(" ".join(blocks.ICON_NAMES))
    return 0


def changes() -> int:
    """What changed in the code since the written pages were last reviewed (for the `refresh` workflow)."""
    review = read_review()
    since = int(review.get("reviewed", 0))
    args = ["log", "--name-only", "--format=--- %h %cs %s"]
    args += [f"--since=@{since}"] if since else ["-n", "30"]
    log = git(*args)
    prefix = DOCS_DIR.name + "/"
    out: dict[str, list[str]] = {}
    head = ""
    for line in log.splitlines():
        if line.startswith("--- "):
            head = line[4:]
            out[head] = []
        elif line.strip() and head and not line.startswith(prefix):
            out[head].append(line.strip())
    shown = {k: v for k, v in out.items() if v}
    print(f"{len(shown)} commit(s) touching the code since the pages were last reviewed" + ("" if since else " (never reviewed: showing the last 30)"))
    for h, files in shown.items():
        tops = sorted({f.split('/')[0] if '/' in f else '(root)' for f in files})
        more = " ..." if len(files) > 8 else ""
        print(f"- {h}")
        print(f"    areas: {', '.join(tops)}")
        print(f"    files: {', '.join(files[:8])}{more}")
    return 0


def presets_list() -> int:
    sys.path.insert(0, str(SITE_DIR))
    import presets
    from presets.common import ANIMATIONS
    presets.load_custom(SITE_DIR / "presets_custom")
    groups: dict[str, list] = {}
    for p in presets.catalog():
        groups.setdefault(p.group, []).append(p)
    for g, ps in groups.items():
        print(f"\n[{g}]")
        for p in ps:
            al = f" (also: {', '.join(p.aliases)})" if p.aliases else ""
            print(f"  :::{p.name}{al}  default animation: {p.default_anim}\n      {p.summary}\n      syntax: {p.syntax}")
    print("\n[animations]  add anim=NAME to any diagram, or static to turn it off")
    for k, v in ANIMATIONS.items():
        print(f"  {k}: {v}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("--open", action="store_true"); s.add_argument("--quiet", action="store_true")
    for name in ("stop", "status", "url", "check", "presets", "reviewed", "icons", "changes"):
        sub.add_parser(name)
    b = sub.add_parser("build"); b.add_argument("--no-scan", action="store_true")
    h = sub.add_parser("hosting"); h.add_argument("target")
    k = sub.add_parser("hook"); k.add_argument("event", choices=["session-start", "post-commit"])
    a = ap.parse_args(argv)
    try:
        if a.cmd == "start":
            return start(a.open, a.quiet)
        if a.cmd == "stop":
            return stop()
        if a.cmd in ("status", "url"):
            return status()
        if a.cmd == "build":
            return run_build(["--no-scan"] if a.no_scan else [])
        if a.cmd == "check":
            return run_build(["--check"])
        if a.cmd == "presets":
            return presets_list()
        if a.cmd == "icons":
            return icons()
        if a.cmd == "changes":
            return changes()
        if a.cmd == "reviewed":
            return mark_reviewed()
        if a.cmd == "hosting":
            return hosting(a.target)
        if a.cmd == "hook":
            return session_start() if a.event == "session-start" else post_commit()
    except Exception as exc:                                                # noqa: BLE001
        if a.cmd == "hook":                       # hooks must never break a session or a commit
            print(f"docs-studio: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 0
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
