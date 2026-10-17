#!/usr/bin/env python3
"""Serve the docs with the editable status board and the whiteboard, saving into the repository.

    python docs/site/serve.py [--port N] [--commit] [--repo PATH]      (studio.py start does this for you)

The board page reads and writes `docs/board/board.yaml` through `GET/PUT /api/board`; whiteboards live in
`docs/whiteboard/`. With --commit (or "server": {"commit_edits": true} in studio.json) every accepted write
is committed on its own ("Board: owner edit"); only that one file is ever committed. Default: files are
written, nothing is committed.

Safe by construction: binds 127.0.0.1 only, accepts only local Host and Origin headers, refuses
bodies over 1 MB, requires JSON and an If-Match version (a concurrent edit gets a 409 with the
current board so the page can merge), validates everything through docs/board/board.py, and serves
nothing but index.html. Standard library and PyYAML only; no network.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SITE_DIR = Path(__file__).resolve().parent
DOCS_DIR = SITE_DIR.parent
DEFAULT_ROOT = DOCS_DIR.parent
sys.path.insert(0, str(DOCS_DIR / "board"))
import board as boardlib                                               # noqa: E402

BIND = "127.0.0.1"
DEFAULT_PORT = 0
MAX_BODY = 1024 * 1024
COMMIT_MESSAGE = "Board: owner edit"
LOCAL_NAMES = {"127.0.0.1", "localhost", "::1"}


def _host_name(netloc: str) -> str:
    """The host part of a Host header or URL authority ("[::1]:80" -> "::1")."""
    host = netloc.rsplit("@", 1)[-1]
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else ""
    return host.split(":", 1)[0]


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Only the local machine may talk to the API: a local Host (stops DNS rebinding) and, when the
    browser sends one, a local http Origin. `Origin: null` (a file:// page, a sandbox) is refused."""
    if not host or _host_name(host).lower() not in LOCAL_NAMES:
        return False
    if origin is None:
        return True
    parts = urlsplit(origin)
    return parts.scheme == "http" and _host_name(parts.netloc).lower() in LOCAL_NAMES


class GitCommitter:
    """Commits one file, and only that file, in the checkout. Never raises."""

    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled and shutil.which("git") is not None

    def _git(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        # An empty hooks directory keeps owner edits quick and the working tree clean (the repository's
        # post-commit hook would rebuild the docs on every save).
        no_hooks = str(self.root / ".git-no-hooks")
        return subprocess.run(["git", "-C", str(self.root), "-c", f"core.hooksPath={no_hooks}", *args],
                              capture_output=True, text=True, timeout=timeout, check=False)

    def commit(self, path: Path, message: str = COMMIT_MESSAGE) -> tuple[bool, str, str]:
        """(committed, short sha, note). A deleted file is committed as its removal."""
        if not self.enabled:
            return False, "", "git is not available: saved to the file only"
        try:
            rel = path.resolve().relative_to(self.root.resolve()).as_posix()
            if self._git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
                return False, "", "not a git checkout: saved to the file only"
            added = self._git("add", "-A", "--", rel)
            if added.returncode != 0:
                return False, "", "git add failed: " + (added.stderr.strip().splitlines() or ["?"])[0]
            if self._git("diff", "--cached", "--quiet", "--", rel).returncode == 0:
                return False, "", "no change to commit"
            done = self._git("commit", "--only", "-m", message, "--", rel)
            if done.returncode != 0:
                return False, "", "git commit failed: " + ((done.stderr or done.stdout).strip().splitlines() or ["?"])[0]
            sha = self._git("rev-parse", "--short", "HEAD").stdout.strip()
            return True, sha, "committed"
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return False, "", f"git unavailable: {exc}"


class BoardService:
    """The board file, read and written under one lock."""

    def __init__(self, root: Path, commit: bool = True) -> None:
        self.root = root
        self.path = DOCS_DIR / "board" / "board.yaml"
        self.lock = threading.Lock()
        self.git = GitCommitter(root, commit)

    def read(self) -> dict[str, Any]:
        board = boardlib.load(self.path)
        return {"board": board, "etag": boardlib.etag_of(board), "path": f"{DOCS_DIR.name}/board/board.yaml", "commits": self.git.enabled}

    def write(self, payload: Any, if_match: str | None) -> tuple[int, dict[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("board"), dict):
            return 400, {"error": "invalid", "errors": ["the body must be {\"board\": {...}}"]}
        with self.lock:
            try:
                current = boardlib.load(self.path)
            except boardlib.BoardError as exc:
                return 500, {"error": "stored board is invalid", "errors": exc.errors}
            etag = boardlib.etag_of(current)
            if (if_match or "").strip().strip('"').removeprefix("W/").strip('"') != etag:
                return 409, {"error": "conflict", "board": current, "etag": etag}
            try:
                incoming = boardlib.parse_data(payload["board"])
            except boardlib.BoardError as exc:
                return 400, {"error": "invalid", "errors": exc.errors}
            final = boardlib.apply_changes(current, incoming, by="owner")
            changed = final["version"] != current["version"]
            committed, sha, note = False, "", "no change"
            if changed:
                boardlib.save(self.path, final)
                committed, sha, note = self.git.commit(self.path)
            return 200, {"board": final, "etag": boardlib.etag_of(final), "changed": changed,
                         "committed": committed, "commit": sha, "note": note}


WHITEBOARD_DIR = SITE_DIR / "whiteboard"
WB_MAX_BODY = 16 * 1024 * 1024                    # pasted images live inside the scene
WB_ID = re.compile(r"^wb_[a-z0-9]{4,40}$")
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".woff": "font/woff",
                ".ttf": "font/ttf", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
                ".txt": "text/plain; charset=utf-8"}


class WhiteboardService:
    """Owner doodles: one Excalidraw scene per file in docs/whiteboard/, committed to the repo."""

    def __init__(self, root: Path, git: GitCommitter) -> None:
        self.dir = DOCS_DIR / "whiteboard"
        self.git = git
        self.lock = threading.Lock()

    def _path(self, board_id: str) -> Path | None:
        return self.dir / f"{board_id}.excalidraw" if WB_ID.match(board_id or "") else None

    def list(self) -> dict[str, Any]:
        boards = []
        for path in sorted(self.dir.glob("wb_*.excalidraw")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            boards.append({"id": path.stem, "title": doc.get("title") or path.stem, "updated": doc.get("updated")})
        boards.sort(key=lambda b: b.get("updated") or "", reverse=True)
        return {"boards": boards, "commits": self.git.enabled}

    def read(self, board_id: str) -> tuple[int, dict[str, Any]]:
        path = self._path(board_id)
        if path is None or not path.is_file():
            return 404, {"error": "not found", "errors": ["no board with this id"]}
        return 200, json.loads(path.read_text(encoding="utf-8"))

    def write(self, board_id: str, payload: Any, commit: bool) -> tuple[int, dict[str, Any]]:
        path = self._path(board_id)
        if path is None:
            return 400, {"error": "invalid", "errors": ["a board id looks like wb_xxxx"]}
        if not isinstance(payload, dict) or not isinstance(payload.get("scene"), (dict, type(None))):
            return 400, {"error": "invalid", "errors": ["the body must be {title, scene}"]}
        doc = {"type": "excalidraw-board", "id": board_id, "title": str(payload.get("title") or "Untitled")[:120],
               "updated": str(payload.get("updated") or ""), "scene": payload.get("scene")}
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            committed, sha, note = (self.git.commit(path, "Whiteboard: owner edit") if commit
                                    else (False, "", "saved; committed with a later save"))
        return 200, {"saved": True, "committed": committed, "commit": sha, "note": note}

    def delete(self, board_id: str) -> tuple[int, dict[str, Any]]:
        path = self._path(board_id)
        if path is None or not path.is_file():
            return 404, {"error": "not found", "errors": ["no board with this id"]}
        with self.lock:
            path.unlink()
            committed, sha, note = self.git.commit(path, "Whiteboard: owner deleted a board")
        return 200, {"deleted": True, "committed": committed, "commit": sha, "note": note}


DEFAULT_ROOT_RUNTIME = [DEFAULT_ROOT]


class Handler(BaseHTTPRequestHandler):
    server_version = "BoardServe/1"
    protocol_version = "HTTP/1.0"      # one request per connection: error replies never leave an unread body behind
    service: BoardService
    whiteboards: "WhiteboardService"

    # -- plumbing ------------------------------------------------------- #
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Any, extra: dict[str, str] | None = None) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _local_only(self) -> bool:
        if not origin_allowed(self.headers.get("Origin"), self.headers.get("Host")):
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden", "errors": ["only local pages may use this server"]})
            return False
        if (self.headers.get("Sec-Fetch-Site") or "same-origin") == "cross-site":
            self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden", "errors": ["cross-site requests are refused"]})
            return False
        return True

    def _static(self, path: str) -> None:
        rel = path[len("/whiteboard/"):] or "index.html"
        base = WHITEBOARD_DIR.resolve()
        target = (base / rel).resolve()
        if base not in target.parents or not target.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, target.read_bytes(), STATIC_TYPES.get(target.suffix.lower(), "application/octet-stream"))

    # -- routes --------------------------------------------------------- #
    def do_HEAD(self) -> None:                                         # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:                                          # noqa: N802
        path = urlsplit(self.path).path
        if not self._local_only():
            return
        if path == "/api/board":
            try:
                self._json(200, self.service.read())
            except boardlib.BoardError as exc:
                self._json(500, {"error": "stored board is invalid", "errors": exc.errors})
        elif path == "/api/health":
            self._json(200, {"studio": True, "root": str(DEFAULT_ROOT_RUNTIME[0]), "docs": DOCS_DIR.name})
        elif path == "/api/version":
            page = SITE_DIR / "index.html"
            m = re.search(r'data-build="([0-9a-f]+)"', page.read_text(encoding="utf-8", errors="replace")[:600]) if page.exists() else None
            self._json(200, {"build": m.group(1) if m else ""})
        elif path == "/api/whiteboards":
            self._json(200, self.whiteboards.list())
        elif path.startswith("/api/whiteboards/"):
            status, body = self.whiteboards.read(path.rsplit("/", 1)[1])
            self._json(status, body)
        elif path.startswith("/whiteboard/"):
            self._static(path)
        elif path in ("/", "/index.html"):
            page = SITE_DIR / "index.html"
            if not page.exists():
                self._send(404, b"index.html is not built: run python docs/site/studio.py build", "text/plain; charset=utf-8")
            else:
                self._send(200, page.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_PUT(self) -> None:                                          # noqa: N802
        # Read the body first (bounded) so an early refusal never leaves unread bytes on the socket.
        length_header = self.headers.get("Content-Length")
        if length_header is None or not length_header.isdigit():
            self._json(411, {"error": "length required", "errors": ["send a Content-Length"]})
            return
        length = int(length_header)
        path = urlsplit(self.path).path
        limit = WB_MAX_BODY if path.startswith("/api/whiteboards/") else MAX_BODY
        if length > limit:
            self._json(413, {"error": "too large", "errors": [f"the limit is {limit // 1024} KB"]})
            return
        raw = self.rfile.read(length)
        if path.startswith("/api/whiteboards/"):
            if not self._local_only():
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self._json(400, {"error": "invalid", "errors": ["the body is not valid JSON"]})
                return
            status, body = self.whiteboards.write(path.rsplit("/", 1)[1], payload, self.headers.get("X-Commit") == "1")
            self._json(status, body)
            return
        if path != "/api/board":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        if not self._local_only():
            return
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            self._json(415, {"error": "unsupported", "errors": ["send application/json"]})
            return
        if self.headers.get("If-Match") is None:
            self._json(428, {"error": "precondition required", "errors": ["send the If-Match version of the board you edited"]})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._json(400, {"error": "invalid", "errors": ["the body is not valid JSON"]})
            return
        status, body = self.service.write(payload, self.headers.get("If-Match"))
        self._json(status, body)

    def do_DELETE(self) -> None:                                       # noqa: N802
        path = urlsplit(self.path).path
        if not path.startswith("/api/whiteboards/"):
            self._send(405, b"method not allowed", "text/plain; charset=utf-8", {"Allow": "GET, HEAD, PUT"})
            return
        if not self._local_only():
            return
        status, body = self.whiteboards.delete(path.rsplit("/", 1)[1])
        self._json(status, body)

    def do_POST(self) -> None:                                         # noqa: N802
        self._send(405, b"method not allowed", "text/plain; charset=utf-8", {"Allow": "GET, HEAD, PUT, DELETE"})

    do_PATCH = do_OPTIONS = do_POST


def make_server(root: Path = DEFAULT_ROOT, port: int = DEFAULT_PORT, commit: bool = False) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1 (port 0 picks a free one). Call serve_forever() on it."""
    DEFAULT_ROOT_RUNTIME[0] = root.resolve()
    service = BoardService(root.resolve(), commit)
    whiteboards = WhiteboardService(root.resolve(), service.git)
    handler = type("BoundHandler", (Handler,), {"service": service, "whiteboards": whiteboards})
    server = ThreadingHTTPServer((BIND, port), handler)
    server.daemon_threads = True
    server.board_service = service                                     # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the docs with a board that saves into the repository.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="0 picks a free port")
    parser.add_argument("--repo", type=Path, default=DEFAULT_ROOT, help="the project root (the folder that contains docs/)")
    parser.add_argument("--commit", action="store_true", help="git-commit each board / whiteboard save on its own")
    args = parser.parse_args(argv)
    try:
        server = make_server(args.repo, args.port, args.commit)
    except OSError as exc:
        print(f"Cannot listen on port {args.port}: {exc}. Try --port 0.", file=sys.stderr)
        return 1
    service: BoardService = server.board_service                      # type: ignore[attr-defined]
    port = server.server_address[1]
    print(f"Docs and board: http://localhost:{port}  (listening on {BIND} only)")
    print(f"Board file: {service.path}")
    print("Saves are committed one file at a time as '" + COMMIT_MESSAGE + "'." if service.git.enabled
          else "Saves are written to the file only (no git commit).")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
