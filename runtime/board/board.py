#!/usr/bin/env python3
"""The status board: the single reference for what is planned, running, merged and deployed.

The source of truth is `docs/board/board.yaml` (versioned). This module is the only code that
reads, validates and writes it: the docs site build, `docs/site/serve.py` (the owner's editable
board) and the small CLI below all go through it, so the file stays valid and its layout stays
deterministic (stable ordering, one canonical text form) and diffs stay small.

    python docs/board/board.py list [--column running] [--package ORCH] [--json]
    python docs/board/board.py show <id>
    python docs/board/board.py add --title "..." --column planned [--package F2] [--owner agent] ...
    python docs/board/board.py move <id> <column> [--position N]
    python docs/board/board.py update <id> [--title ..] [--description ..] [--package ..] [--column ..]
                                          [--owner ..] [--branch ..] [--sha ..] [--labels a,b] [--links "title=url,url"]
    python docs/board/board.py remove <id>      # soft delete: the card moves into `archived`
    python docs/board/board.py restore <id>
    python docs/board/board.py columns          # the column ids

Every write keeps the card history (created, moved, archived, restored) and bumps `version`.
`--by agent|integrator|owner` says who is writing (default: agent). `--file` picks another file.

File shape (version 1): `version`, `columns` (id, title, status), `cards` (id `t_...`, title, package,
column, order, owner, labels, branch, sha, links, created, updated, description, history) and
`archived` (cards that were deleted; never hard-deleted). Owner edits made through serve.py are
authoritative: never overwrite them, merge.

Needs Python 3.9+ and PyYAML. Nothing here touches the network or git.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:                                                    # pragma: no cover
    sys.exit("board.py needs PyYAML (pip install pyyaml)")

BOARD_PATH = Path(__file__).resolve().with_name("board.yaml")
OWNERS = ("owner", "agent", "integrator")
STATUSES = ("planned", "running", "done", "blocked")
EVENTS = ("created", "moved", "archived", "restored")
DEFAULT_COLUMNS = [
    {"id": "backlog", "title": "Backlog", "status": "planned"},
    {"id": "planned", "title": "Planned", "status": "planned"},
    {"id": "running", "title": "Running", "status": "running"},
    {"id": "review", "title": "Review", "status": "running"},
    {"id": "merged", "title": "Merged", "status": "done"},
    {"id": "deployed", "title": "Deployed", "status": "done"},
    {"id": "blocked", "title": "Blocked", "status": "blocked"},
]
MAX_BYTES = 1024 * 1024
MAX_CARDS = 1000
HISTORY_KEEP = 30

CARD_KEYS = ("id", "title", "package", "column", "order", "owner", "labels", "branch", "sha", "links",
             "created", "updated", "description", "history")
ARCHIVED_KEYS = CARD_KEYS[:12] + ("archived_at",) + CARD_KEYS[12:]
OPTIONAL_TEXT = ("package", "branch", "sha", "description")

COLUMN_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
CARD_ID = re.compile(r"^t_[a-z0-9]{4,12}$")
LABEL = re.compile(r"^[a-z0-9][a-z0-9 ._/-]{0,29}$")
SHA = re.compile(r"^[0-9a-f]{4,12}$")
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
BAD_CHARS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\ufffe\uffff]")


class BoardError(ValueError):
    """The board is invalid; `.errors` lists every problem."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:5]) + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""))
        self.errors = errors


# --------------------------------------------------------------------------- #
# Small helpers                                                                #
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_card_id(taken: set[str]) -> str:
    while True:
        cid = "t_" + secrets.token_hex(3)
        if cid not in taken:
            return cid


def default_board() -> dict[str, Any]:
    return {"version": 0, "columns": copy.deepcopy(DEFAULT_COLUMNS), "cards": [], "archived": []}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"^[^a-z]+", "", slug)[:32].strip("-")
    return slug or "column"


# --------------------------------------------------------------------------- #
# Validation                                                                   #
# --------------------------------------------------------------------------- #
def _text_ok(value: Any, where: str, errs: list[str], *, limit: int, multiline: bool = False, required: bool = False) -> None:
    if not isinstance(value, str):
        errs.append(f"{where}: must be text")
        return
    if required and not value.strip():
        errs.append(f"{where}: must not be empty")
    if len(value) > limit:
        errs.append(f"{where}: longer than {limit} characters")
    if BAD_CHARS.search(value.replace("\n", "") if multiline else value):
        errs.append(f"{where}: contains control characters")
    if not multiline and "\n" in value:
        errs.append(f"{where}: must be one line")


def _check_card(card: Any, where: str, columns: set[str], errs: list[str], *, archived: bool) -> None:
    if not isinstance(card, dict):
        errs.append(f"{where}: must be a mapping")
        return
    allowed = set(ARCHIVED_KEYS if archived else CARD_KEYS)
    for key in sorted(set(card) - allowed):
        errs.append(f"{where}: unknown field '{key}'")
    cid = card.get("id")
    if not isinstance(cid, str) or not CARD_ID.match(cid):
        errs.append(f"{where}: id must look like t_ab12cd")
    where = f"{where} ({cid})" if isinstance(cid, str) else where
    _text_ok(card.get("title"), f"{where}.title", errs, limit=200, required=True)
    for key, limit in (("package", 40), ("branch", 100), ("description", 20000)):
        if card.get(key) not in (None, ""):
            _text_ok(card[key], f"{where}.{key}", errs, limit=limit, multiline=key == "description")
    if card.get("branch") and re.search(r"\s", str(card["branch"])):
        errs.append(f"{where}.branch: must not contain spaces")
    if card.get("sha") and not (isinstance(card["sha"], str) and SHA.match(card["sha"])):
        errs.append(f"{where}.sha: use the short hex form (4 to 12 characters)")
    if card.get("column") not in columns:
        errs.append(f"{where}.column: '{card.get('column')}' is not a column")
    if not isinstance(card.get("order"), int) or isinstance(card.get("order"), bool) or card["order"] < 0:
        errs.append(f"{where}.order: must be a whole number >= 0")
    if card.get("owner") not in OWNERS:
        errs.append(f"{where}.owner: one of {', '.join(OWNERS)}")
    labels = card.get("labels", [])
    if not isinstance(labels, list) or len(labels) > 12:
        errs.append(f"{where}.labels: a list of at most 12")
    else:
        for lab in labels:
            if not isinstance(lab, str) or not LABEL.match(lab):
                errs.append(f"{where}.labels: '{lab}' (lowercase letters, digits, space . _ / -, up to 30)")
    links = card.get("links", [])
    if not isinstance(links, list) or len(links) > 12:
        errs.append(f"{where}.links: a list of at most 12")
    else:
        for link in links:
            if not isinstance(link, dict) or set(link) - {"title", "url"} or not link.get("url"):
                errs.append(f"{where}.links: each link needs a url (and optionally a title)")
                continue
            url, title = link["url"], link.get("title", "")
            _text_ok(url, f"{where}.links.url", errs, limit=500)
            _text_ok(title, f"{where}.links.title", errs, limit=80)
            if isinstance(url, str) and (re.search(r"\s", url) or (SCHEME.match(url) and not re.match(r"^https?://", url, re.I))):
                errs.append(f"{where}.links: '{url[:40]}' must be an http(s) address or a path in the repository")
    for key in ("created", "updated") + (("archived_at",) if archived else ()):
        if not (isinstance(card.get(key), str) and TS.match(card[key])):
            errs.append(f"{where}.{key}: must be a UTC time like 2026-10-05T09:30:00Z")
    history = card.get("history", [])
    if not isinstance(history, list):
        errs.append(f"{where}.history: must be a list")
        return
    for ev in history:
        if not isinstance(ev, dict) or set(ev) - {"at", "event", "from", "to", "by"}:
            errs.append(f"{where}.history: entries have at, event, from, to, by")
        elif ev.get("event") not in EVENTS or not (isinstance(ev.get("at"), str) and TS.match(ev["at"])) or ev.get("by") not in OWNERS:
            errs.append(f"{where}.history: entry {ev} is malformed")


def validate(data: Any) -> list[str]:
    """Every problem with a board (already filled by `fill_defaults`), or an empty list."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["board: must be a mapping"]
    for key in sorted(set(data) - {"version", "columns", "cards", "archived"}):
        errs.append(f"board: unknown field '{key}'")
    if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool) or data["version"] < 0:
        errs.append("version: must be a whole number >= 0")
    columns = data.get("columns")
    col_ids: set[str] = set()
    if not isinstance(columns, list) or not 1 <= len(columns) <= 30:
        errs.append("columns: between 1 and 30 columns")
        columns = []
    for i, col in enumerate(columns):
        where = f"columns[{i}]"
        if not isinstance(col, dict) or set(col) - {"id", "title", "status"}:
            errs.append(f"{where}: fields are id, title, status")
            continue
        cid = col.get("id")
        if not isinstance(cid, str) or not COLUMN_ID.match(cid):
            errs.append(f"{where}.id: lowercase letters, digits and dashes, starting with a letter")
        elif cid in col_ids:
            errs.append(f"{where}.id: '{cid}' is used twice")
        else:
            col_ids.add(cid)
        _text_ok(col.get("title"), f"{where}.title", errs, limit=40, required=True)
        if col.get("status") not in STATUSES:
            errs.append(f"{where}.status: one of {', '.join(STATUSES)}")
    seen: set[str] = set()
    for part, archived in (("cards", False), ("archived", True)):
        items = data.get(part)
        if not isinstance(items, list):
            errs.append(f"{part}: must be a list")
            continue
        if len(items) > MAX_CARDS:
            errs.append(f"{part}: more than {MAX_CARDS} cards")
            continue
        for i, card in enumerate(items):
            _check_card(card, f"{part}[{i}]", col_ids, errs, archived=archived)
            cid = card.get("id") if isinstance(card, dict) else None
            if isinstance(cid, str):
                if cid in seen:
                    errs.append(f"{part}[{i}]: id {cid} is used twice")
                seen.add(cid)
    return errs


# --------------------------------------------------------------------------- #
# Filling, normalising, history                                                #
# --------------------------------------------------------------------------- #
def _stamp(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


def _clean_text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _clean_description(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    lines = [ln.rstrip() for ln in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def fill_defaults(raw: Any, now: str | None = None) -> Any:
    """Tolerant first pass: copies the input, fixes types a person or a browser may get wrong and
    fills what is missing. It never invents data that would hide a mistake (unknown fields and bad
    values are left for `validate`)."""
    if not isinstance(raw, dict):
        return raw
    now = now or now_iso()
    data = copy.deepcopy(raw)
    data["version"] = data.get("version", 0)
    data.setdefault("columns", copy.deepcopy(DEFAULT_COLUMNS))
    data["cards"] = data.get("cards") if data.get("cards") is not None else []
    data["archived"] = data.get("archived") if data.get("archived") is not None else []
    for col in data["columns"] if isinstance(data["columns"], list) else []:
        if isinstance(col, dict):
            col["title"] = _clean_text(col.get("title", col.get("id")))
            col.setdefault("status", "planned")
    for part in ("cards", "archived"):
        if not isinstance(data[part], list):
            continue
        for card in data[part]:
            if not isinstance(card, dict):
                continue
            for key in ("title", "package", "branch", "sha", "column", "owner"):
                if key in card:
                    card[key] = _clean_text(card[key])
            if "sha" in card and isinstance(card["sha"], str):
                card["sha"] = card["sha"].lower()
            if "description" in card:
                card["description"] = _clean_description(card["description"])
            for key in OPTIONAL_TEXT:
                if card.get(key) is None:
                    card.pop(key, None)
            card.setdefault("owner", "agent")
            card.setdefault("order", 10 ** 6)
            labels = card.get("labels")
            if labels is None:
                card["labels"] = []
            elif isinstance(labels, list):
                card["labels"] = list(dict.fromkeys(str(x).strip().lower() for x in labels if str(x).strip()))
            links = card.get("links")
            if links is None:
                card["links"] = []
            elif isinstance(links, list):
                fixed = []
                for link in links:
                    if isinstance(link, str):
                        link = {"url": link}
                    if isinstance(link, dict):
                        link = {k: _clean_text(v) for k, v in link.items() if v not in (None, "")}
                    fixed.append(link)
                card["links"] = fixed
            card["history"] = card.get("history") if card.get("history") is not None else []
            for key in ("created", "updated", "archived_at"):
                if key in card:
                    card[key] = _stamp(card[key])
            card.setdefault("created", now)
            card.setdefault("updated", card["created"])
            if part == "archived":
                card.setdefault("archived_at", card["updated"])
            for ev in card["history"] if isinstance(card["history"], list) else []:
                if isinstance(ev, dict):
                    if "at" in ev:
                        ev["at"] = _stamp(ev["at"])
                    if ev.get("from") is None:
                        ev.pop("from", None)
                    if ev.get("to") is None:
                        ev.pop("to", None)
    return data


def _canon(card: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """A card with only the known fields, in file order; empty optional text is left out."""
    out: dict[str, Any] = {}
    for key in keys:
        value = card.get(key)
        if key in OPTIONAL_TEXT and not value:
            continue
        if key in ("labels", "links", "history"):
            value = value or []
        if value is None:
            continue
        out[key] = value
    return out


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Canonical content of a valid board: columns in order, cards sorted by column then order and
    renumbered 1..n per column, archived sorted by archive time, history trimmed."""
    col_index = {c["id"]: i for i, c in enumerate(data["columns"])}
    cards = sorted(copy.deepcopy(data["cards"]), key=lambda c: (col_index[c["column"]], c["order"], c["id"]))
    counters: dict[str, int] = {}
    for card in cards:
        counters[card["column"]] = counters.get(card["column"], 0) + 1
        card["order"] = counters[card["column"]]
    archived = sorted(copy.deepcopy(data["archived"]), key=lambda c: (c["archived_at"], c["id"]))
    for card in cards + archived:
        card["history"] = card["history"][-HISTORY_KEEP:]
    return {
        "version": data["version"],
        "columns": [{"id": c["id"], "title": c["title"], "status": c["status"]} for c in data["columns"]],
        "cards": [_canon(c, CARD_KEYS) for c in cards],
        "archived": [_canon(c, ARCHIVED_KEYS) for c in archived],
    }


def parse_data(raw: Any, now: str | None = None) -> dict[str, Any]:
    """Raw mapping (from YAML or JSON) -> a validated, canonical board. Raises BoardError."""
    data = fill_defaults(raw, now)
    errs = validate(data)
    if errs:
        raise BoardError(errs)
    return normalize(data)


def parse_text(text: str) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BoardError([f"board.yaml is not valid YAML: {str(exc).splitlines()[0] if str(exc) else 'error'}"]) from exc
    return parse_data(default_board() if raw is None else raw)


def _content(card: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in card.items() if k not in ("order", "updated", "created", "history", "archived_at")}


def apply_changes(old: dict[str, Any], new: dict[str, Any], by: str = "owner", now: str | None = None) -> dict[str, Any]:
    """The board to store when `new` (valid, canonical) replaces `old` (the stored one).

    Server side truth: history, `created`, `updated` and `archived_at` come from here, never from
    the writer. A card missing from `new` is archived, never lost. `version` goes up by one when
    anything changed."""
    now = now or now_iso()
    out = copy.deepcopy(new)
    old_cards = {c["id"]: c for c in old["cards"]}
    old_arch = {c["id"]: c for c in old["archived"]}
    present = {c["id"] for c in out["cards"]} | {c["id"] for c in out["archived"]}
    for cid, prev in {**old_arch, **old_cards}.items():
        if cid not in present:
            gone = copy.deepcopy(prev)
            gone["archived_at"] = prev.get("archived_at", now)
            if cid in old_cards:
                gone["archived_at"] = now
                gone["history"] = gone["history"] + [{"at": now, "event": "archived", "by": by}]
            out["archived"].append(gone)
    for part in ("cards", "archived"):
        for card in out[part]:
            cid = card["id"]
            prev = old_cards.get(cid) or old_arch.get(cid)
            if prev is None:
                card["created"] = card["updated"] = now
                card["history"] = [{"at": now, "event": "created", "to": card["column"], "by": by}]
                if part == "archived":
                    card["archived_at"] = now
                    card["history"].append({"at": now, "event": "archived", "by": by})
                continue
            history = list(prev.get("history", []))
            card["created"] = prev["created"]
            card["updated"] = prev["updated"]
            was_archived = cid in old_arch
            if part == "cards" and was_archived:
                history.append({"at": now, "event": "restored", "to": card["column"], "by": by})
                card["updated"] = now
            elif part == "cards" and prev["column"] != card["column"]:
                history.append({"at": now, "event": "moved", "from": prev["column"], "to": card["column"], "by": by})
                card["updated"] = now
            elif part == "cards" and _content(prev) != _content(card):
                card["updated"] = now
            elif part == "archived" and not was_archived:
                history.append({"at": now, "event": "archived", "by": by})
                card["updated"] = now
            elif part == "archived" and _content(prev) != _content(card):
                card["updated"] = now
            card["history"] = history
            if part == "archived":
                card["archived_at"] = prev.get("archived_at") if was_archived else now
    out = normalize(out)
    out["version"] = old["version"]
    if _body(out) != _body(old):
        out["version"] = old["version"] + 1
    return out


def _body(board: dict[str, Any]) -> str:
    return dumps(board | {"version": 0})


# --------------------------------------------------------------------------- #
# Canonical text form                                                          #
# --------------------------------------------------------------------------- #
_PLAIN = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]{0,79}$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "y", "n"}


def _quote(value: str) -> str:
    return (json.dumps(value, ensure_ascii=False)
            .replace("\u0085", "\\u0085").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    value = str(value)
    return value if _PLAIN.match(value) and value.lower() not in _RESERVED else _quote(value)


def _text_lines(key: str, value: str, indent: str) -> list[str]:
    block = ("\n" in value and "\t" not in value and not value[0].isspace()
             and all(ln == ln.rstrip() for ln in value.split("\n")))
    if not block:
        return [f"{indent}{key}: {_quote(value)}"]
    return [f"{indent}{key}: |-"] + [f"{indent}  {ln}" if ln else "" for ln in value.split("\n")]


def _card_lines(card: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    first = True
    for key in ARCHIVED_KEYS:
        if key not in card or card[key] in ("", None) or card[key] == []:
            continue
        value = card[key]
        lead = "  - " if first else "    "
        first = False
        if key == "labels":
            lines.append(f"{lead}labels: [{', '.join(_scalar(v) for v in value)}]")
        elif key == "links":
            lines.append(f"{lead}links:")
            for link in value:
                parts = [f"{k}: {_quote(link[k]) if k == 'title' else _scalar(link[k])}" for k in ("title", "url") if link.get(k)]
                lines.append(f"      - {parts[0]}")
                lines.extend(f"        {p}" for p in parts[1:])
        elif key == "history":
            lines.append(f"{lead}history:")
            for ev in value:
                parts = [f"{k}: {_quote(ev[k]) if k == 'at' else _scalar(ev[k])}" for k in ("at", "event", "from", "to", "by") if ev.get(k)]
                lines.append(f"      - {parts[0]}")
                lines.extend(f"        {p}" for p in parts[1:])
        elif key == "description":
            lines.extend(_text_lines(key, value, "    "))
        elif key in ("title", "created", "updated", "archived_at"):
            lines.append(f"{lead}{key}: {_quote(value)}")
        else:
            lines.append(f"{lead}{key}: {_scalar(value)}")
    return lines


def dumps(data: dict[str, Any]) -> str:
    """The one text form of a canonical board. Plain scalars where safe, JSON-quoted otherwise,
    block text for multi-line descriptions, a fixed key order, LF line ends, final newline."""
    out = [f"version: {data['version']}", "columns:"]
    for col in data["columns"]:
        out += [f"  - id: {_scalar(col['id'])}", f"    title: {_quote(col['title'])}", f"    status: {_scalar(col['status'])}"]
    for part in ("cards", "archived"):
        if not data[part]:
            out.append(f"{part}: []")
            continue
        out.append(f"{part}:")
        for card in data[part]:
            out.extend(_card_lines(card))
    return "\n".join(out) + "\n"


def etag_of(board: dict[str, Any]) -> str:
    return hashlib.sha1(dumps(board).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Files                                                                        #
# --------------------------------------------------------------------------- #
def load(path: Path | str = BOARD_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return normalize(default_board())
    return parse_text(path.read_text(encoding="utf-8"))


def write_text(path: Path | str, text: str) -> None:
    """Atomic write with LF line ends."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".board-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save(path: Path | str, board: dict[str, Any]) -> str:
    text = dumps(board)
    write_text(path, text)
    return text


# --------------------------------------------------------------------------- #
# Operations (pure: they change the board they are given)                      #
# --------------------------------------------------------------------------- #
def find(board: dict[str, Any], card_id: str, *, archived: bool = False) -> dict[str, Any]:
    for card in board["archived" if archived else "cards"]:
        if card["id"] == card_id:
            return card
    raise BoardError([f"no {'archived ' if archived else ''}card with id {card_id}"])


def _column_ids(board: dict[str, Any]) -> list[str]:
    return [c["id"] for c in board["columns"]]


def place(board: dict[str, Any], card: dict[str, Any], column: str, position: int | None) -> None:
    """Put `card` in `column` at 1-based `position` (default: the end), renumbering that column."""
    if column not in _column_ids(board):
        raise BoardError([f"'{column}' is not a column (columns: {', '.join(_column_ids(board))})"])
    peers = sorted((c for c in board["cards"] if c["column"] == column and c is not card), key=lambda c: (c["order"], c["id"]))
    index = len(peers) if position is None else max(0, min(position - 1, len(peers)))
    peers.insert(index, card)
    card["column"] = column
    for i, c in enumerate(peers, 1):
        c["order"] = i


def op_add(board: dict[str, Any], *, title: str, column: str, position: int | None = None, **fields: Any) -> dict[str, Any]:
    taken = {c["id"] for c in board["cards"] + board["archived"]}
    card: dict[str, Any] = {"id": new_card_id(taken), "title": title, "column": column, "order": 10 ** 6}
    card.update({k: v for k, v in fields.items() if v not in (None, "")})
    board["cards"].append(card)
    place(board, card, column, position)
    return card


def op_move(board: dict[str, Any], card_id: str, column: str, position: int | None = None) -> dict[str, Any]:
    card = find(board, card_id)
    place(board, card, column, position)
    return card


def op_update(board: dict[str, Any], card_id: str, **fields: Any) -> dict[str, Any]:
    card = find(board, card_id)
    column = fields.pop("column", None)
    for key, value in fields.items():
        if key not in ("title", "package", "owner", "branch", "sha", "description", "labels", "links"):
            raise BoardError([f"cannot update '{key}'"])
        if value is None:
            continue
        if value in ("", []):
            if key == "title":
                raise BoardError(["title must not be empty"])
            card.pop(key, None)
            if key in ("labels", "links"):
                card[key] = []
        else:
            card[key] = value
    if column and column != card["column"]:
        place(board, card, column, None)
    return card


def op_remove(board: dict[str, Any], card_id: str) -> dict[str, Any]:
    card = find(board, card_id)
    board["cards"].remove(card)
    card["archived_at"] = now_iso()
    board["archived"].append(card)
    return card


def op_restore(board: dict[str, Any], card_id: str) -> dict[str, Any]:
    card = find(board, card_id, archived=True)
    board["archived"].remove(card)
    card.pop("archived_at", None)
    board["cards"].append(card)
    place(board, card, card["column"] if card["column"] in _column_ids(board) else board["columns"][0]["id"], None)
    return card


def mutate(path: Path | str, fn: Any, by: str = "agent") -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the file, apply `fn(board)` to a copy, validate, add history, write. Returns (card, board)."""
    old = load(path)
    work = copy.deepcopy(old)
    card = fn(work)
    final = apply_changes(old, parse_data(work), by=by)
    save(path, final)
    return card, final


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _parse_links(text: str) -> list[dict[str, str]]:
    links = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        title, sep, url = part.partition("=")
        if sep and not re.match(r"^https?:", title, re.I):
            links.append({"title": title.strip(), "url": url.strip()})
        else:
            links.append({"url": part})
    return links


def _parse_labels(text: str) -> list[str]:
    return [p.strip().lower() for p in text.split(",") if p.strip()]


def _row(card: dict[str, Any]) -> str:
    return f"{card['id']:<10} {card['column']:<9} {card.get('package', '-'):<8} {card['owner']:<10} {card['title']}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="board.py", description="Read and update the status board (docs/board/board.yaml).")
    p.add_argument("--file", type=Path, default=BOARD_PATH, help="board file (default: docs/board/board.yaml)")
    p.add_argument("--by", choices=OWNERS, default="agent", help="who is writing, for the card history")
    # The same two options are accepted after the command too (`move <id> review --by integrator`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--file", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--by", choices=OWNERS, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **kw: _add(*a, parents=[common], **kw)          # type: ignore[method-assign]

    s = sub.add_parser("list", help="list cards, in board order")
    s.add_argument("--column")
    s.add_argument("--package")
    s.add_argument("--owner", choices=OWNERS)
    s.add_argument("--label")
    s.add_argument("--archived", action="store_true", help="list deleted cards instead")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("show", help="show one card in full")
    s.add_argument("id")

    s = sub.add_parser("columns", help="list the column ids")

    s = sub.add_parser("add", help="add a card (prints its id)")
    s.add_argument("--title", required=True)
    s.add_argument("--column", required=True)
    s.add_argument("--package")
    s.add_argument("--description")
    s.add_argument("--owner", choices=OWNERS, default="agent")
    s.add_argument("--branch")
    s.add_argument("--sha")
    s.add_argument("--labels")
    s.add_argument("--links")
    s.add_argument("--position", type=int)

    s = sub.add_parser("move", help="move a card to a column (end of the column unless --position)")
    s.add_argument("id")
    s.add_argument("column")
    s.add_argument("--position", type=int)

    s = sub.add_parser("update", help="change fields of a card; an empty value clears an optional field")
    s.add_argument("id")
    for field in ("title", "description", "package", "branch", "sha", "column"):
        s.add_argument(f"--{field}")
    s.add_argument("--owner", choices=OWNERS)
    s.add_argument("--labels", help="comma separated; replaces the labels")
    s.add_argument("--links", help="comma separated: url or title=url; replaces the links")

    s = sub.add_parser("remove", help="soft delete: the card moves into `archived`")
    s.add_argument("id")
    s = sub.add_parser("restore", help="bring an archived card back")
    s.add_argument("id")
    return p


def run(args: argparse.Namespace, out: Any = None) -> int:
    out = out or sys.stdout
    path = args.file
    if args.cmd == "columns":
        for col in load(path)["columns"]:
            print(f"{col['id']:<10} {col['status']:<8} {col['title']}", file=out)
        return 0
    if args.cmd in ("list", "show"):
        board = load(path)
        if args.cmd == "show":
            try:
                card = find(board, args.id)
            except BoardError:
                card = find(board, args.id, archived=True)
            print(json.dumps(card, indent=2, ensure_ascii=False), file=out)
            return 0
        cards = board["archived" if args.archived else "cards"]
        if args.column:
            cards = [c for c in cards if c["column"] == args.column]
        if args.package:
            cards = [c for c in cards if c.get("package", "").lower() == args.package.lower()]
        if args.owner:
            cards = [c for c in cards if c["owner"] == args.owner]
        if args.label:
            cards = [c for c in cards if args.label.lower() in c["labels"]]
        if args.json:
            print(json.dumps(cards, indent=2, ensure_ascii=False), file=out)
        else:
            for card in cards:
                print(_row(card), file=out)
        return 0
    if args.cmd == "add":
        fields = {"package": args.package, "description": args.description, "owner": args.owner, "branch": args.branch,
                  "sha": args.sha, "labels": _parse_labels(args.labels or ""), "links": _parse_links(args.links or "")}
        card, _ = mutate(path, lambda b: op_add(b, title=args.title.strip(), column=args.column, position=args.position, **fields), args.by)
        print(card["id"], file=out)
    elif args.cmd == "move":
        card, _ = mutate(path, lambda b: op_move(b, args.id, args.column, args.position), args.by)
        print(f"{args.id} -> {args.column}", file=out)
    elif args.cmd == "update":
        fields = {k: getattr(args, k) for k in ("title", "description", "package", "branch", "sha", "column", "owner")}
        if args.labels is not None:
            fields["labels"] = _parse_labels(args.labels) or []
        if args.links is not None:
            fields["links"] = _parse_links(args.links) or []
        if not any(v is not None for v in fields.values()):
            raise BoardError(["nothing to update: pass at least one --field"])
        mutate(path, lambda b: op_update(b, args.id, **fields), args.by)
        print(f"{args.id} updated", file=out)
    elif args.cmd == "remove":
        mutate(path, lambda b: op_remove(b, args.id), args.by)
        print(f"{args.id} archived", file=out)
    elif args.cmd == "restore":
        mutate(path, lambda b: op_restore(b, args.id), args.by)
        print(f"{args.id} restored", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except BoardError as exc:
        for err in exc.errors:
            print(f"board: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
