"""Graph presets: flow, state, er, network, swimlane. One parser, one layered layout engine.

Directive body (flow / state / er):

    node api | API gateway | proc | routes every request        (kind and subtitle are optional)
    web[Web app] -> api[API] -> db[(Postgres)]                   (mermaid-style shorthand)
    api --> queue: async                                         (--> dashed, ==> thick, <-> both ways, --- no head)
    api ->|retry| api                                            (a label can sit in |bars| too)
    group Backend: api, queue, db                                (a labelled box around nodes)
    [*] -> idle -> running -> [*]                                (start and end markers)

Shapes in the shorthand: [text] box, (text) rounded, {text} decision, [(text)] store, ((text)) circle.
Kinds: proc dec data model owner ext plan start end state record note danger ok circle.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .common import (Ctx, PresetError, esc, fields, fmt, marker_defs, num, preset, svg_open, text_el, tw, uid, wrap)

KINDS = {"proc", "dec", "data", "model", "owner", "ext", "plan", "start", "end", "state", "record", "note",
         "danger", "ok", "circle", "info"}
ARROW = re.compile(r"\s*(<-->|<->|==>|-\.->|-->|---|->)\s*(?:\|([^|]*)\|\s*)?")
BRACKETS = re.compile(r"\[\(.*?\)\]|\(\(.*?\)\)|\[\[.*?\]\]|\[.*?\]|\(.*?\)|\{.*?\}")
REF = re.compile(r"^([A-Za-z0-9_.\-]+|STARMARK)\s*(\x00\d+\x00)?$")


@dataclass
class Node:
    id: str
    label: str
    kind: str = "proc"
    sub: str = ""
    link: str = ""
    rows: list[str] = field(default_factory=list)
    w: float = 0
    h: float = 0
    x: float = 0
    y: float = 0
    layer: int = 0
    dummy: bool = False
    lane: int = 0
    col: float = 0


@dataclass
class Edge:
    a: str
    b: str
    label: str = ""
    style: str = "solid"            # solid | dash | thick | line
    both: bool = False
    back: bool = False
    chain: list[str] = field(default_factory=list)      # dummy node ids between a and b


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    groups: list[tuple[str, list[str]]] = field(default_factory=list)
    _anon: int = 0

    def node(self, ident: str, label: str | None = None, kind: str | None = None) -> Node:
        n = self.nodes.get(ident)
        if n is None:
            n = self.nodes[ident] = Node(ident, label if label is not None else ident.replace("_", " "), kind or "proc")
        else:
            if label is not None:
                n.label = label
            if kind:
                n.kind = kind
        return n


def _shape(text: str) -> tuple[str, str]:
    t = text.strip()
    if t.startswith("[(") and t.endswith(")]"):
        return t[2:-2].strip(), "data"
    if t.startswith("((") and t.endswith("))"):
        return t[2:-2].strip(), "circle"
    if t.startswith("[[") and t.endswith("]]"):
        return t[2:-2].strip(), "model"
    if t.startswith("{") and t.endswith("}"):
        return t[1:-1].strip(), "dec"
    if t.startswith("(") and t.endswith(")"):
        return t[1:-1].strip(), "state"
    return t[1:-1].strip(), "proc"


def parse(lines: list[str], *, default_kind: str = "proc") -> Graph:
    g = Graph()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        m = re.match(r"^(?:node|n|entity|table)\s+(\S+)\s*(?:\|\s*(.*))?$", line, re.I)
        if m:
            ident, rest = m.group(1), m.group(2) or ""
            f = fields(rest, 5) if rest else [""] * 5
            is_record = line.lower().startswith(("entity", "table"))
            if is_record:
                label, rows = (f[0] or ident), [r.strip() for r in re.split(r"[;,]", f[1]) if r.strip()]
                n = g.node(ident, label, "record")
                n.rows = rows
                n.link = f[2]
                continue
            kind, sub, link = "", "", ""
            rest_fields = f[1:]
            if rest_fields[0].lower() in KINDS:
                kind, sub, link = rest_fields[0].lower(), rest_fields[1], rest_fields[2]
            else:
                sub, link = rest_fields[0], rest_fields[1]
            n = g.node(ident, f[0] or ident.replace("_", " "), kind or default_kind)
            n.sub, n.link = sub, link if link.startswith(("#", "http")) else ""
            continue
        m = re.match(r"^group\s+([^:]+):\s*(.+)$", line, re.I)
        if m:
            g.groups.append((m.group(1).strip(), [x.strip() for x in re.split(r"[,\s]+", m.group(2)) if x.strip()]))
            continue
        # edge chain -------------------------------------------------------- #
        masked: list[str] = []

        def keep(mm: re.Match) -> str:
            masked.append(mm.group(0))
            return f"\x00{len(masked) - 1}\x00"

        text = BRACKETS.sub(keep, line.replace("[*]", "STARMARK"))
        text, _, tail = text.partition(": ")
        parts = ARROW.split(text)
        if len(parts) < 3:
            raise PresetError(f"cannot read the line: {line!r} (expected `a -> b`, `node id | Label | kind`, or `group Name: a, b`)")
        refs, hops = parts[0::3], list(zip(parts[1::3], parts[2::3]))
        resolved: list[str] = []
        for pos, ref in enumerate(refs):
            ref = ref.strip()
            mm = REF.match(ref)
            if not mm:
                raise PresetError(f"cannot read the node reference {ref!r} in: {line!r}")
            ident, shape = mm.group(1), mm.group(2)
            if ident == "STARMARK":
                g._anon += 1
                is_target = pos > 0
                ident = f"__{'end' if is_target else 'start'}{g._anon}"
                g.node(ident, "", "end" if is_target else "start")
                resolved.append(ident)
                continue
            if shape:
                label, kind = _shape(masked[int(shape.strip("\x00"))])
                g.node(ident, label, kind)
            else:
                g.node(ident)
            resolved.append(ident)
        for k, (arrow, lab) in enumerate(hops):
            style = {"->": "solid", "-->": "dash", "-.->": "dash", "==>": "thick", "---": "line", "<->": "solid",
                     "<-->": "dash"}[arrow]
            label = (lab or "").strip()
            if k == len(hops) - 1 and tail.strip() and not label:
                label = tail.strip()
            g.edges.append(Edge(resolved[k], resolved[k + 1], label, style, both=arrow.startswith("<")))
    if not g.nodes:
        raise PresetError("nothing to draw: add lines like `a -> b` or `node id | Label | kind`")
    return g


# --------------------------------------------------------------------------- #
# Sizes                                                                        #
# --------------------------------------------------------------------------- #
def measure(n: Node) -> None:
    k = n.kind
    n.lines = []                                                   # type: ignore[attr-defined]
    if n.dummy:
        n.w = n.h = 8
        return
    if k in ("start", "end"):
        n.w = n.h = 26
        n.lines = wrap(n.label, 120, 11, True) if n.label else []   # type: ignore[attr-defined]
        return
    if k == "record":
        widest = max([tw(n.label, 13, True)] + [tw(r, 12) for r in n.rows] + [90])
        n.w = widest + 34
        n.h = 32 + 21 * max(1, len(n.rows)) + 8
        return
    width = 190 if k != "dec" else 150
    lines = wrap(n.label, width, 13, True, 3)
    sub = wrap(n.sub, width + 20, 11, False, 3) if n.sub else []
    n.lines = lines                                                # type: ignore[attr-defined]
    n.sublines = sub                                               # type: ignore[attr-defined]
    text_w = max([tw(x, 13, True) for x in lines] + [tw(x, 11) for x in sub] + [60])
    body_h = 17 * len(lines) + (4 + 14 * len(sub) if sub else 0)
    if k == "dec":
        n.w = max(128, text_w * 1.45 + 40)
        n.h = max(70, body_h * 1.5 + 22)
    elif k == "circle":
        d = max(60, text_w + 26, body_h + 26)
        n.w = n.h = d
    elif k == "data":
        n.w = max(104, text_w + 34)
        n.h = body_h + 34
    else:
        n.w = max(104, text_w + 30)
        n.h = body_h + 24


# --------------------------------------------------------------------------- #
# Layered layout                                                               #
# --------------------------------------------------------------------------- #
def layout(g: Graph, direction: str) -> tuple[list[list[str]], dict[str, Node]]:
    """Assign layers (longest path), insert dummy nodes for long edges, order by barycentre, then place."""
    horiz = direction in ("lr", "rl")
    nodes = dict(g.nodes)
    for n in nodes.values():
        measure(n)
    out_edges: dict[str, list[Edge]] = {i: [] for i in nodes}
    for e in g.edges:
        if e.a in nodes and e.b in nodes and e.a != e.b:
            out_edges[e.a].append(e)
    # 1. break cycles ------------------------------------------------------- #
    state: dict[str, int] = {}

    def dfs(u: str) -> None:
        state[u] = 1
        for e in out_edges[u]:
            if state.get(e.b) == 1:
                e.back = True
            elif e.b not in state:
                dfs(e.b)
        state[u] = 2

    for i in nodes:
        if i not in state:
            dfs(i)
    fwd = [e for e in g.edges if not e.back and e.a != e.b and e.a in nodes and e.b in nodes]
    # 2. layers: longest path, then pull sources next to their first successor --- #
    layer = {i: 0 for i in nodes}
    for _ in range(len(nodes) + 1):
        changed = False
        for e in fwd:
            if layer[e.b] < layer[e.a] + 1:
                layer[e.b] = layer[e.a] + 1
                changed = True
        if not changed:
            break
    has_in = {e.b for e in fwd}
    for i in nodes:
        succ = [layer[e.b] for e in fwd if e.a == i]
        if i not in has_in and succ:
            layer[i] = min(succ) - 1
    low = min(layer.values())
    for i in layer:
        layer[i] -= low
    # 3. dummy nodes -------------------------------------------------------- #
    seg: list[tuple[str, str]] = []
    count = 0
    for e in fwd:
        span = layer[e.b] - layer[e.a]
        chain = [e.a]
        for k in range(1, span):
            count += 1
            did = f"~{count}"
            d = Node(did, "", "dummy", dummy=True)
            measure(d)
            nodes[did] = d
            layer[did] = layer[e.a] + k
            chain.append(did)
            e.chain.append(did)
        chain.append(e.b)
        seg.extend(zip(chain, chain[1:]))
    depth = max(layer.values()) + 1
    layers: list[list[str]] = [[] for _ in range(depth)]
    for i in nodes:
        layers[layer[i]].append(i)
    up: dict[str, list[str]] = {i: [] for i in nodes}
    down: dict[str, list[str]] = {i: [] for i in nodes}
    for a, b in seg:
        down[a].append(b)
        up[b].append(a)
    # 4. order: barycentre sweeps ------------------------------------------- #
    pos = {i: k for lay in layers for k, i in enumerate(lay)}

    def sweep(rng, nbrs) -> None:
        for l in rng:
            layers[l].sort(key=lambda i: (sum(pos[j] for j in nbrs[i]) / len(nbrs[i])) if nbrs[i] else pos[i])
            for k, i in enumerate(layers[l]):
                pos[i] = k

    for _ in range(6):
        sweep(range(1, depth), up)
        sweep(range(depth - 2, -1, -1), down)
    # 5. coordinates: cross axis relaxed toward neighbours ------------------ #
    def dv(i: str) -> float:
        n = nodes[i]
        return n.h if horiz else n.w

    def du(i: str) -> float:
        n = nodes[i]
        return n.w if horiz else n.h

    gap_v = 26.0
    cross = {i: 0.0 for i in nodes}
    for lay in layers:
        total = sum(dv(i) for i in lay) + gap_v * (len(lay) - 1)
        y = -total / 2
        for i in lay:
            cross[i] = y + dv(i) / 2
            y += dv(i) + gap_v

    def settle(lay: list[str], want: dict[str, float]) -> None:
        vs, prev = [], None
        for i in lay:
            v = want[i]
            if prev is not None:
                v = max(v, cross[prev] + dv(prev) / 2 + gap_v + dv(i) / 2)
            cross[i] = v
            prev = i
        if lay:
            shift = sum(want[i] - cross[i] for i in lay) / len(lay)
            for i in lay:
                cross[i] += shift

    for _ in range(10):
        for rng, nbrs in ((range(1, depth), up), (range(depth - 2, -1, -1), down)):
            for l in rng:
                want = {i: (sum(cross[j] for j in nbrs[i]) / len(nbrs[i]) if nbrs[i] else cross[i]) for i in layers[l]}
                settle(layers[l], want)
    # 6. along axis ---------------------------------------------------------- #
    labelled = any(e.label for e in g.edges)
    gap_u = 74.0 + (34.0 if labelled else 0.0) + (10.0 if not horiz else 0.0)
    along: list[float] = []
    cursor = 0.0
    for lay in layers:
        thick = max([du(i) for i in lay if not nodes[i].dummy] or [20])
        along.append(cursor + thick / 2)
        cursor += thick + gap_u
    total_u = cursor - gap_u
    for l, lay in enumerate(layers):
        for i in lay:
            u, v = along[l], cross[i]
            if direction == "lr":
                nodes[i].x, nodes[i].y = u, v
            elif direction == "rl":
                nodes[i].x, nodes[i].y = total_u - u, v
            elif direction == "tb":
                nodes[i].x, nodes[i].y = v, u
            else:
                nodes[i].x, nodes[i].y = v, total_u - u
    return layers, nodes


# --------------------------------------------------------------------------- #
# Drawing                                                                      #
# --------------------------------------------------------------------------- #
def _curve(pts: list[tuple[float, float]], horiz: bool) -> str:
    d = f"M{fmt(pts[0][0])},{fmt(pts[0][1])}"
    for (px, py), (qx, qy) in zip(pts, pts[1:]):
        if horiz:
            k = (qx - px) / 2
            d += f" C{fmt(px + k)},{fmt(py)} {fmt(qx - k)},{fmt(qy)} {fmt(qx)},{fmt(qy)}"
        else:
            k = (qy - py) / 2
            d += f" C{fmt(px)},{fmt(py + k)} {fmt(qx)},{fmt(qy - k)} {fmt(qx)},{fmt(qy)}"
    return d


def draw_node(n: Node, i: int) -> str:
    x, y, w, h = n.x - n.w / 2, n.y - n.h / 2, n.w, n.h
    k = n.kind
    lines, sub = getattr(n, "lines", []), getattr(n, "sublines", [])
    shape = ""
    text = ""
    if k == "dec":
        shape = (f'<polygon class="pv-shape" points="{fmt(n.x)},{fmt(y)} {fmt(x + w)},{fmt(n.y)} '
                 f'{fmt(n.x)},{fmt(y + h)} {fmt(x)},{fmt(n.y)}"/>')
    elif k == "data":
        ry = 9
        shape = (f'<path class="pv-shape" d="M{fmt(x)},{fmt(y + ry)} a{fmt(w / 2)},{ry} 0 0 1 {fmt(w)},0 v{fmt(h - 2 * ry)} '
                 f'a{fmt(w / 2)},{ry} 0 0 1 {fmt(-w)},0 z"/>'
                 f'<path class="pv-line" d="M{fmt(x)},{fmt(y + ry)} a{fmt(w / 2)},{ry} 0 0 0 {fmt(w)},0"/>')
    elif k == "circle":
        shape = f'<circle class="pv-shape" cx="{fmt(n.x)}" cy="{fmt(n.y)}" r="{fmt(w / 2)}"/>'
    elif k == "start":
        shape = f'<circle class="pv-shape solid" cx="{fmt(n.x)}" cy="{fmt(n.y)}" r="9"/>'
    elif k == "end":
        shape = (f'<circle class="pv-shape" cx="{fmt(n.x)}" cy="{fmt(n.y)}" r="11"/>'
                 f'<circle class="pv-shape solid" cx="{fmt(n.x)}" cy="{fmt(n.y)}" r="6"/>')
    elif k == "record":
        shape = (f'<rect class="pv-shape" x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="9"/>'
                 f'<path class="pv-head" d="M{fmt(x)},{fmt(y + 30)} v-21 a9,9 0 0 1 9,-9 h{fmt(w - 18)} a9,9 0 0 1 9,9 v21 z"/>'
                 f'<path class="pv-line" d="M{fmt(x)},{fmt(y + 30)} h{fmt(w)}"/>')
        text = f'<text class="pv-t" x="{fmt(n.x)}" y="{fmt(y + 20)}" text-anchor="middle">{esc(n.label)}</text>'
        for r, row in enumerate(n.rows):
            parts = row.split(None, 1)
            name, rest = (parts[0], parts[1]) if len(parts) > 1 else (row, "")
            ry_ = y + 30 + 21 * r + 17
            text += f'<text class="pv-s row" x="{fmt(x + 14)}" y="{fmt(ry_)}">{esc(name)}</text>'
            if rest:
                text += f'<text class="pv-s key" x="{fmt(x + w - 14)}" y="{fmt(ry_)}" text-anchor="end">{esc(rest)}</text>'
    else:
        rx = {"model": min(h / 2, 30), "state": 16}.get(k, 10)
        shape = f'<rect class="pv-shape" x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="{fmt(rx)}"/>'
    if k not in ("record",):
        if k in ("start", "end"):
            if lines:
                text = text_el(n.x, n.y + 28, lines, "pv-s", 13, "middle")
        else:
            block = 17 * len(lines) + (4 + 14 * len(sub) if sub else 0)
            top = n.y - block / 2 + 13
            text = text_el(n.x, top, lines, "pv-t", 17, "middle")
            if sub:
                text += text_el(n.x, top + 17 * len(lines) - 13 + 17, sub, "pv-s", 14, "middle")
    g = f'<g class="pv-n k-{k}" style="--i:{i}">{shape}{text}</g>'
    return f'<a href="{esc(n.link)}">{g}</a>' if n.link else g


def render(g: Graph, direction: str, ctx: Ctx, label: str) -> str:
    horiz = direction in ("lr", "rl")
    layers, nodes = layout(g, direction)
    real = [n for n in nodes.values() if not n.dummy]
    margin = 28.0
    minx = min(n.x - n.w / 2 for n in real)
    miny = min(n.y - n.h / 2 for n in real)
    group_boxes = []
    for title, members in g.groups:
        ms = [nodes[m] for m in members if m in nodes]
        if ms:
            gx0 = min(n.x - n.w / 2 for n in ms) - 24
            gy0 = min(n.y - n.h / 2 for n in ms) - 40
            gx1 = max(n.x + n.w / 2 for n in ms) + 24
            gy1 = max(n.y + n.h / 2 for n in ms) + 22
            group_boxes.append((title, gx0, gy0, gx1, gy1))
            minx, miny = min(minx, gx0), min(miny, gy0)
    dx, dy = margin - minx, margin - miny
    for n in nodes.values():
        n.x += dx
        n.y += dy
    group_boxes = [(t, a + dx, b + dy, c + dx, d + dy) for t, a, b, c, d in group_boxes]
    maxx = max([n.x + n.w / 2 for n in real] + [b[3] for b in group_boxes])
    maxy = max([n.y + n.h / 2 for n in real] + [b[4] for b in group_boxes])
    mid = uid("mk")
    parts = [marker_defs(mid)]
    for title, x0, y0, x1, y1 in group_boxes:
        parts.append(f'<g class="pv-n pv-zone-g" style="--i:0"><rect class="pv-zone" x="{fmt(x0)}" y="{fmt(y0)}" '
                     f'width="{fmt(x1 - x0)}" height="{fmt(y1 - y0)}" rx="16"/>'
                     f'<text class="pv-zone-t" x="{fmt(x0 + 16)}" y="{fmt(y0 + 24)}">{esc(title)}</text></g>')
    labels: list[tuple[float, float, str]] = []
    paths: list[str] = []
    packets: list[str] = []
    speed = num(ctx.kv.get("speed", "1"), 1) or 1
    back_k = 0
    for idx, e in enumerate(g.edges):
        if e.a not in nodes or e.b not in nodes:
            continue
        a, b = nodes[e.a], nodes[e.b]
        cls = {"dash": "pv-edge dash", "thick": "pv-edge thick", "line": "pv-edge"}.get(e.style, "pv-edge")
        eid = uid("ed")
        head = "" if e.style == "line" else f' marker-end="url(#{mid})"'
        tail = f' marker-start="url(#{mid})"' if e.both else ""
        if e.a == e.b:                                               # self loop on the top
            x0, y0 = a.x - 12, a.y - a.h / 2
            d = f"M{fmt(x0)},{fmt(y0)} C{fmt(x0 - 10)},{fmt(y0 - 40)} {fmt(x0 + 46)},{fmt(y0 - 40)} {fmt(x0 + 34)},{fmt(y0)}"
            lx, ly = x0 + 12, y0 - 36
            if y0 - 44 < 0:
                pass
        elif e.back:
            back_k += 1
            if horiz:
                sx, sy, tx, ty = a.x, a.y + a.h / 2, b.x, b.y + b.h / 2
                low = max(sy, ty) + 34 + 14 * back_k
                d = f"M{fmt(sx)},{fmt(sy)} C{fmt(sx)},{fmt(low)} {fmt(tx)},{fmt(low)} {fmt(tx)},{fmt(ty)}"
                lx, ly = (sx + tx) / 2, low - 8
                maxy = max(maxy, low + 10)
            else:
                sx, sy, tx, ty = a.x + a.w / 2, a.y, b.x + b.w / 2, b.y
                far = max(sx, tx) + 40 + 14 * back_k
                d = f"M{fmt(sx)},{fmt(sy)} C{fmt(far)},{fmt(sy)} {fmt(far)},{fmt(ty)} {fmt(tx)},{fmt(ty)}"
                lx, ly = far - 4, (sy + ty) / 2
                maxx = max(maxx, far + 10)
        else:
            pts = [(nodes[c].x, nodes[c].y) for c in e.chain]
            if direction == "lr":
                s, t = (a.x + a.w / 2, a.y), (b.x - b.w / 2, b.y)
            elif direction == "rl":
                s, t = (a.x - a.w / 2, a.y), (b.x + b.w / 2, b.y)
            elif direction == "tb":
                s, t = (a.x, a.y + a.h / 2), (b.x, b.y - b.h / 2)
            else:
                s, t = (a.x, a.y - a.h / 2), (b.x, b.y + b.h / 2)
            allp = [s] + pts + [t]
            d = _curve(allp, horiz)
            m = allp[len(allp) // 2] if len(allp) > 2 else ((s[0] + t[0]) / 2, (s[1] + t[1]) / 2)
            lx, ly = m
        paths.append(f'<path id="{eid}" class="{cls} pv-e" style="--i:{idx}" pathLength="1000" d="{d}"{head}{tail}/>')
        if e.label:
            labels.append((lx, ly, e.label))
        if ctx.anim == "packets" and e.style != "line":                   # type: ignore[attr-defined]
            dur = (3.0 + 0.002 * (abs(b.x - a.x) + abs(b.y - a.y))) / speed
            packets.append(f'<circle class="pv-packet" r="4.5"><animateMotion dur="{dur:.2f}s" begin="{(idx * 0.45) % dur:.2f}s" '
                           f'repeatCount="indefinite" path="{d}"/></circle>')
    parts.extend(paths)
    parts.extend(packets)
    order = sorted((n for n in real), key=lambda n: (n.x if horiz else n.y))
    for i, n in enumerate(order):
        parts.append(draw_node(n, i))
    placed: list[tuple[float, float, float, float]] = []
    for lx, ly, text in labels:
        lines = wrap(text, 150, 10.5, False, 3)
        w = max(tw(x, 10.5) for x in lines) + 12
        h = len(lines) * 12.5 + 7
        for _ in range(8):
            box = (lx - w / 2, ly - h / 2, w, h)
            if not any(box[0] < o[0] + o[2] and o[0] < box[0] + box[2] and box[1] < o[1] + o[3] and o[1] < box[1] + box[3]
                       for o in placed):
                break
            ly += h + 3
        placed.append((lx - w / 2, ly - h / 2, w, h))
        parts.append(f'<g class="pv-lab"><rect x="{fmt(lx - w / 2)}" y="{fmt(ly - h / 2)}" width="{fmt(w)}" height="{fmt(h)}" rx="5"/>'
                     + text_el(lx, ly - h / 2 + 13, lines, "pv-l", 12.5, "middle") + "</g>")
        maxx, maxy = max(maxx, lx + w / 2 + 6), max(maxy, ly + h / 2 + 6)
    width, height = maxx + margin, maxy + margin
    return svg_open(width, height, label) + "".join(parts) + "</svg>"


def _describe(g: Graph, what: str) -> str:
    names = [n.label or n.id for n in g.nodes.values() if n.kind not in ("start", "end")][:8]
    return f"{what}: " + ", ".join(names)


@preset("flow", anim="packets", aliases=("flowchart",), group="graph",
        summary="Flowchart with automatic layout: boxes, decisions, stores, groups, labelled arrows.",
        syntax="a[API] -> b{Valid?} -> c[(DB)] | node id | Label | kind | sub | #link | group Name: a, b | options: lr tb rl bt")
def flow(ctx: Ctx) -> str:
    """Flowchart with automatic layout."""
    g = parse(ctx.lines)
    return render(g, ctx.dir("lr"), ctx, ctx.kv.get("title") or _describe(g, "Flowchart"))


@preset("state", anim="trace", group="graph", aliases=("statemachine",),
        summary="State machine: rounded states, [*] start and end, labelled transitions.",
        syntax="[*] -> idle -> running: start | running -> idle: stop | running -> [*]")
def state(ctx: Ctx) -> str:
    """State machine."""
    g = parse(ctx.lines, default_kind="state")
    for n in g.nodes.values():
        if n.kind == "proc":
            n.kind = "state"
    return render(g, ctx.dir("lr"), ctx, ctx.kv.get("title") or _describe(g, "State machine"))


@preset("er", anim="reveal", group="graph", aliases=("erd", "schema"),
        summary="Entity-relationship / schema diagram: tables with rows and relations.",
        syntax="entity users | Users | id pk; email unique; name | table orders | Orders | id pk; user_id fk | users -> orders: 1..n")
def er(ctx: Ctx) -> str:
    """Entity-relationship diagram."""
    g = parse(ctx.lines)
    for e in g.edges:
        e.style = e.style if e.style in ("dash", "thick") else "solid"
    return render(g, ctx.dir("lr"), ctx, ctx.kv.get("title") or _describe(g, "Entities"))


# --------------------------------------------------------------------------- #
# Network (force-directed, undirected)                                         #
# --------------------------------------------------------------------------- #
@preset("network", anim="pulse", aliases=("graph", "dependencies"), group="graph",
        summary="Force-directed network of nodes (dependencies, relationships); node size follows how connected it is.",
        syntax="a --- b | a -> b | node id | Label | kind | options: width=900 height=520")
def network(ctx: Ctx) -> str:
    """Force-directed network."""
    g = parse(ctx.lines)
    ids = list(g.nodes)
    n = len(ids)
    W, H = num(ctx.kv.get("width", "900"), 900), num(ctx.kv.get("height", "540"), 540)
    deg = {i: 0 for i in ids}
    for e in g.edges:
        deg[e.a] += 1
        deg[e.b] += 1
    px = {i: W / 2 + math.cos(2 * math.pi * k / n) * W * 0.32 for k, i in enumerate(ids)}
    py = {i: H / 2 + math.sin(2 * math.pi * k / n) * H * 0.32 for k, i in enumerate(ids)}
    k_len = math.sqrt(W * H / max(n, 1)) * 0.75
    for step in range(260):
        t = 1 - step / 260
        fx = {i: 0.0 for i in ids}
        fy = {i: 0.0 for i in ids}
        for a in range(n):
            for b in range(a + 1, n):
                i, j = ids[a], ids[b]
                dx, dy = px[i] - px[j], py[i] - py[j]
                d = math.hypot(dx, dy) or 0.01
                f = k_len * k_len / d
                fx[i] += dx / d * f
                fy[i] += dy / d * f
                fx[j] -= dx / d * f
                fy[j] -= dy / d * f
        for e in g.edges:
            if e.a == e.b:
                continue
            dx, dy = px[e.a] - px[e.b], py[e.a] - py[e.b]
            d = math.hypot(dx, dy) or 0.01
            f = d * d / k_len
            fx[e.a] -= dx / d * f
            fx[e.b] += dx / d * f
            fy[e.a] -= dy / d * f
            fy[e.b] += dy / d * f
        for i in ids:
            fx[i] += (W / 2 - px[i]) * 0.9
            fy[i] += (H / 2 - py[i]) * 0.9
            mag = math.hypot(fx[i], fy[i]) or 0.01
            lim = 24 * t + 1
            px[i] += fx[i] / mag * min(mag, lim)
            py[i] += fy[i] / mag * min(mag, lim)
    minx, maxx = min(px.values()), max(px.values())
    miny, maxy = min(py.values()), max(py.values())
    pad = 70
    sx = (W - 2 * pad) / ((maxx - minx) or 1)
    sy = (H - 2 * pad) / ((maxy - miny) or 1)
    s = min(sx, sy) if n > 1 else 1
    ox = (W - (maxx - minx) * s) / 2 - minx * s
    oy = (H - (maxy - miny) * s) / 2 - miny * s
    pos = {i: (px[i] * s + ox, py[i] * s + oy) for i in ids}
    mid = uid("mk")
    parts = [marker_defs(mid)]
    packets = []
    for idx, e in enumerate(g.edges):
        (x1, y1), (x2, y2) = pos[e.a], pos[e.b]
        if e.a == e.b:
            continue
        r1 = 10 + min(deg[e.a], 8) * 1.6
        r2 = 10 + min(deg[e.b], 8) * 1.6
        ang = math.atan2(y2 - y1, x2 - x1)
        sx_, sy_ = x1 + math.cos(ang) * r1, y1 + math.sin(ang) * r1
        ex_, ey_ = x2 - math.cos(ang) * (r2 + (4 if e.style != "line" else 0)), y2 - math.sin(ang) * (r2 + (4 if e.style != "line" else 0))
        d = f"M{fmt(sx_)},{fmt(sy_)} L{fmt(ex_)},{fmt(ey_)}"
        cls = {"dash": "pv-edge dash", "thick": "pv-edge thick"}.get(e.style, "pv-edge")
        head = "" if e.style == "line" else f' marker-end="url(#{mid})"'
        parts.append(f'<path class="{cls} pv-e" style="--i:{idx}" pathLength="1000" d="{d}"{head}/>')
        if ctx.anim == "packets" and e.style != "line":                  # type: ignore[attr-defined]
            packets.append(f'<circle class="pv-packet" r="3.5"><animateMotion dur="2.6s" begin="{(idx * 0.3) % 2.6:.2f}s" '
                           f'repeatCount="indefinite" path="{d}"/></circle>')
        if e.label:
            parts.append(f'<text class="pv-l" x="{fmt((x1 + x2) / 2)}" y="{fmt((y1 + y2) / 2 - 4)}" text-anchor="middle">{esc(e.label)}</text>')
    parts.extend(packets)
    for i, nid in enumerate(ids):
        node = g.nodes[nid]
        x, y = pos[nid]
        r = 10 + min(deg[nid], 8) * 1.6
        body = (f'<g class="pv-n k-{node.kind}" style="--i:{i}"><circle class="pv-shape" cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(r)}"/>'
                f'<text class="pv-t" x="{fmt(x)}" y="{fmt(y + r + 15)}" text-anchor="middle">{esc(node.label)}</text></g>')
        parts.append(f'<a href="{esc(node.link)}">{body}</a>' if node.link else body)
    return svg_open(W, H, ctx.kv.get("title") or _describe(g, "Network")) + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- #
# Swimlane                                                                     #
# --------------------------------------------------------------------------- #
@preset("swimlane", anim="trace", aliases=("lanes", "functional-flow"), group="graph",
        summary="Swimlane flow: actors as rows, stages as columns, decisions and the information on each arrow.",
        syntax="lane Owner | who they are | col Stage name | node id | lane | col | kind | Title | sub | a -> b: label")
def swimlane(ctx: Ctx) -> str:
    """Swimlane flow: lanes (rows) by stages (columns)."""
    lanes: list[tuple[str, str]] = []
    cols: list[str] = []
    g = Graph()
    raw_edges: list[str] = []
    for line in ctx.lines:
        m = re.match(r"^lane\s+(.*)$", line, re.I)
        if m:
            f = fields(m.group(1), 2)
            lanes.append((f[0], f[1]))
            continue
        m = re.match(r"^(?:col|stage|column)\s+(.*)$", line, re.I)
        if m:
            cols.append(m.group(1).strip())
            continue
        m = re.match(r"^node\s+(\S+)\s*\|\s*(.*)$", line, re.I)
        if m:
            f = fields(m.group(2), 5)           # lane | col | kind | Title | sub
            lane_ref, col_ref = f[0], f[1]
            li = next((k for k, (nm, _) in enumerate(lanes) if nm.lower() == lane_ref.lower()), None)
            if li is None:
                li = int(num(lane_ref, -1)) if lane_ref.lstrip("-").isdigit() else None
            if li is None or not (0 <= li < len(lanes)):
                raise PresetError(f"node {m.group(1)}: unknown lane {lane_ref!r}; declare it with `lane Name | description` first")
            ci = next((k for k, nm in enumerate(cols) if nm.lower() == col_ref.lower()), None)
            if ci is None:
                ci = num(col_ref, -1)
            if ci < 0 or ci >= len(cols):
                raise PresetError(f"node {m.group(1)}: unknown column {col_ref!r}; declare it with `col Name` first")
            kind = f[2].lower() if f[2].lower() in KINDS else "proc"
            n = g.node(m.group(1), f[3] or m.group(1), kind)
            n.sub, n.lane, n.col = f[4], li, ci
            continue
        raw_edges.append(line)
    if not lanes or not cols:
        raise PresetError("a swimlane needs `lane Name | description` and `col Name` lines before its nodes")
    if raw_edges:
        eg = parse(raw_edges)
        for e in eg.edges:
            if e.a in g.nodes and e.b in g.nodes:
                g.edges.append(e)
            else:
                raise PresetError(f"edge {e.a} -> {e.b}: both ends must be declared with `node id | lane | col | kind | Title | sub`")
    LEFT, COL_W, LANE_H, TOP, NW, NH = 190, 250, 150, 70, 196, 74
    width = LEFT + len(cols) * COL_W + 30
    height = TOP + len(lanes) * LANE_H + 30
    mid = uid("mk")
    mid_b = uid("mk")
    parts = [marker_defs(mid),
             f'<defs><marker id="{mid_b}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" orient="auto-start-reverse">'
             '<path class="pv-arrow back" d="M0 0L10 5L0 10z"/></marker></defs>']
    for i, name in enumerate(cols):
        x = LEFT + i * COL_W
        parts.append(f'<rect class="pv-col{" alt" if i % 2 else ""}" x="{x}" y="{TOP - 34}" width="{COL_W}" height="{len(lanes) * LANE_H + 34}"/>'
                     f'<text class="pv-col-t" x="{x + COL_W / 2}" y="{TOP - 14}" text-anchor="middle">{i + 1}. {esc(name)}</text>')
    for i, (name, sub) in enumerate(lanes):
        y = TOP + i * LANE_H
        parts.append(f'<line class="pv-lane-line" x1="10" y1="{y}" x2="{width - 10}" y2="{y}"/>'
                     f'<text class="pv-zone-t" x="18" y="{y + 26}">{esc(name)}</text>'
                     + text_el(18, y + 46, wrap(sub, 150, 11, False, 4), "pv-s", 15))
    parts.append(f'<line class="pv-lane-line" x1="10" y1="{TOP + len(lanes) * LANE_H}" x2="{width - 10}" y2="{TOP + len(lanes) * LANE_H}"/>')

    def centre(n: Node) -> tuple[float, float]:
        return LEFT + n.col * COL_W + COL_W / 2, TOP + n.lane * LANE_H + LANE_H / 2

    def half(n: Node) -> tuple[float, float]:
        return (NH * 0.62 * 1.55, NH * 0.62) if n.kind == "dec" else (NW / 2, NH / 2)

    used: dict[tuple[str, int], int] = {}

    def slot(kind: str, idx: int) -> int:
        k = used.get((kind, idx), 0)
        used[(kind, idx)] = k + 1
        return (k % 3) * 6

    labels, paths, packets = [], [], []
    for idx, e in enumerate(g.edges):
        a, b = g.nodes[e.a], g.nodes[e.b]
        (ax, ay), (bx, by) = centre(a), centre(b)
        (ahw, ahh), (bhw, bhh) = half(a), half(b)
        back = e.style == "dash"
        if a.lane == b.lane and abs(a.col - b.col) == 1:
            sx = 1 if b.col > a.col else -1
            pts = [(ax + sx * ahw, ay), (bx - sx * bhw, by)]
            lx, ly = (pts[0][0] + pts[1][0]) / 2, ay - 16
        else:
            down = b.lane >= a.lane
            yg = TOP + (a.lane + 1) * LANE_H - 14 - slot("lane", a.lane + 1) if down else TOP + a.lane * LANE_H + 14 + slot("lane", a.lane)
            if b.col > a.col:
                side, xg = -1, LEFT + b.col * COL_W + 6 + slot("colL", int(b.col))
            else:
                side, xg = 1, LEFT + (b.col + 1) * COL_W - 6 - slot("colR", int(b.col))
            start = (ax, ay + (ahh if down else -ahh))
            end = (bx + side * bhw, by)
            pts = [start, (ax, yg), (xg, yg), (xg, by), end]
            lx, ly = (ax + xg) / 2, yg
            if abs(xg - ax) < 70:
                lx, ly = xg, (yg + by) / 2
        d = "M" + " L".join(f"{fmt(x)},{fmt(y)}" for x, y in pts)
        eid = uid("ed")
        cls = "pv-edge dash back" if back else "pv-edge"
        paths.append(f'<path id="{eid}" class="{cls} pv-e" style="--i:{idx}" pathLength="1000" d="{d}" marker-end="url(#{mid_b if back else mid})"/>')
        if e.label:
            labels.append((lx, ly, e.label, back))
        if ctx.anim == "packets":                                           # type: ignore[attr-defined]
            packets.append(f'<circle class="pv-packet" r="4.5"><animateMotion dur="4s" begin="{(idx * 0.5) % 4:.2f}s" repeatCount="indefinite" path="{d}"/></circle>')
    parts.extend(paths)
    parts.extend(packets)
    for i, (key, n) in enumerate(g.nodes.items()):
        n.x, n.y = centre(n)
        n.w, n.h = (half(n)[0] * 2, half(n)[1] * 2) if n.kind == "dec" else (NW, NH)
        n.lines = wrap(n.label, NW - 20 if n.kind != "dec" else 130, 13, True, 2)                  # type: ignore[attr-defined]
        n.sublines = wrap(n.sub, NW - 20, 11, False, 2) if n.sub else []                         # type: ignore[attr-defined]
        parts.append(draw_node(n, i))
    placed: list[tuple[float, float, float, float]] = []
    for lx, ly, text, back in labels:
        lines = wrap(text, 160, 10.5, False, 3)
        w = max(tw(x, 10.5) for x in lines) + 12
        h = len(lines) * 12.5 + 7
        for _ in range(8):
            box = (lx - w / 2, ly - h / 2, w, h)
            if not any(box[0] < o[0] + o[2] and o[0] < box[0] + box[2] and box[1] < o[1] + o[3] and o[1] < box[1] + box[3] for o in placed):
                break
            ly += h + 3
        placed.append((lx - w / 2, ly - h / 2, w, h))
        parts.append(f'<g class="pv-lab{" back" if back else ""}"><rect x="{fmt(lx - w / 2)}" y="{fmt(ly - h / 2)}" width="{fmt(w)}" height="{fmt(h)}" rx="5"/>'
                     + text_el(lx, ly - h / 2 + 13, lines, "pv-l", 12.5, "middle") + "</g>")
    svg = svg_open(width, height, ctx.kv.get("title") or "Swimlane flow").replace(f"min-width:{int(min(width, 820))}px", f"min-width:{int(min(width, 1400))}px")
    return svg + "".join(parts) + "</svg>"
