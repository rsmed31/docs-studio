"""Chart presets: donut, chart (line / area / column / stack), radar, gantt, quadrant, heatmap, stats."""
from __future__ import annotations

import datetime as dt
import math
import re

from .common import (Ctx, PresetError, esc, fields, fmt, human, items, num, preset, svg_open, text_el, tw, uid, wrap)


def _nice_max(v: float) -> tuple[float, float]:
    """(axis top, tick step) for a positive maximum."""
    if v <= 0:
        return 1.0, 0.2
    base = 10 ** math.floor(math.log10(v))
    for m in (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10):
        step = m * base
        if 3 <= math.ceil(v / step) <= 6:
            return math.ceil(v / step - 1e-9) * step, step
    return v, v / 4


def _series(lines: list[str]) -> tuple[list[str], list[tuple[str, list[float]]]]:
    xs: list[str] = []
    out: list[tuple[str, list[float]]] = []
    for line in lines:
        m = re.match(r"^(?:x|axis|labels|cols|axes)\s*:\s*(.*)$", line, re.I)
        if m:
            xs = [p.strip() for p in m.group(1).split("|") if p.strip()]
            continue
        m = re.match(r"^(?:series|s|[-*])\s+(.*)$", line, re.I)
        if m:
            f = [p.strip() for p in re.split(r"(?<=\s)\|(?=\s|$)", m.group(1))]
            out.append((f[0], [num(v) for v in f[1:]]))
    if not out:
        raise PresetError("add `x: A | B | C` and one or more `series Name | 1 | 2 | 3` lines")
    width = max(len(v) for _, v in out)
    if not xs:
        xs = [str(i + 1) for i in range(width)]
    return xs, out


# --------------------------------------------------------------------------- #
# donut                                                                        #
# --------------------------------------------------------------------------- #
@preset("donut", anim="draw", group="chart", aliases=("pie", "share"),
        summary="Donut / pie: shares of a whole with a legend.",
        syntax="- Label | value | note     options: center=Text unit=%")
def donut(ctx: Ctx) -> str:
    """Donut of shares."""
    rows = [fields(i, 3) for i in items(ctx.body)]
    vals = [max(num(r[1]), 0) for r in rows]
    total = sum(vals)
    if not rows or total <= 0:
        raise PresetError("write `- Label | number | note` items with positive numbers")
    W, H, R, SW = 880.0, 320.0, 104.0, 40.0
    cx, cy = 180.0, H / 2
    parts = []
    acc = 0.0
    for i, ((label, _v, note), v) in enumerate(zip(rows, vals)):
        pct = v / total * 100
        parts.append(f'<circle class="pv-slice pv-e c{i % 8 + 1}" style="--i:{i};--len:{pct:.3f}" cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(R)}" fill="none" stroke-width="{fmt(SW)}" '
                     f'pathLength="100" stroke-dasharray="{pct:.3f} {100 - pct:.3f}" stroke-dashoffset="{-acc:.3f}" transform="rotate(-90 {fmt(cx)} {fmt(cy)})"/>')
        acc += pct
    center = ctx.kv.get("center", human(total))
    parts.append(f'<text class="pv-center" x="{fmt(cx)}" y="{fmt(cy + 8)}" text-anchor="middle">{esc(center)}</text>')
    ly = max(28.0, cy - len(rows) * 15)
    for i, ((label, value, note), v) in enumerate(zip(rows, vals)):
        y = ly + i * 30
        parts.append(f'<g class="pv-n" style="--i:{i}"><rect class="pv-sw c{i % 8 + 1}" x="360" y="{fmt(y - 12)}" width="16" height="16" rx="4"/>'
                     f'<text class="pv-t" x="386" y="{fmt(y)}">{esc(label)}</text>'
                     f'<text class="pv-l" x="640" y="{fmt(y)}" text-anchor="end">{esc(value)}{esc(ctx.kv.get("unit", ""))}</text>'
                     f'<text class="pv-s" x="660" y="{fmt(y)}">{v / total * 100:.0f}%{(" · " + esc(note)) if note else ""}</text></g>')
    H = max(H, ly + len(rows) * 30 + 20)
    return svg_open(W, H, ctx.kv.get("title") or "Shares: " + ", ".join(f"{r[0]} {r[1]}" for r in rows)) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# chart                                                                        #
# --------------------------------------------------------------------------- #
@preset("chart", anim="draw", group="chart", aliases=("line", "area", "column", "stack"),
        summary="Line, area, column or stacked-column chart over a shared x axis. Options: line area column stack.",
        syntax="x: Jan | Feb | Mar   then   series Name | 1 | 2 | 3   options: line|area|column|stack unit=$ min=0")
def chart(ctx: Ctx) -> str:
    """Line / area / column chart."""
    xs, series = _series(ctx.lines)
    kind = next((k for k in ("stack", "column", "area", "line") if k in ctx.flags), ctx.kv.get("type", "line"))
    if kind == "stacked":
        kind = "stack"
    n = max(len(xs), max(len(v) for _, v in series))
    xs = (xs + [""] * n)[:n]
    stacked = kind == "stack"
    peak = max(sum(v[i] if i < len(v) else 0 for _, v in series) for i in range(n)) if stacked else max(max(v or [0]) for _, v in series)
    lo = min(0.0, min(min(v or [0]) for _, v in series))
    lo = num(ctx.kv.get("min", ""), lo) if "min" in ctx.kv else lo
    top, step = _nice_max(max(peak, 0.0001))
    unit = ctx.kv.get("unit", "")
    W, H = 880.0, 380.0
    L, R_, T, B = 62.0, 24.0, 44.0, 52.0
    iw, ih = W - L - R_, H - T - B

    def Y(v: float) -> float:
        return T + ih - (v - lo) / ((top - lo) or 1) * ih

    def X(i: int) -> float:
        return L + (iw * (i + 0.5) / n if kind in ("column", "stack") else (iw * i / max(n - 1, 1)))

    parts = []
    t = lo
    while t <= top + step * 0.01:
        y = Y(t)
        parts.append(f'<line class="pv-grid" x1="{fmt(L)}" y1="{fmt(y)}" x2="{fmt(W - R_)}" y2="{fmt(y)}"/>'
                     f'<text class="pv-s" x="{fmt(L - 8)}" y="{fmt(y + 4)}" text-anchor="end">{esc(unit)}{esc(human(t))}</text>')
        t += step
    skip = max(1, math.ceil(n * 60 / iw))
    for i, lab in enumerate(xs):
        if i % skip == 0:
            parts.append(f'<text class="pv-s" x="{fmt(X(i))}" y="{fmt(H - B + 22)}" text-anchor="middle">{esc(lab)}</text>')
    if kind in ("column", "stack"):
        slot = iw / n
        gap = slot * 0.22
        per = (slot - gap) / (1 if stacked else len(series))
        base = [0.0] * n
        for s, (name, vals) in enumerate(series):
            for i in range(n):
                v = vals[i] if i < len(vals) else 0
                if stacked:
                    y0, y1 = Y(base[i] + v), Y(base[i])
                    x = L + slot * i + gap / 2
                    base[i] += v
                else:
                    y0, y1 = Y(max(v, 0)), Y(max(lo, 0) if v >= 0 else v)
                    x = L + slot * i + gap / 2 + per * s
                parts.append(f'<rect class="pv-bar pv-e c{s % 8 + 1}" style="--i:{i}" x="{fmt(x)}" y="{fmt(min(y0, y1))}" width="{fmt(per - 2)}" height="{fmt(abs(y1 - y0))}" rx="3"><title>{esc(name)} · {esc(xs[i])}: {esc(v)}</title></rect>')
    else:
        for s, (name, vals) in enumerate(series):
            pts = [(X(i), Y(vals[i] if i < len(vals) else 0)) for i in range(n)]
            d = "M" + " L".join(f"{fmt(x)},{fmt(y)}" for x, y in pts)
            if kind == "area":
                parts.append(f'<path class="pv-area pv-n c{s % 8 + 1}" style="--i:{s}" d="{d} L{fmt(pts[-1][0])},{fmt(Y(lo))} L{fmt(pts[0][0])},{fmt(Y(lo))} z"/>')
            parts.append(f'<path class="pv-series pv-e c{s % 8 + 1}" style="--i:{s}" pathLength="1000" d="{d}"/>')
            for i, (x, y) in enumerate(pts):
                parts.append(f'<circle class="pv-dot pv-n c{s % 8 + 1}" style="--i:{s + i}" cx="{fmt(x)}" cy="{fmt(y)}" r="3.6"><title>{esc(name)} · {esc(xs[i])}: {esc(vals[i] if i < len(vals) else 0)}</title></circle>')
    lx = L
    for s, (name, _v) in enumerate(series):
        parts.append(f'<g class="pv-n" style="--i:{s}"><rect class="pv-sw c{s % 8 + 1}" x="{fmt(lx)}" y="14" width="14" height="14" rx="4"/>'
                     f'<text class="pv-l" x="{fmt(lx + 20)}" y="26">{esc(name)}</text></g>')
        lx += 20 + tw(name, 12) + 26
    return svg_open(W, H, ctx.kv.get("title") or f"{kind.title()} chart of " + ", ".join(s[0] for s in series)) + "".join(parts) + "</svg>"


@preset("radar", anim="draw", group="chart", aliases=("spider",),
        summary="Radar / spider chart comparing series across axes (skills, scores, capabilities).",
        syntax="axes: Speed | Cost | Quality | Reach   then   series Name | 3 | 4 | 2 | 5     options: max=5")
def radar(ctx: Ctx) -> str:
    """Radar chart."""
    xs, series = _series(ctx.lines)
    n = len(xs)
    if n < 3:
        raise PresetError("a radar needs at least three axes: `axes: A | B | C`")
    top = num(ctx.kv.get("max", ""), 0) or max(max(v or [0]) for _, v in series) or 1
    W, H, R = 880.0, 460.0, 160.0
    cx, cy = 300.0, H / 2
    parts = []
    for ring in range(1, 6):
        r = R * ring / 5
        pts = " ".join(f"{fmt(cx + r * math.cos(-math.pi / 2 + 2 * math.pi * i / n))},{fmt(cy + r * math.sin(-math.pi / 2 + 2 * math.pi * i / n))}" for i in range(n))
        parts.append(f'<polygon class="pv-grid-poly" points="{pts}"/>')
    for i, lab in enumerate(xs):
        a = -math.pi / 2 + 2 * math.pi * i / n
        parts.append(f'<line class="pv-grid" x1="{fmt(cx)}" y1="{fmt(cy)}" x2="{fmt(cx + R * math.cos(a))}" y2="{fmt(cy + R * math.sin(a))}"/>'
                     f'<text class="pv-t" x="{fmt(cx + (R + 22) * math.cos(a))}" y="{fmt(cy + (R + 22) * math.sin(a) + 4)}" text-anchor="{"middle" if abs(math.cos(a)) < 0.3 else ("start" if math.cos(a) > 0 else "end")}">{esc(lab)}</text>')
    for s, (name, vals) in enumerate(series):
        pts = []
        for i in range(n):
            v = (vals[i] if i < len(vals) else 0) / top
            a = -math.pi / 2 + 2 * math.pi * i / n
            pts.append(f"{fmt(cx + R * v * math.cos(a))},{fmt(cy + R * v * math.sin(a))}")
        parts.append(f'<polygon class="pv-radar pv-n c{s % 8 + 1}" style="--i:{s}" points="{" ".join(pts)}"/>')
    for s, (name, _v) in enumerate(series):
        y = 120 + s * 28
        parts.append(f'<g class="pv-n" style="--i:{s}"><rect class="pv-sw c{s % 8 + 1}" x="620" y="{y - 12}" width="16" height="16" rx="4"/><text class="pv-t" x="646" y="{y}">{esc(name)}</text></g>')
    return svg_open(W, H, ctx.kv.get("title") or "Radar: " + ", ".join(s[0] for s in series)) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# gantt                                                                        #
# --------------------------------------------------------------------------- #
def _date(s: str) -> dt.date | None:
    s = s.strip()
    for fmt_ in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m"):
        try:
            return dt.datetime.strptime(s, fmt_).date()
        except ValueError:
            continue
    return None


@preset("gantt", anim="draw", group="chart", aliases=("schedule", "roadmap-chart"),
        summary="Gantt / schedule: tasks as bars on a date axis, grouped, coloured by status.",
        syntax="- Task | 2026-01-05 | 2026-02-10 (or 3w / 10d) | status | group     options: today")
def gantt(ctx: Ctx) -> str:
    """Gantt chart."""
    rows = []
    for it in items(ctx.body):
        name, a, b, status, group = fields(it, 5)
        start = _date(a)
        if start is None:
            raise PresetError(f"task {name!r}: cannot read the start date {a!r} (use 2026-01-31)")
        m = re.match(r"^(\d+)\s*([dw])$", b.strip().lower())
        end = start + dt.timedelta(days=int(m.group(1)) * (7 if m.group(2) == "w" else 1)) if m else _date(b)
        if end is None:
            raise PresetError(f"task {name!r}: cannot read the end {b!r} (a date, or a duration like 3w or 10d)")
        rows.append((name, start, max(end, start + dt.timedelta(days=1)), status, group))
    if not rows:
        raise PresetError("write `- Task | start | end | status | group` items")
    d0 = min(r[1] for r in rows)
    d1 = max(r[2] for r in rows)
    span = max((d1 - d0).days, 1)
    L, R_, T, RH = 230.0, 30.0, 52.0, 34.0
    W = 980.0
    H = T + len(rows) * RH + 30
    iw = W - L - R_

    def X(d: dt.date) -> float:
        return L + (d - d0).days / span * iw

    parts = []
    if span <= 70:
        step_days, label = 7, lambda d: d.strftime("%d %b")
        cur = d0 - dt.timedelta(days=d0.weekday())
    else:
        step_days, label = 0, lambda d: d.strftime("%b %Y")
        cur = d0.replace(day=1)
    while cur <= d1:
        if cur >= d0:
            x = X(cur)
            parts.append(f'<line class="pv-grid" x1="{fmt(x)}" y1="{T - 10}" x2="{fmt(x)}" y2="{fmt(H - 20)}"/><text class="pv-s" x="{fmt(x + 4)}" y="{T - 16}">{esc(label(cur))}</text>')
        if step_days:
            cur += dt.timedelta(days=step_days)
        else:
            cur = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    groups = {}
    for i, (name, a, b, status, group) in enumerate(rows):
        y = T + i * RH
        tone = {"done": "st-done", "built": "st-done", "running": "st-running", "in progress": "st-running", "blocked": "st-blocked"}.get(status.lower(), "st-planned" if status else "")
        gi = groups.setdefault(group, len(groups)) if group else None
        colour = f" c{gi % 8 + 1}" if gi is not None and not tone else ""
        parts.append(f'<g class="pv-n" style="--i:{i}"><text class="pv-t" x="{fmt(L - 12)}" y="{fmt(y + 20)}" text-anchor="end">{esc(wrap(name, L - 24, 13, True, 1)[0])}</text>'
                     f'<rect class="pv-bar pv-e {tone}{colour}" style="--i:{i}" x="{fmt(X(a))}" y="{fmt(y + 6)}" width="{fmt(max(X(b) - X(a), 6))}" height="{RH - 12}" rx="6"><title>{esc(name)}: {a} to {b}{(" · " + esc(group)) if group else ""}</title></rect>'
                     f'</g>')
    if "today" in ctx.flags:
        t = dt.date.today()
        if d0 <= t <= d1:
            parts.append(f'<line class="pv-today" x1="{fmt(X(t))}" y1="{T - 10}" x2="{fmt(X(t))}" y2="{fmt(H - 20)}"/><text class="pv-l" x="{fmt(X(t) + 4)}" y="{fmt(H - 6)}">today</text>')
    return svg_open(W, H, ctx.kv.get("title") or "Schedule: " + ", ".join(r[0] for r in rows[:6])) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# quadrant                                                                     #
# --------------------------------------------------------------------------- #
@preset("quadrant", anim="reveal", group="chart", aliases=("matrix", "2x2", "prioritisation"),
        summary="2x2 matrix: place items by two scores (effort/impact, risk/likelihood).",
        syntax="x: Effort | y: Impact | tl: Quick wins | tr: Big bets | bl: Fill-ins | br: Money pits | - Item | 0.2 | 0.9 | tone")
def quadrant(ctx: Ctx) -> str:
    """2x2 quadrant."""
    xl = yl = ""
    quad = {"tl": "", "tr": "", "bl": "", "br": ""}
    pts = []
    for line in ctx.lines:
        m = re.match(r"^(x|y|tl|tr|bl|br)\s*:\s*(.*)$", line, re.I)
        if m:
            k = m.group(1).lower()
            if k == "x":
                xl = m.group(2)
            elif k == "y":
                yl = m.group(2)
            else:
                quad[k] = m.group(2)
            continue
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            f = fields(m.group(1), 4)
            pts.append((f[0], num(f[1]), num(f[2]), f[3]))
    if not pts:
        raise PresetError("add items like `- Name | 0.3 | 0.8` (both scores between 0 and 1, or 0 and 10)")
    scale = 10.0 if max(max(p[1], p[2]) for p in pts) > 1.0 else 1.0
    W, H = 880.0, 540.0
    L, T, S = 90.0, 20.0, 460.0
    iw = W - L - 30
    parts = [f'<rect class="pv-q" x="{L}" y="{T}" width="{iw / 2}" height="{S / 2}"/><rect class="pv-q alt" x="{L + iw / 2}" y="{T}" width="{iw / 2}" height="{S / 2}"/>'
             f'<rect class="pv-q alt" x="{L}" y="{T + S / 2}" width="{iw / 2}" height="{S / 2}"/><rect class="pv-q" x="{L + iw / 2}" y="{T + S / 2}" width="{iw / 2}" height="{S / 2}"/>']
    for key, (qx, qy, anchor) in {"tl": (L + 14, T + 24, "start"), "tr": (L + iw - 14, T + 24, "end"),
                                  "bl": (L + 14, T + S - 14, "start"), "br": (L + iw - 14, T + S - 14, "end")}.items():
        if quad[key]:
            parts.append(f'<text class="pv-zone-t" x="{fmt(qx)}" y="{fmt(qy)}" text-anchor="{anchor}">{esc(quad[key])}</text>')
    parts.append(f'<text class="pv-l" x="{fmt(L + iw / 2)}" y="{fmt(T + S + 30)}" text-anchor="middle">{esc(xl)} →</text>'
                 f'<text class="pv-l" transform="translate(32 {fmt(T + S / 2)}) rotate(-90)" text-anchor="middle">{esc(yl)} →</text>')
    for i, (name, x, y, tone) in enumerate(pts):
        px, py = L + min(max(x / scale, 0), 1) * iw, T + S - min(max(y / scale, 0), 1) * S
        tcls = f" {tone}" if tone in ("ok", "warn", "danger", "info") else f" c{i % 8 + 1}"
        parts.append(f'<g class="pv-n" style="--i:{i}"><circle class="pv-dot big{tcls}" cx="{fmt(px)}" cy="{fmt(py)}" r="8"/>'
                     f'<text class="pv-t" x="{fmt(px + 13)}" y="{fmt(py + 4)}">{esc(name)}</text></g>')
    return svg_open(W, H, ctx.kv.get("title") or "Matrix of " + ", ".join(p[0] for p in pts)) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# heatmap                                                                      #
# --------------------------------------------------------------------------- #
@preset("heatmap", anim="reveal", group="chart", aliases=("grid-heat", "coverage"),
        summary="Heatmap: rows by columns, colour by value (coverage, activity, risk).",
        syntax="cols: Mon | Tue | Wed   then   - Row | 1 | 5 | 3     options: max=10 unit=%")
def heatmap(ctx: Ctx) -> str:
    """Heatmap grid."""
    xs, series = _series(ctx.lines)
    n = len(xs)
    top = num(ctx.kv.get("max", ""), 0) or max(max(v or [0]) for _, v in series) or 1
    cw, rh, left = max(54.0, min(110.0, 700.0 / n)), 34.0, 170.0
    W, H = left + cw * n + 20, 60 + rh * len(series) + 20
    parts = []
    for j, lab in enumerate(xs):
        parts.append(f'<text class="pv-s" x="{fmt(left + cw * j + cw / 2)}" y="38" text-anchor="middle">{esc(lab)}</text>')
    for i, (name, vals) in enumerate(series):
        y = 50 + i * rh
        parts.append(f'<text class="pv-t" x="{fmt(left - 12)}" y="{fmt(y + 22)}" text-anchor="end">{esc(wrap(name, 150, 13, True, 1)[0])}</text>')
        for j in range(n):
            v = vals[j] if j < len(vals) else 0
            a = min(max(v / top, 0), 1)
            parts.append(f'<g class="pv-n" style="--i:{i + j}"><rect class="pv-heat" x="{fmt(left + cw * j + 2)}" y="{fmt(y + 2)}" width="{fmt(cw - 4)}" height="{rh - 4}" rx="6" style="--a:{a:.2f}"><title>{esc(name)} · {esc(xs[j])}: {esc(v)}</title></rect>'
                         f'<text class="pv-s {"on-fill" if a > 0.55 else ""}" x="{fmt(left + cw * j + cw / 2)}" y="{fmt(y + 22)}" text-anchor="middle">{esc(human(v))}{esc(ctx.kv.get("unit", ""))}</text></g>')
    return svg_open(W, H, ctx.kv.get("title") or "Heatmap of " + ", ".join(s[0] for s in series[:6])) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# stats (KPI tiles with sparklines)                                            #
# --------------------------------------------------------------------------- #
@preset("stats", anim="reveal", group="chart", aliases=("kpi", "tiles"), raw=True,
        summary="KPI tiles: a big number, a change, and an optional sparkline.",
        syntax="- Label | value | +12% | 1,3,2,5,8 | note     options: 2 3 4 (columns)")
def stats(ctx: Ctx) -> str:
    """KPI tiles."""
    cols = next((w for w in ("2", "3", "4", "5") if w in ctx.flags), "4")
    out = []
    for i, it in enumerate(items(ctx.body)):
        label, value, delta, spark, note = fields(it, 5)
        tone = "up" if delta.startswith("+") else ("down" if delta.startswith(("-", "−")) else "")
        svg = ""
        vals = [num(v) for v in spark.split(",") if v.strip()] if spark else []
        if len(vals) >= 2:
            lo, hi = min(vals), max(vals)
            pts = " ".join(f"{fmt(4 + 112 * k / (len(vals) - 1))},{fmt(32 - 28 * (v - lo) / ((hi - lo) or 1))}" for k, v in enumerate(vals))
            svg = f'<svg class="pv-spark" viewBox="0 0 120 36" aria-hidden="true"><polyline class="pv-series pv-e" pathLength="1000" points="{pts}"/></svg>'
        out.append(f'<div class="pv-tile pv-n" style="--i:{i}"><div class="pv-tile-l">{esc(label)}</div><div class="pv-tile-v">{esc(value)}</div>'
                   + (f'<div class="pv-tile-d {tone}">{esc(delta)}</div>' if delta else "")
                   + svg + (f'<div class="pv-tile-n">{ctx.inline(note)}</div>' if note else "") + "</div>")
    if not out:
        raise PresetError("write `- Label | value | change | 1,2,3 | note` items")
    anim = ctx.anim
    return f'<div class="pv-tiles cols-{cols} diagram-lite" data-anim="{esc(anim)}" data-pv="stats">{"".join(out)}</div>'
