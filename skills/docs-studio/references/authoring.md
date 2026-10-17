# Writing the pages

The runtime never contains project facts. Everything specific to a project lives in `docs/site/src/*.md` (written by Claude from what it reads in the repository) or is scanned at build time. This file is how to write those pages well.

## 1. Read before writing

Do not write from the project's name. Read, in this order, and stop when you can explain the project in two sentences:

1. `README*`, `CONTRIBUTING*`, existing `docs/`, `ARCHITECTURE*`, ADRs.
2. Manifests: `package.json`, `pyproject.toml`, `requirements*.txt`, `go.mod`, `Cargo.toml`, `pom.xml`, `*.csproj`, `Dockerfile`, `docker-compose*`, CI files.
3. The scanned pages: `python docs/site/studio.py build`, then look at **Auto → Project at a glance / Folder structure / Module dependencies**. They tell you where the code is and which parts depend on which.
4. Entry points: the files that start the app, route requests, define jobs or commands. Open them; do not infer.
5. `git log --oneline -30` for what is moving.

If the repository does not answer something a page needs (who the audience is, what is planned, what a term means), **ask the user** instead of inventing it. Mark anything not built yet as `planned`.

## 2. Plan the pages

Pick pages by what readers need, not by a template. Typical, and only if the project has the content:

| Page | Group | What goes in it |
|---|---|---|
| Home (`id: home`, `layout: home`) | Start here | one-paragraph purpose, a `zones` or `layers` map whose boxes link to pages, cards for the 3–6 things a reader wants to do |
| How it works | How it works | the main flow as `flow`/`swimlane`/`sequence`, then `:::details` for each step |
| Architecture | How it works | `layers` or `zones`, components table, what talks to what |
| Data model | How it works | `er` and the rules around the data |
| Run and deploy | Running it | `steps` for setup, environments, config table, costs as `bars` |
| Decisions | Plan | `:::decision` callouts, `timeline`, open questions |
| Glossary | Reference | terms the project defines |
| Status board / Whiteboard | Plan | already seeded; do not rewrite them |

6–12 pages is plenty. A small project may need 3. Never pad.

## 3. Page format

```
---
id: how-it-works          # link target: #how-it-works (required unique; defaults to the file name)
title: How it works
group: How it works       # sidebar group
order: 20                 # sort order across the whole site
status: done              # done | running | planned | (empty)
summary: One sentence under the title.
layout: home              # optional: home | board
---
```

Shape of a good page: one-line summary, **a visual first**, a short paragraph, then detail folded into `:::details Title` sections. Visual before prose; one idea per diagram; ≤ 12 nodes per diagram (split otherwise).

Markdown supported: `##`/`###` headings, paragraphs, nested bullet/numbered lists, tables, code fences, block quotes, `inline code`, **bold**, *italic*, `[text](#other-page)` and `[text](#page/section)` links, `---`, badges `[[planned]]` `[[done]]` `[[running]]`, callouts

```
:::note
Kinds: note, tip, warn, planned, done, running, decision, open.
:::
```

and `:::levels` (a toggle between `@@ Simple` and `@@ Detailed` versions of the same text). Diagram presets: see `presets.md`.

## 4. Use the scanned content, do not copy it

Scanned pages exist under **Auto** and update on every commit. Embed a section in a written page instead of pasting numbers:

```
{{auto:scan-overview}}     the stats, languages donut and folder bars
{{auto:scan-structure}}    folder tree
{{auto:scan-modules}}      import graph
{{auto:scan-activity}}     commits per week, contributors, latest commits
{{auto:scan-dependencies}} packages
{{auto:scan-todos}}        TODO / FIXME list
{{auto:scan-documents}}    markdown documents found in the repo
```

When a number or list can be derived from code, prefer a scanner. A project-specific scanner goes in `docs/site/scanners/<name>.py`:

```python
def scan(ctx):                         # ctx.root, ctx.files (tracked paths), ctx.read(path), ctx.run(*git_args), ctx.config
    routes = []
    for f in ctx.files:
        if f.endswith(".py"):
            for line in ctx.read(f).splitlines():
                if line.lstrip().startswith("@app.route"):
                    routes.append(f"- `{f}`: {line.strip()}")
    if not routes:
        return None
    return {"id": "routes", "title": "HTTP routes", "group": "Auto", "order": 335,
            "summary": "Every route decorator in the code.", "markdown": "\n".join(routes)}
```
Disable a built-in with `"scan": {"disable": ["todos"]}` in `docs/studio.json`; hide paths with `"scan": {"ignore": ["^legacy/"]}` (regular expressions).

## 5. Rules

- No secrets, tokens, internal addresses, customer data. The build refuses to write a page that contains a key-shaped string; set `"strict_scan": true` in `studio.json` to also refuse IP addresses and long hex strings.
- Say what exists today; mark the rest `planned`. A diagram is a claim about the code: check each arrow against the code before you draw it.
- Names in diagrams are the names used in the code.
- Keep each diagram's labels short; put detail in the subtitle field or in the text below.
- Do not hand-edit `docs/site/index.html`; it is rebuilt.
- Pages are for the project's readers (teammates, agents, stakeholders), not a log of what you did.

## 6. Verify

1. `python docs/site/studio.py build` — read its output; fix any "Could not draw" warning (the message says which line).
2. Open the server URL (`python docs/site/studio.py url`) in the browser pane and look at every new page: diagrams readable, nothing clipped, links open the right page, light and dark.
3. `python docs/site/studio.py reviewed` — records that the pages match the code now (the commit hook counts changes from this point).
