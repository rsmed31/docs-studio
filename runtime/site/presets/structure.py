"""Structure presets: sequence, layers, zones, tree, mindmap, cycle, pyramid, funnel."""
from __future__ import annotations

import math
import re

from .common import (Ctx, PresetError, esc, fields, fmt, human, items, marker_defs, num, preset, svg_open, text_el, tw,
                     uid, wrap)

ICON_SIZE = 20


def _icon(name: str, x: float, y: float, size: int = ICON_SIZE) -> str:
    try:
        from blocks import icon as _ic                                   # the site's icon set (24x24 strokes)
    except ImportError:                                                  # pragma: no cover
        return ""
    svg = _ic(name, size)
    if not svg:
        return ""
    return svg.replace("<svg ", f'<svg x="{fmt(x)}" y="{fmt(y)}" ', 1).replace('class="ico-svg"', 'class="pv-ico"')


def _status_cls(status: str) -> str:
    s = (status or "").strip().lower()
    return {"done": " st-done", "built": " st-done", "running": " st-running", "in progress": " st-running",
            "planned": " st-planned", "plan": " st-planned", "blocked": " st-blocked"}.get(s, "")


# --------------------------------------------------------------------------- #
# sequence                                                                     #
# --------------------------------------------------------------------------- #
@preset("sequence", anim="trace", group="structure", aliases=("seq", "interaction"),
        summary="Sequence diagram: who talks to whom, in order; `!` marks a question, `--&gt;` a reply, `== phase ==` a band.",
        syntax="first line: Actor A | Actor B | Actor C   then   A -> B: text | B --> A: reply | == Phase == | note A: text")
def sequence(ctx: Ctx) -> str:
    """Sequence diagram."""
    lines = ctx.lines
    if not lines:
        raise PresetError("a sequence needs a first line listing the actors: `User | API | Database`")
    actors = [a.strip() for a in lines[0].split("|") if a.strip()]
    if len(actors) < 2:
        raise PresetError("list at least two actors on the first line, separated by `|`")
    n = len(actors)
    W, M = max(760.0, 190.0 * n), 16.0
    gap = (W - 2 * M) / n
    cx = [M + gap * (i + 0.5) for i in range(n)]
    idx = {a.lower(): i for i, a in enumerate(actors)}
    box_w = min(168.0, gap - 14)
    y = 78.0
    parts: list[str] = []
    mid = uid("mk")
    step = 0
    for raw in lines[1:]:
        m = re.match(r"^==\s*(.*?)\s*==$", raw)
        if m:
            parts.append(f'<g class="pv-n" style="--i:{step}"><rect class="sq-band" x="{M}" y="{y - 12:.1f}" width="{W - 2 * M}" height="22" rx="6"/>'
                         f'<text class="sq-band-t" x="{W / 2}" y="{y + 3:.1f}" text-anchor="middle">{esc(m.group(1))}</text></g>')
            y += 30
            continue
        m = re.match(r"^note\s+([^:]+):\s*(.*)$", raw, re.I)
        if m and m.group(1).strip().lower() in idx:
            i = idx[m.group(1).strip().lower()]
            ls = wrap(m.group(2), box_w + 28, 11)
            h = 10 + 15 * len(ls)
            parts.append(f'<g class="pv-n" style="--i:{step}"><rect class="sq-note" x="{cx[i] - box_w / 2 - 20:.1f}" y="{y - 6:.1f}" width="{box_w + 40:.1f}" height="{h}" rx="8"/>'
                         + text_el(cx[i], y + 8, ls, "sq-t", 15, "middle") + "</g>")
            y += h + 14
            continue
        m = re.match(r"^(.+?)\s*(-->|->)\s*(.+?):\s*(.*)$", raw)
        if not m:
            raise PresetError(f"cannot read: {raw!r} (expected `A -> B: text`)")
        a_name, b_name = m.group(1).strip().lower(), m.group(3).strip().lower()
        if a_name not in idx or b_name not in idx:
            unknown = m.group(1) if a_name not in idx else m.group(3)
            raise PresetError(f"{unknown.strip()!r} is not one of the actors ({', '.join(actors)})")
        a, b = idx[a_name], idx[b_name]
        dashed = m.group(2) == "-->"
        text = m.group(4).strip()
        ask = text.startswith("!")
        text = text.lstrip("! ").strip()
        span = max(abs(cx[b] - cx[a]), gap)
        ls = wrap(text, span - 14, 12)
        h = 15 * len(ls)
        mx = (cx[a] + cx[b]) / 2
        ly = y + h + 14
        if a == b:
            line = f'<path class="sq-line pv-e{" ask" if ask else ""}" pathLength="1000" d="M{cx[a]:.1f} {ly - 8:.1f} h26 v14 h-26" marker-end="url(#{mid})"/>'
        else:
            x1 = cx[a] + (3 if cx[b] > cx[a] else -3)
            x2 = cx[b] + (-3 if cx[b] > cx[a] else 3)
            line = (f'<path class="sq-line pv-e{" dash" if dashed else ""}{" ask" if ask else ""}" pathLength="1000" '
                    f'd="M{x1:.1f} {ly:.1f} H{x2:.1f}" marker-end="url(#{mid})"/>')
        parts.append(f'<g class="pv-n pv-msg" style="--i:{step}">' + text_el(mx, y + 11, ls, f"sq-t{' ask' if ask else ''}", 15, "middle") + line + "</g>")
        step += 1
        y = ly + 12
    height = y + 10
    head = [f'<line class="sq-life" x1="{cx[i]:.1f}" y1="46" x2="{cx[i]:.1f}" y2="{height - 6:.1f}"/>' for i in range(n)]
    for i, a in enumerate(actors):
        head.append(f'<rect class="sq-actor" x="{cx[i] - box_w / 2:.1f}" y="8" width="{box_w:.1f}" height="36" rx="9"/>'
                    f'<text class="sq-actor-t" x="{cx[i]:.1f}" y="31" text-anchor="middle">{esc(a)}</text>')
    label = ctx.kv.get("title") or "Sequence: " + "; ".join(re.sub(r"\s+", " ", ln) for ln in lines[1:5])
    return svg_open(W, height, label) + marker_defs(mid) + "".join(head) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# layers                                                                       #
# --------------------------------------------------------------------------- #
@preset("layers", anim="reveal", group="structure", aliases=("stack", "architecture"),
        summary="Architecture layers: horizontal bands, each with boxes; arrows between layers show the direction of calls.",
        syntax="## Layer name  then  - Box | subtitle | icon | status | #link     options: arrows=off  up")
def layers(ctx: Ctx) -> str:
    """Architecture layers."""
    bands: list[tuple[str, list[list[str]]]] = []
    for line in ctx.lines:
        m = re.match(r"^#{1,4}\s+(.*)$", line)
        if m:
            bands.append((m.group(1).strip(), []))
        elif re.match(r"^[-*]\s+", line) and bands:
            bands[-1][1].append(fields(re.sub(r"^[-*]\s+", "", line), 5))
    if not bands:
        raise PresetError("write `## Layer name` lines, each followed by `- Box | subtitle | icon | status | #link` items")
    W, LABEL_W, PAD = 980.0, 150.0, 18.0
    band_h, gap = 112.0, 34.0
    mid = uid("mk")
    parts = [marker_defs(mid)]
    arrows = "off" not in ctx.kv.get("arrows", "")
    y = 14.0
    k = 0
    for bi, (title, boxes) in enumerate(bands):
        parts.append(f'<g class="pv-n" style="--i:{bi * 2}"><rect class="pv-zone" x="10" y="{fmt(y)}" width="{fmt(W - 20)}" height="{fmt(band_h)}" rx="16"/>'
                     + text_el(26, y + band_h / 2 - 4, wrap(title, LABEL_W - 28, 11, True), "pv-zone-t", 14) + "</g>")
        n = max(len(boxes), 1)
        avail = W - 20 - LABEL_W - PAD
        bw = min(230.0, (avail - 14 * (n - 1)) / n)
        total = bw * n + 14 * (n - 1)
        x = 10 + LABEL_W + (avail - total) / 2
        for label, sub, icon, status, link in boxes:
            lines = wrap(label, bw - 56 if icon else bw - 24, 13, True, 2)
            sublines = wrap(sub, bw - 24, 11, False, 2) if sub else []
            body = (f'<rect class="pv-shape{_status_cls(status)}" x="{fmt(x)}" y="{fmt(y + 18)}" width="{fmt(bw)}" height="{fmt(band_h - 36)}" rx="11"/>')
            tx = x + (44 if icon else bw / 2)
            anchor = "start" if icon else "middle"
            if icon:
                body += _icon(icon, x + 12, y + 18 + 12)
            ty = y + 18 + 24
            body += text_el(tx if icon else x + bw / 2, ty, lines, "pv-t", 16, anchor)
            body += text_el(tx if icon else x + bw / 2, ty + 16 * len(lines), sublines, "pv-s", 13, anchor)
            g = f'<g class="pv-n" style="--i:{bi * 2 + 1}">{body}</g>'
            parts.append(f'<a href="{esc(link)}">{g}</a>' if link.startswith(("#", "http")) else g)
            x += bw + 14
            k += 1
        y += band_h
        if bi < len(bands) - 1:
            if arrows:
                ax = W / 2
                d_dn = f"M{fmt(ax - 12)},{fmt(y + 4)} V{fmt(y + gap - 6)}"
                d_up = f"M{fmt(ax + 12)},{fmt(y + gap - 4)} V{fmt(y + 6)}"
                parts.append(f'<path class="pv-edge pv-e" style="--i:{bi * 2 + 1}" pathLength="1000" d="{d_dn}" marker-end="url(#{mid})"/>')
                if "up" in ctx.flags:
                    parts.append(f'<path class="pv-edge dash pv-e" style="--i:{bi * 2 + 1}" pathLength="1000" d="{d_up}" marker-end="url(#{mid})"/>')
                if ctx.anim == "packets":                       # type: ignore[attr-defined]
                    parts.append(f'<circle class="pv-packet" r="4"><animateMotion dur="1.6s" repeatCount="indefinite" path="{d_dn}"/></circle>')
            y += gap
    return svg_open(W, y + 14, ctx.kv.get("title") or "Layers: " + ", ".join(b[0] for b in bands)) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# zones (the generic "map")                                                    #
# --------------------------------------------------------------------------- #
@preset("zones", anim="flow", group="structure", aliases=("map", "landscape"),
        summary="System map: named zones containing nodes, arrows between nodes. Every box can link to a page.",
        syntax="## Zone  then  - id | icon | Title | subtitle | status | #link   then   id -> id: label     options: cols=3")
def zones(ctx: Ctx) -> str:
    """System map of zones and nodes."""
    zs: list[tuple[str, list[dict]]] = []
    edges: list[tuple[str, str, str, str]] = []
    for line in ctx.lines:
        m = re.match(r"^#{1,4}\s+(.*)$", line)
        if m:
            zs.append((m.group(1).strip(), []))
            continue
        m = re.match(r"^[-*]\s+(.*)$", line)
        if m and zs:
            f = fields(m.group(1), 6)
            zs[-1][1].append({"id": f[0], "icon": f[1], "t": f[2] or f[0], "s": f[3], "status": f[4], "link": f[5]})
            continue
        m = re.match(r"^(\S+)\s*(-->|->)\s*(\S+?)\s*(?::\s*(.*))?$", line)
        if m:
            edges.append((m.group(1), m.group(3), m.group(4) or "", "dash" if m.group(2) == "-->" else ""))
    if not zs:
        raise PresetError("write `## Zone name` lines, each followed by `- id | icon | Title | subtitle | status | #link` items")
    ncols = int(num(ctx.kv.get("cols", ""), 0)) or min(3, len(zs))
    NW, NH, PADX, PADY, GAPX, GAPY = 214.0, 64.0, 18.0, 44.0, 70.0, 52.0
    zw = NW + 2 * PADX
    pos: dict[str, tuple[float, float]] = {}
    boxes = []
    row_y = 20.0
    placed = [zs[i:i + ncols] for i in range(0, len(zs), ncols)]
    for row in placed:
        row_h = max(len(z[1]) for z in row) * (NH + 14) + PADY + 14
        for c, (title, nodes) in enumerate(row):
            x0 = 20 + c * (zw + GAPX)
            boxes.append((title, x0, row_y, zw, row_h))
            for r, nd in enumerate(nodes):
                pos[nd["id"]] = (x0 + PADX, row_y + PADY + r * (NH + 14))
        row_y += row_h + GAPY
    W = 20 + ncols * zw + (ncols - 1) * GAPX + 20
    H = row_y - GAPY + 20
    mid = uid("mk")
    parts = [marker_defs(mid)]
    for i, (title, x0, y0, w, h) in enumerate(boxes):
        parts.append(f'<g class="pv-n" style="--i:{i}"><rect class="pv-zone" x="{fmt(x0)}" y="{fmt(y0)}" width="{fmt(w)}" height="{fmt(h)}" rx="18"/>'
                     f'<text class="pv-zone-t" x="{fmt(x0 + 18)}" y="{fmt(y0 + 28)}">{esc(title)}</text></g>')
    speed = num(ctx.kv.get("speed", "1"), 1) or 1
    for k, (a, b, label, style) in enumerate(edges):
        if a not in pos or b not in pos:
            raise PresetError(f"arrow {a} -> {b}: both ends must be ids from the `- id | …` lines")
        (ax, ay), (bx, by) = pos[a], pos[b]
        acx, acy, bcx, bcy = ax + NW / 2, ay + NH / 2, bx + NW / 2, by + NH / 2
        if abs(acx - bcx) > 20:                                           # side by side: leave at the facing sides
            sx = ax + NW if bcx > acx else ax
            ex = bx if bcx > acx else bx + NW
            kk = (ex - sx) / 2
            d = f"M{fmt(sx)},{fmt(acy)} C{fmt(sx + kk)},{fmt(acy)} {fmt(ex - kk)},{fmt(bcy)} {fmt(ex)},{fmt(bcy)}"
            lx, ly = (sx + ex) / 2, (acy + bcy) / 2
        else:
            sy = ay + NH if bcy > acy else ay
            ey = by if bcy > acy else by + NH
            kk = (ey - sy) / 2
            d = f"M{fmt(acx)},{fmt(sy)} C{fmt(acx)},{fmt(sy + kk)} {fmt(bcx)},{fmt(ey - kk)} {fmt(bcx)},{fmt(ey)}"
            lx, ly = (acx + bcx) / 2, (sy + ey) / 2
        parts.append(f'<path class="pv-edge{" dash" if style else ""} pv-e" style="--i:{k}" pathLength="1000" d="{d}" marker-end="url(#{mid})"/>')
        if ctx.anim == "packets":                                         # type: ignore[attr-defined]
            parts.append(f'<circle class="pv-packet" r="4.5"><animateMotion dur="{3 / speed:.1f}s" begin="{(k * 0.5) % 3:.1f}s" repeatCount="indefinite" path="{d}"/></circle>')
        if label:
            w_ = tw(label, 10.5) + 12
            parts.append(f'<g class="pv-lab"><rect x="{fmt(lx - w_ / 2)}" y="{fmt(ly - 9)}" width="{fmt(w_)}" height="18" rx="5"/>'
                         f'<text class="pv-l" x="{fmt(lx)}" y="{fmt(ly + 4)}" text-anchor="middle">{esc(label)}</text></g>')
    i = 0
    for title, nodes in zs:
        for nd in nodes:
            x, y = pos[nd["id"]]
            lines = wrap(nd["t"], NW - 56, 13, True, 1)
            subs = wrap(nd["s"], NW - 56, 11, False, 2) if nd["s"] else []
            body = f'<rect class="pv-shape{_status_cls(nd["status"])}" x="{fmt(x)}" y="{fmt(y)}" width="{fmt(NW)}" height="{fmt(NH)}" rx="12"/>'
            body += _icon(nd["icon"], x + 13, y + 14, 22) if nd["icon"] else ""
            tx = x + 46 if nd["icon"] else x + 14
            body += text_el(tx, y + 26, lines, "pv-t", 16, "start") + text_el(tx, y + 43, subs, "pv-s", 13, "start")
            g = f'<g class="pv-n" style="--i:{i + len(boxes)}">{body}</g>'
            parts.append(f'<a href="{esc(nd["link"])}">{g}</a>' if nd["link"].startswith(("#", "http")) else g)
            i += 1
    return svg_open(W, H, ctx.kv.get("title") or "Map of " + ", ".join(z[0] for z in zs)) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# tree and mindmap                                                             #
# --------------------------------------------------------------------------- #
def _parse_tree(body: list[str]) -> dict:
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for raw in body:
        if not raw.strip() or raw.strip().startswith("//"):
            continue
        expanded = raw.replace("\t", "    ")
        m = re.match(r"^(\s*)(?:[-*]\s+)?(.*)$", expanded)
        indent, text = len(m.group(1)), m.group(2).strip()
        f = fields(text, 3)
        node = {"label": f[0], "sub": f[1], "link": f[2] if f[2].startswith(("#", "http")) else "", "kids": []}
        while stack and stack[-1][0] >= indent:
            stack.pop()
        (stack[-1][1]["kids"] if stack else roots).append(node)
        stack.append((indent, node))
    if not roots:
        raise PresetError("write the tree as indented lines: the root, then its children indented below it")
    return roots[0] if len(roots) == 1 else {"label": "", "sub": "", "link": "", "kids": roots, "virtual": True}


def _tree_size(n: dict) -> None:
    n["lines"] = wrap(n["label"], 190, 13, True, 2) if n["label"] else []
    n["subl"] = wrap(n["sub"], 200, 11, False, 2) if n["sub"] else []
    tw_ = max([tw(x, 13, True) for x in n["lines"]] + [tw(x, 11) for x in n["subl"]] + [40])
    n["w"] = max(70.0, tw_ + 28)
    n["h"] = 18 + 17 * max(1, len(n["lines"])) + (14 * len(n["subl"]) if n["subl"] else 0)
    for k in n["kids"]:
        _tree_size(k)


def _tree_node(n: dict, i: int, cls: str = "") -> str:
    top = n["y"] - n["h"] / 2
    body = f'<rect class="pv-shape" x="{fmt(n["x"] - n["w"] / 2)}" y="{fmt(top)}" width="{fmt(n["w"])}" height="{fmt(n["h"])}" rx="{fmt(min(14, n["h"] / 2))}"/>'
    block = 17 * max(1, len(n["lines"])) + 14 * len(n["subl"])
    ty = n["y"] - block / 2 + 13
    body += text_el(n["x"], ty, n["lines"], "pv-t", 17, "middle") + text_el(n["x"], ty + 17 * max(1, len(n["lines"])) - 2, n["subl"], "pv-s", 14, "middle")
    g = f'<g class="pv-n {cls}" style="--i:{i}">{body}</g>'
    return f'<a href="{esc(n["link"])}">{g}</a>' if n["link"] else g


@preset("tree", anim="reveal", group="structure", aliases=("hierarchy", "org", "breakdown"),
        summary="Tree / org chart / breakdown from an indented list. Left-to-right by default; `tb` for top-down.",
        syntax="indented lines: Label | subtitle | #link     options: lr tb")
def tree(ctx: Ctx) -> str:
    """Tree from an indented list."""
    root = _parse_tree(ctx.body)
    _tree_size(root)
    horiz = ctx.dir("lr") in ("lr", "rl")
    slot = [0.0]
    depth_extent: dict[int, float] = {}
    GAP = 18.0

    def walk(n: dict, d: int) -> None:
        n["d"] = d
        depth_extent[d] = max(depth_extent.get(d, 0), n["w"] if horiz else n["h"])
        for k in n["kids"]:
            walk(k, d + 1)
        cross = n["h"] if horiz else n["w"]
        if not n["kids"]:
            n["c"] = slot[0] + cross / 2
            slot[0] += cross + GAP
        else:
            n["c"] = (n["kids"][0]["c"] + n["kids"][-1]["c"]) / 2

    walk(root, 0)
    gap_d = 64.0
    start: dict[int, float] = {}
    acc = 0.0
    for d in sorted(depth_extent):
        start[d] = acc
        acc += depth_extent[d] + gap_d
    flat: list[dict] = []

    def place(n: dict) -> None:
        a = start[n["d"]] + depth_extent[n["d"]] / 2
        n["x"], n["y"] = (a, n["c"]) if horiz else (n["c"], a)
        flat.append(n)
        for k in n["kids"]:
            place(k)

    place(root)
    W = max(n["x"] + n["w"] / 2 for n in flat) + 30
    H = max(n["y"] + n["h"] / 2 for n in flat) + 30
    for n in flat:
        n["x"] += 20
        n["y"] += 20
    W, H = W + 20, H + 20
    mid = uid("mk")
    parts = [marker_defs(mid)]
    k = 0
    for n in flat:
        for c in n["kids"]:
            if n.get("virtual"):
                continue
            if horiz:
                s, t = (n["x"] + n["w"] / 2, n["y"]), (c["x"] - c["w"] / 2, c["y"])
                kk = (t[0] - s[0]) / 2
                d = f"M{fmt(s[0])},{fmt(s[1])} C{fmt(s[0] + kk)},{fmt(s[1])} {fmt(t[0] - kk)},{fmt(t[1])} {fmt(t[0])},{fmt(t[1])}"
            else:
                s, t = (n["x"], n["y"] + n["h"] / 2), (c["x"], c["y"] - c["h"] / 2)
                kk = (t[1] - s[1]) / 2
                d = f"M{fmt(s[0])},{fmt(s[1])} C{fmt(s[0])},{fmt(s[1] + kk)} {fmt(t[0])},{fmt(t[1] - kk)} {fmt(t[0])},{fmt(t[1])}"
            parts.append(f'<path class="pv-edge pv-e" style="--i:{k}" pathLength="1000" d="{d}"/>')
            k += 1
    for i, n in enumerate(flat):
        if n.get("virtual"):
            continue
        parts.append(_tree_node(n, i, "root" if n["d"] == 0 else ""))
    return svg_open(W, H, ctx.kv.get("title") or f"Tree: {root['label'] or 'overview'}") + "".join(parts) + "</svg>"


@preset("mindmap", anim="reveal", group="structure", aliases=("radial",),
        summary="Mind map: the same indented list as `tree`, laid out around a centre.",
        syntax="indented lines: Label | subtitle | #link")
def mindmap(ctx: Ctx) -> str:
    """Mind map around a centre."""
    root = _parse_tree(ctx.body)
    if root.get("virtual"):
        root = {"label": ctx.kv.get("title", "Overview"), "sub": "", "link": "", "kids": root["kids"]}
    _tree_size(root)

    def leaves(n: dict) -> int:
        n["leaves"] = 1 if not n["kids"] else sum(leaves(k) for k in n["kids"])
        return n["leaves"]

    total = leaves(root)
    depth = [0]
    flat: list[dict] = []

    def place(n: dict, d: int, a0: float, a1: float) -> None:
        depth[0] = max(depth[0], d)
        ang = (a0 + a1) / 2
        r = 0 if d == 0 else 120 + (d - 1) * 150 + (n["w"] / 4)
        n["x"], n["y"], n["d"], n["ang"] = r * math.cos(ang), r * math.sin(ang), d, ang
        flat.append(n)
        cur = a0
        for k in n["kids"]:
            span = (a1 - a0) * k["leaves"] / n["leaves"]
            place(k, d + 1, cur, cur + span)
            cur += span

    place(root, 0, -math.pi / 2, 3 * math.pi / 2)
    minx = min(n["x"] - n["w"] / 2 for n in flat) - 24
    miny = min(n["y"] - n["h"] / 2 for n in flat) - 24
    maxx = max(n["x"] + n["w"] / 2 for n in flat) + 24
    maxy = max(n["y"] + n["h"] / 2 for n in flat) + 24
    for n in flat:
        n["x"] -= minx
        n["y"] -= miny
    parts = []
    k = 0
    for n in flat:
        for c in n["kids"]:
            sx, sy, tx, ty = n["x"], n["y"], c["x"], c["y"]
            mx, my = (sx + tx) / 2, (sy + ty) / 2
            d = f"M{fmt(sx)},{fmt(sy)} Q{fmt(mx + (ty - sy) * 0.12)},{fmt(my - (tx - sx) * 0.12)} {fmt(tx)},{fmt(ty)}"
            parts.append(f'<path class="pv-edge pv-e" style="--i:{k}" pathLength="1000" d="{d}"/>')
            k += 1
    for i, n in enumerate(flat):
        parts.append(_tree_node(n, i, "root" if n["d"] == 0 else ""))
    return svg_open(maxx - minx, maxy - miny, ctx.kv.get("title") or f"Mind map: {root['label']}") + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# cycle, pyramid, funnel                                                       #
# --------------------------------------------------------------------------- #
@preset("cycle", anim="packets", group="structure", aliases=("loop", "lifecycle"),
        summary="A loop of steps arranged in a circle (lifecycle, feedback loop, release cycle).",
        syntax="- Step | one line | #link     options: center=Label")
def cycle(ctx: Ctx) -> str:
    """Loop of steps in a circle."""
    steps_ = [fields(i, 3) for i in items(ctx.body)]
    if len(steps_) < 2:
        raise PresetError("a cycle needs at least two `- Step | text` items")
    n = len(steps_)
    R = 190.0 + max(0, n - 6) * 14
    W, H = 2 * R + 330, 2 * R + 110
    cx, cy = W / 2, H / 2
    BW, BH = 170.0, 62.0
    mid = uid("mk")
    pts = []
    for i in range(n):
        a = -math.pi / 2 + 2 * math.pi * i / n
        pts.append((cx + R * math.cos(a), cy + R * math.sin(a), a))
    parts = [marker_defs(mid)]
    speed = num(ctx.kv.get("speed", "1"), 1) or 1
    for i in range(n):
        x1, y1, a1 = pts[i]
        x2, y2, a2 = pts[(i + 1) % n]
        def reach(a: float) -> float:
            tx, ty = abs(math.sin(a)), abs(math.cos(a))             # tangent direction at angle a
            return 1.0 / max(tx / (BW / 2), ty / (BH / 2), 1e-6)    # distance from a box centre to its edge along it

        s_a, e_a = a1 + (reach(a1) + 8) / R, a2 - (reach(a2) + 12) / R
        if e_a < s_a:
            e_a += 2 * math.pi
        sx, sy = cx + R * math.cos(s_a), cy + R * math.sin(s_a)
        ex, ey = cx + R * math.cos(e_a), cy + R * math.sin(e_a)
        large = 1 if (e_a - s_a) > math.pi else 0
        d = f"M{fmt(sx)},{fmt(sy)} A{fmt(R)},{fmt(R)} 0 {large} 1 {fmt(ex)},{fmt(ey)}"
        parts.append(f'<path class="pv-edge pv-e" style="--i:{i}" pathLength="1000" d="{d}" marker-end="url(#{mid})"/>')
        if ctx.anim == "packets":                                           # type: ignore[attr-defined]
            parts.append(f'<circle class="pv-packet" r="4.5"><animateMotion dur="{2.4 / speed:.1f}s" begin="{i * 0.4:.1f}s" repeatCount="indefinite" path="{d}"/></circle>')
    if ctx.kv.get("center"):
        parts.append(text_el(cx, cy + 5, wrap(ctx.kv["center"], 220, 18, True, 3), "pv-center", 22, "middle"))
    for i, ((x, y, _a), (title, text, link)) in enumerate(zip(pts, steps_)):
        lines = wrap(f"{i + 1}. {title}", BW - 20, 13, True, 2)
        subs = wrap(text, BW - 20, 11, False, 2) if text else []
        body = f'<rect class="pv-shape" x="{fmt(x - BW / 2)}" y="{fmt(y - BH / 2)}" width="{BW}" height="{BH}" rx="14"/>'
        block = 16 * len(lines) + 13 * len(subs)
        ty = y - block / 2 + 12
        body += text_el(x, ty, lines, "pv-t", 16, "middle") + text_el(x, ty + 16 * len(lines), subs, "pv-s", 13, "middle")
        g = f'<g class="pv-n" style="--i:{i}">{body}</g>'
        parts.append(f'<a href="{esc(link)}">{g}</a>' if link.startswith(("#", "http")) else g)
    return svg_open(W, H, ctx.kv.get("title") or "Cycle: " + " → ".join(s[0] for s in steps_)) + "".join(parts) + "</svg>"


@preset("pyramid", anim="reveal", group="structure", aliases=("hierarchy-levels",),
        summary="Pyramid of levels, top first (priorities, maturity levels, test pyramid).",
        syntax="- Level | explanation     (first line is the top)")
def pyramid(ctx: Ctx) -> str:
    """Pyramid of levels."""
    rows = [fields(i, 2) for i in items(ctx.body)]
    if not rows:
        raise PresetError("write `- Level | explanation` items, top level first")
    n = len(rows)
    W, LH = 880.0, 64.0
    H = n * LH + 20
    base = 520.0
    cx = 290.0
    parts = []
    for i, (label, text) in enumerate(rows):
        top_w = base * i / n
        bot_w = base * (i + 1) / n
        y = 10 + i * LH
        pts = f"{fmt(cx - top_w / 2)},{fmt(y)} {fmt(cx + top_w / 2)},{fmt(y)} {fmt(cx + bot_w / 2 - 2)},{fmt(y + LH - 4)} {fmt(cx - bot_w / 2 + 2)},{fmt(y + LH - 4)}"
        lines = wrap(label, max(60, (top_w + bot_w) / 2 - 20), 13, True, 2)
        body = (f'<polygon class="pv-shape c{i % 8 + 1}" points="{pts}"/>'
                + text_el(cx, y + LH / 2 + 4 - (len(lines) - 1) * 8, lines if i else [], "pv-t on-fill", 16, "middle")
                + f'<path class="pv-line" d="M{fmt(cx + bot_w / 2 + 14)},{fmt(y + LH / 2)} H{fmt(cx + base / 2 + 40)}"/>'
                + text_el(cx + base / 2 + 50, y + LH / 2 - 4, [label] if not i else [], "pv-t", 14)
                + text_el(cx + base / 2 + 50, y + LH / 2 + (11 if not i else 4), wrap(text, 290, 12, False, 3), "pv-s", 15))
        parts.append(f'<g class="pv-n" style="--i:{i}">{body}</g>')
    return svg_open(W, H, ctx.kv.get("title") or "Pyramid: " + ", ".join(r[0] for r in rows)) + "".join(parts) + "</svg>"


@preset("funnel", anim="draw", group="structure", aliases=("conversion",),
        summary="Funnel: stages narrowing by value, with the conversion between stages.",
        syntax="- Stage | value | note")
def funnel(ctx: Ctx) -> str:
    """Funnel of stages."""
    rows = [fields(i, 3) for i in items(ctx.body)]
    vals = [num(r[1]) for r in rows]
    if not rows or not any(vals):
        raise PresetError("write `- Stage | number | note` items")
    W, LH, MAXW = 880.0, 58.0, 520.0
    top = max(vals) or 1
    H = len(rows) * LH + 20
    cx = 290.0
    parts = []
    for i, ((label, value, note), v) in enumerate(zip(rows, vals)):
        w = max(MAXW * v / top, 36)
        nxt = max(MAXW * vals[i + 1] / top, 36) if i + 1 < len(rows) else w * 0.82
        y = 10 + i * LH
        pts = f"{fmt(cx - w / 2)},{fmt(y)} {fmt(cx + w / 2)},{fmt(y)} {fmt(cx + nxt / 2)},{fmt(y + LH - 6)} {fmt(cx - nxt / 2)},{fmt(y + LH - 6)}"
        conv = f"{v / vals[i - 1] * 100:.0f}% of previous" if i and vals[i - 1] else ""
        parts.append(f'<g class="pv-n" style="--i:{i}"><polygon class="pv-shape c{i % 8 + 1}" points="{pts}"/>'
                     + (f'<text class="pv-t on-fill" x="{fmt(cx)}" y="{fmt(y + LH / 2 + 1)}" text-anchor="middle">{esc(human(v))}</text>' if w >= 60 else "")
                     + text_el(cx + MAXW / 2 + 40, y + LH / 2 - 8, [f"{label}" + (f" · {human(v)}" if w < 60 else "")], "pv-t", 14)
                     + text_el(cx + MAXW / 2 + 40, y + LH / 2 + 8, ([conv] if conv else []) + wrap(note, 280, 12, False, 1), "pv-s", 14) + "</g>")
    return svg_open(W, H, ctx.kv.get("title") or "Funnel: " + ", ".join(r[0] for r in rows)) + "".join(parts) + "</svg>"
