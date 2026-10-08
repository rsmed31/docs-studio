# Diagram presets

Every preset is a `:::name` block in a page's Markdown. Options go on the first line (`:::flow lr anim=packets title="Request path"`), the body is plain lines. All of them: follow the site's light and dark theme, export to PNG/SVG, open full screen with pan and zoom, and are searchable. A bad body never breaks the build; it renders a warning that says what to fix.

`python docs/site/studio.py presets` prints this catalogue from the installed code (including presets the project added).

## Options that work on every diagram

| Option | Effect |
|---|---|
| `title="…"` | caption under the diagram, also the accessible name |
| `anim=NAME` | `reveal`, `flow`, `packets`, `pulse`, `draw`, `trace`, `glow`, `none` (each preset has a sensible default) |
| `static` | no motion |
| `speed=1.5` | animation speed multiplier |

Animations: **reveal** elements fade in one by one when scrolled into view (Replay button) · **draw** lines draw themselves, bars and slices grow · **flow** dashes march along connections · **packets** dots travel along connections · **trace** connections light up in order on a loop (walk through a sequence) · **pulse** / **glow** nodes breathe in turn. Visitors with reduced-motion set see everything still. Exports always show the finished picture.

## Choosing a preset

| You want to show | Use |
|---|---|
| how a request/data/work moves, with decisions | `flow` (`lr` wide, `tb` tall) |
| who does what, and when (several actors over stages) | `swimlane` |
| a conversation between components, in order | `sequence` |
| states and transitions | `state` |
| tables / entities / schema | `er` |
| the big picture: named areas and what talks to what | `zones` |
| an architecture stack (UI → services → data) | `layers` |
| a hierarchy, org chart, breakdown, folder tree | `tree` (`mindmap` for a radial feel) |
| how things relate with no direction/order | `network` |
| a repeating loop | `cycle` |
| levels, priorities, maturity | `pyramid` |
| a drop-off | `funnel` |
| shares of a whole | `donut` |
| values over time or by category | `chart line|area|column|stack` |
| comparing options across criteria | `radar`, `heatmap` |
| a schedule | `gantt` |
| prioritising (effort vs impact, risk vs likelihood) | `quadrant` |
| headline numbers | `stats` |
| linked tiles, steps, history, costs | `cards`, `steps`, `timeline`, `bars` |
| a live task board | `board` (one page, already seeded) |

---

## flow  (aliases: flowchart)
Layered automatic layout. Nodes can be declared or inferred from edges.
```
:::flow lr anim=packets title="Request path"
web[Web app] -> api[API gateway]: HTTPS
api -> auth{Valid token?}
auth -> svc[Orders service]: yes
auth --> deny[Reject]: no
svc -> db[(Postgres)]
svc -> queue[[Worker queue]]: async
queue -> svc: result
group Backend: api, auth, svc, queue, db
:::
```
- Shapes: `[box]` `(rounded)` `{decision}` `[(store)]` `((circle))` `[[model/service pill]]`; `[*]` is a start/end marker.
- Arrows: `->` solid · `-->` dashed · `==>` thick · `<->` both ways · `---` plain line. Label with `: text` or `->|text|`.
- Declare richer nodes: `node id | Label | kind | subtitle | #link`. Kinds: `proc dec data model owner ext plan start end state note danger ok circle`.
- `group Name: a, b, c` draws a labelled box around nodes. Back edges (cycles) are routed around automatically. Directions: `lr` `rl` `tb` `bt`.

## swimlane  (aliases: lanes)
Actors as rows, stages as columns.
```
:::swimlane
lane Owner | decides money and taste
lane System | does the work
col Request
col Plan
col Deliver
node brief | Owner | Request | owner | Write brief | idea and audience
node plan  | System | Plan | proc | Plan steps | agents and order
node ok    | Owner | Deliver | dec | Approve?
node out   | System | Deliver | data | Final file
brief -> plan: brief
plan -> ok: draft
ok -> out: yes
:::
```
`node id | lane | column | kind | Title | subtitle`. A `-->` edge is drawn as a red dashed "back" loop.

## sequence  (aliases: seq)
```
:::sequence
User | API | Database
User -> API: GET /orders
API -> Database: query
Database --> API: rows
API --> User: ! confirm export?
== After confirm ==
note API: streams the file
:::
```
First line lists actors. `->` call, `-->` reply (dashed), a leading `!` marks a question to a human (highlighted), `== text ==` is a phase band.

## state  (aliases: statemachine)
```
:::state
[*] -> idle
idle -> running: start
running -> paused: pause
paused -> running: resume
running -> [*]: done
:::
```

## er  (aliases: erd, schema)
```
:::er
entity users | Users | id pk; email unique; name
entity orders | Orders | id pk; user_id fk; total
users -> orders: 1..n
:::
```
`entity id | Title | row; row; row` — a row is `name` or `name annotation` (shown on the right).

## network  (aliases: graph, dependencies)
Force-directed. `a --- b` undirected, `a -> b` directed, `node id | Label | kind`. Node size grows with how connected it is. Options `width=900 height=540`.

## zones  (aliases: map)
```
:::zones cols=3 anim=packets
## You
- web | monitor | Web app | review and decide | done | #page
## Server
- api | server | API | rules and budgets | done
- jobs | cpu | Jobs | long tasks | running
web -> api: HTTPS
api --> jobs
:::
```
`- id | icon | Title | subtitle | status | #link`. Status `done|running|planned|blocked` styles the box. Icons: `python docs/site/studio.py icons` lists the names (`server cpu database cloud monitor users lock shield zap …`); unknown names show no icon.

## layers  (aliases: stack, architecture)
```
:::layers
## Presentation
- Web app | React | monitor | done
## Services
- API | REST | server | done | #api
## Data
- Postgres | primary store | database | done
:::
```
`- Box | subtitle | icon | status | #link`. Options: `up` (draw return arrows), `arrows=off`.

## tree  (aliases: hierarchy, org, breakdown)  ·  mindmap  (aliases: radial)
```
:::tree lr
Platform
  Frontend | web
    Pages
  Backend | #backend
:::
```
Indented list; `Label | subtitle | #link`. `tree` is `lr` by default, `tb` for top-down. `mindmap` takes the same body.

## cycle  (aliases: loop, lifecycle)
`- Step | one line | #link`, option `center="Release loop"`. Default animation `packets` (dots run round the loop).

## pyramid  ·  funnel
`pyramid`: `- Level | explanation` top first. `funnel`: `- Stage | number | note` (conversion between stages is computed).

## donut  (aliases: pie)
`- Label | value | note`, options `center="62%"`, `unit=%`.

## chart  (aliases: line, area, column, stack)
```
:::chart column
x: Q1 | Q2 | Q3
series A | 12 | 18 | 15
series B | 8 | 11 | 17
:::
```
Flags `line` (default) `area` `column` `stack`; options `unit=$`, `min=0`. Hover shows values.

## radar  ·  heatmap
`radar`: `axes: A | B | C | D` then `series Name | 3 | 4 | 2 | 5`, option `max=5`. `heatmap`: `cols: Mon | Tue` then `- Row | 1 | 4`, options `max=10 unit=%`.

## gantt  (aliases: schedule)
`- Task | 2026-01-05 | 2026-02-10 | status | group`. The end may be a duration: `3w`, `10d`. Colour by status (`done running planned blocked`) or, without status, by group. Flag `today` draws a marker (it changes the page every day, so leave it off for committed docs).

## quadrant  (aliases: matrix, 2x2)
```
:::quadrant
x: Effort
y: Impact
tl: Quick wins
tr: Big bets
- Cache | 0.2 | 0.8
:::
```
Scores 0–1 or 0–10. Optional tone as 4th field: `ok warn danger info`.

## stats  (aliases: kpi)
`- Label | value | +8% | 3,4,3,6,8 | note`. `+`/`-` colours the change; the comma list becomes a sparkline. Flags `2 3 4 5` set the columns.

---

## Older blocks (still available)

`:::cards [2|3|4] [mini|big]` (`icon | Title | text | small print | status | #link`) · `:::steps` (`Title | line | #link | status`) · `:::timeline` (`date | Title | text | #link | status`) · `:::bars $` (`Label | number | note | tone`) · `:::kanban` (`## Built` / `## In progress` / `## Planned`, then `ID | what | tag`) · `:::board` (the live status board) · `{{status-bar}}` · `{{auto:scan-overview}}` embeds a scanned section (see authoring.md) · `{{svg:name|caption}}` inlines `src/_assets/name.svg`.

## Add a preset to one project

Create `docs/site/presets_custom/my_diagram.py`:

```python
from presets.common import preset, PresetError, svg_open, esc, items, fields

@preset("badges", anim="reveal", summary="A row of badges.", syntax="- Label | note")
def badges(ctx):
    rows = [fields(i, 2) for i in items(ctx.body)]
    if not rows:
        raise PresetError("write `- Label | note` items")
    parts = []
    for k, (label, note) in enumerate(rows):
        parts.append(f'<g class="pv-n" style="--i:{k}"><rect class="pv-shape" x="{20 + k * 150}" y="20" width="140" height="48" rx="10"/>'
                     f'<text class="pv-t" x="{90 + k * 150}" y="50" text-anchor="middle">{esc(label)}</text></g>')
    return svg_open(40 + len(rows) * 150, 90, "Badges") + "".join(parts) + "</svg>"
```
Rules: return one `<svg>`; give animatable parts the class `pv-n` (node, with `style="--i:index"`) or `pv-e` (edge/line); use the `pv-*` and `k-*` classes for colours so dark mode works. Set `raw=True` on `@preset` to return plain HTML instead.
