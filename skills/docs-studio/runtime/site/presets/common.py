"""Shared plumbing for diagram presets: the registry, option parsing, text measuring, the figure wrapper.

A preset is a function `fn(ctx) -> str` registered with `@preset("name", ...)`. It reads `ctx.body` (the
directive's lines), `ctx.flags` / `ctx.kv` (the options on the directive line) and returns either an
`<svg>` element (it gets wrapped in an exportable, animatable <figure>) or ready HTML (`raw=True`).
Adding a preset never touches the builder: drop a file in `docs/site/presets_custom/` and decorate.
"""
from __future__ import annotations

import html
import itertools
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Inline = Callable[[str], str]

#: Filled from docs/studio.json by build.py: {"animation": "auto|none|<name>", ...}
CONFIG: dict[str, Any] = {"animation": "auto"}

ANIMATIONS = {
    "none": "no motion",
    "reveal": "elements fade in one after another when scrolled into view",
    "flow": "dashed lines march along every connection",
    "packets": "dots travel along the connections",
    "pulse": "nodes breathe in turn",
    "draw": "lines draw themselves, bars and slices grow",
    "trace": "connections light up one by one, in order, on a loop",
    "glow": "nodes glow softly in turn",
}

_ids = itertools.count(1)


def uid(prefix: str = "pv") -> str:
    return f"{prefix}{next(_ids)}"


def reset_ids() -> None:
    """Called once per build so ids are the same on every build (no churn in git)."""
    global _ids
    _ids = itertools.count(1)


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def fmt(x: float) -> str:
    """Compact number for SVG attributes."""
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


# --------------------------------------------------------------------------- #
# Text                                                                         #
# --------------------------------------------------------------------------- #
def tw(text: str, size: float = 13, bold: bool = False) -> float:
    """Approximate rendered width of `text` in px (system UI font)."""
    return len(text) * size * (0.58 if bold else 0.54)


def wrap(text: str, width_px: float, size: float = 13, bold: bool = False, max_lines: int = 0) -> list[str]:
    per = max(4, int(width_px / (size * (0.58 if bold else 0.54))))
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > per:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    lines = lines or [""]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(". ") + "…"
    return lines


def text_el(x: float, y: float, lines: list[str], cls: str, line_h: float = 15, anchor: str = "start") -> str:
    out = []
    for k, ln in enumerate(lines):
        out.append(f'<text class="{cls}" x="{fmt(x)}" y="{fmt(y + k * line_h)}" text-anchor="{anchor}">{esc(ln)}</text>')
    return "".join(out)


def fields(line: str, count: int) -> list[str]:
    """`a | b | c` split on a pipe with spaces around it; padded to `count` fields."""
    parts = [p.strip() for p in re.split(r"(?<=\s)\|(?=\s|$)", line.strip(), maxsplit=count - 1)]
    return parts + [""] * (count - len(parts))


def items(body: list[str]) -> list[str]:
    """List items (`- text`), continuation lines joined to the item."""
    out: list[str] = []
    for raw in body:
        m = re.match(r"^\s*[-*]\s+(.*)$", raw)
        if m:
            out.append(m.group(1).strip())
        elif raw.strip() and out:
            out[-1] += " " + raw.strip()
    return out


def num(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except ValueError:
        return default


def human(n: float) -> str:
    a = abs(n)
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if a >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + unit
    return f"{n:g}"


# --------------------------------------------------------------------------- #
# Options and context                                                          #
# --------------------------------------------------------------------------- #
def parse_opts(opts: str) -> tuple[set[str], dict[str, str]]:
    """`lr anim=packets title="Hello there"` -> ({"lr"}, {"anim": "packets", "title": "Hello there"})."""
    flags: set[str] = set()
    kv: dict[str, str] = {}
    for tok in re.findall(r'[\w-]+="[^"]*"|\S+', opts or ""):
        if "=" in tok:
            k, _, v = tok.partition("=")
            kv[k.strip().lower()] = v.strip().strip('"')
        else:
            flags.add(tok.strip().lower())
    return flags, kv


@dataclass
class Ctx:
    name: str
    flags: set[str]
    kv: dict[str, str]
    body: list[str]
    inline: Inline
    anim: str = "none"
    notes: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list[str]:
        return [b.strip() for b in self.body if b.strip() and not b.strip().startswith("//")]

    def dir(self, default: str = "lr") -> str:
        for d in ("lr", "rl", "tb", "bt"):
            if d in self.flags:
                return d
        return self.kv.get("dir", default).lower()


@dataclass
class Preset:
    name: str
    fn: Callable[[Ctx], str]
    default_anim: str = "reveal"
    summary: str = ""
    syntax: str = ""
    raw: bool = False
    aliases: tuple[str, ...] = ()
    group: str = "diagram"


REGISTRY: dict[str, Preset] = {}


def preset(name: str, *, anim: str = "reveal", summary: str = "", syntax: str = "", raw: bool = False,
           aliases: tuple[str, ...] = (), group: str = "diagram") -> Callable:
    def deco(fn: Callable[[Ctx], str]) -> Callable[[Ctx], str]:
        p = Preset(name, fn, anim, summary or (fn.__doc__ or "").strip().split("\n")[0], syntax, raw, aliases, group)
        REGISTRY[name] = p
        for a in aliases:
            REGISTRY[a] = p
        return fn
    return deco


class PresetError(ValueError):
    """The directive body could not be read; the message says what and where."""


# --------------------------------------------------------------------------- #
# Wrapping                                                                     #
# --------------------------------------------------------------------------- #
def svg_open(w: float, h: float, label: str, *, uid_: str = "") -> str:
    return (f'<svg viewBox="0 0 {fmt(w)} {fmt(h)}" role="img" aria-label="{esc(label)}" '
            f'style="min-width:{int(min(w, 820))}px">')


def marker_defs(mid: str) -> str:
    return (f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" '
            f'orient="auto-start-reverse"><path class="pv-arrow" d="M0 0L10 5L0 10z"/></marker></defs>')


def resolve_anim(p: Preset, kv: dict[str, str], flags: set[str]) -> str:
    asked = kv.get("anim") or ("none" if ({"static", "still"} & flags) else "")
    if not asked:
        configured = str(CONFIG.get("animation", "auto")).lower()
        asked = p.default_anim if configured in ("", "auto") else configured
    asked = asked.lower()
    return asked if asked in ANIMATIONS else p.default_anim


def error_box(name: str, message: str) -> str:
    return (f'<aside class="callout warn"><div class="callout-title">Could not draw {esc(name)}</div>'
            f'<p>{esc(message)}</p></aside>')


def run_preset(p: Preset, opts: str, body: list[str], inline: Inline) -> str:
    flags, kv = parse_opts(opts)
    anim = resolve_anim(p, kv, flags)
    ctx = Ctx(p.name, flags, kv, body, inline, anim)
    try:
        out = p.fn(ctx)
    except PresetError as exc:
        return error_box(p.name, str(exc))
    except Exception as exc:                                                    # noqa: BLE001
        return error_box(p.name, f"{type(exc).__name__}: {exc}")
    if p.raw:
        return out
    title = kv.get("title", "")
    cap = f"<figcaption>{inline(title)}</figcaption>" if title else ""
    speed = kv.get("speed", "1")
    name = re.sub(r"[^a-z0-9-]+", "-", (title or p.name).lower()).strip("-") or p.name
    return (f'<figure class="diagram pv pv-{p.name}" data-pv="{p.name}" data-anim="{esc(anim)}" data-name="{esc(name)}" '
            f'style="--pv-speed:{esc(speed)}">{out}{cap}</figure>')


def as_directive(p: Preset) -> Callable[[str, list[str], Inline], str]:
    def directive(opts: str, body: list[str], inline: Inline) -> str:
        return run_preset(p, opts, body, inline)
    directive.__name__ = f"preset_{p.name}"
    return directive
