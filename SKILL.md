---
name: docs-studio
description: Sets up and maintains a live documentation site for ANY project - written pages with diagrams (flow, sequence, swimlane, architecture layers, system maps, trees, ER, charts, gantt and 20+ more presets with animations), pages scanned from the repo on every commit (folder map, import graph, activity, dependencies, TODOs), an editable status board and an Excalidraw whiteboard. Call it once per project; afterwards the server starts by itself in every session and a post-commit hook rebuilds the docs. Use when the user asks to document a project, draw or animate an architecture / flow / sequence / data-model diagram, build a docs site, keep docs current, add a whiteboard or status board, or says "docs studio". Also use for later requests like "add a diagram of X", "refresh the docs", "stop the docs server".
---

# docs-studio

A project-agnostic docs site that lives in the project's `docs/` folder. The runtime (builder, server, theme, 20+ diagram presets with animations, scanners, board, whiteboard) contains **no project facts**; Claude writes the project's pages from what it reads, and scanners derive the rest from the repository.

You call this skill **once per project**. The installer registers a SessionStart hook (server starts in every later session) and a git post-commit hook (docs rebuild after every commit).

## Decide what the user wants

| The user wants | Do |
|---|---|
| docs / a docs site / "set this project up" (project has no `docs/site/studio.py`) | **Setup** |
| docs already installed and they want pages updated, or the SessionStart note says pages lag the code | **Refresh** |
| a particular diagram or animation | **Add a diagram** |
| to turn it off / remove hooks | **Uninstall** |
| anything unclear: audience, what to cover, which folder, whether to commit the generated page | **Ask first.** Do not guess; one short question with 2–3 options. |

## Setup

1. **Install** (idempotent; re-running updates the runtime and never touches the project's content):
   ```
   python "${CLAUDE_SKILL_DIR}/scripts/install.py" --project . [--name "Project name"] [--docs-dir docs]
   ```
   `${CLAUDE_SKILL_DIR}` is this skill's folder (normally `~/.claude/skills/docs-studio`). Read the JSON it prints. It copied the runtime to `docs/`, wrote `docs/studio.json`, registered the SessionStart hook in `.claude/settings.json`, added the post-commit hook, built the site and started the server. If `pyyaml` shows `MISSING`, tell the user to run `python -m pip install pyyaml`.
   Do not use `--docs-dir` other than `docs` unless the user asked; if `docs/` already holds unrelated files, ask.
2. **Read the project** following `references/authoring.md` §1, and look at the scanned **Auto** pages. Ask the user about anything the repository cannot answer.
3. **Plan 3–12 pages** (authoring.md §2). Tell the user the plan in a few lines before writing.
4. **Write the pages** to `docs/site/src/NN-name.md`. Pick diagram presets by content (table in `references/presets.md`); prefer a visual before prose; check every arrow against the code. Seeded `board` and `whiteboard` pages already exist.
5. **Build and look**: `python docs/site/studio.py build`, fix any "Could not draw" warning, then open `python docs/site/studio.py url` in the browser pane and check each new page.
6. `python docs/site/studio.py reviewed`.
7. **Report**: the URL, the pages written, what the hooks do, and that the generated `docs/site/index.html` is rebuilt after each commit and left uncommitted for the next commit (ask whether it should be gitignored instead if the user dislikes that). Do not commit anything unless asked.

## Refresh

1. `python docs/site/studio.py changes` lists commits and areas changed since the pages were last reviewed.
2. Read those files; update only the pages and diagrams they affect; remove claims that are no longer true; mark finished work `done`.
3. Build, look, `python docs/site/studio.py reviewed`.

## Add a diagram

1. Choose the preset (`references/presets.md`, "Choosing a preset"); `python docs/site/studio.py presets` prints the live catalogue including project presets.
2. Insert the `:::name` block in the right page (or create a page), build, view, adjust. Keep it ≤ 12 nodes; split otherwise.
3. Motion: every preset has a good default. Override with `anim=packets|flow|trace|reveal|draw|pulse|glow|none`, or `static`. Use motion to explain (packets = data moving, trace = order of steps), never as decoration on dense diagrams.
4. A shape that no preset covers: write a project preset in `docs/site/presets_custom/` (see the end of `references/presets.md`), and tell the user.

## Commands (all from the project root)

```
python docs/site/studio.py start | stop | status | url     the server (127.0.0.1 only, port derived from the project path)
python docs/site/studio.py build [--no-scan] | check        rebuild / is the page stale
python docs/site/studio.py presets | icons                  catalogue / icon names
python docs/site/studio.py changes | reviewed               refresh bookkeeping
python docs/site/studio.py hosting netlify|vercel           config to publish docs/site (Netlify also gets shared whiteboards)
python docs/board/board.py list|add|move|update|remove      the status board from the command line
```

`SKIP_DOCS_HOOKS=1` skips the commit hook for one command.

## What got installed

- `docs/site/` builder, server, theme, presets, scanners · `docs/board/` board file and CLI · `docs/studio.json` settings (name, port, animation `auto|none|<name>`, scan options, `server.commit_edits`, `strict_scan`) · `docs/.studio/` runtime state (gitignored).
- `.claude/settings.json`: SessionStart hook → `studio.py hook session-start` (starts the server; says when the pages lag the code).
- Git `post-commit` (in `.githooks/` with `core.hooksPath` pointed at it, or appended to an existing hooks folder): rebuilds the docs in the background, never fails a commit.
- Board and whiteboard edits are saved to files; they are committed only if `"server": {"commit_edits": true}`.

## Uninstall

`python "${CLAUDE_SKILL_DIR}/scripts/install.py" --project . --uninstall` removes both hooks and stops the server; `docs/` stays (delete it by hand if wanted).

## Guardrails

- Never put secrets, tokens or internal addresses on a page; the build refuses key-shaped strings.
- Never edit `docs/site/index.html` by hand, and do not change runtime files in `docs/site/*.py` or `theme/` for one project's needs; use `presets_custom/`, `scanners/` and `studio.json`.
- Say only what the code shows; mark the rest `planned`; ask when unsure.
- The server binds to localhost only. Publishing is the user's call; `hosting` only writes config files.

Reference: `references/authoring.md` (how to read a project and write pages), `references/presets.md` (every preset with syntax and examples).
