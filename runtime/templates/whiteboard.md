---
id: whiteboard
title: Whiteboard
group: Plan
order: 81
status: done
summary: Sketch flows, plan ideas, doodle. Boards save into the repository (docs/whiteboard/) when the docs are opened through the studio server.
---

<div class="wb-embed"><iframe src="whiteboard/index.html" title="Whiteboard" loading="lazy"></iframe></div>

:::details How saving works
- Opened through `python docs/site/studio.py start`: every change is saved to `docs/whiteboard/<board>.excalidraw` within two seconds. Set `"server": {"commit_edits": true}` in `docs/studio.json` to also commit saves.
- Opened as a plain file: boards are kept in this browser only; use the editor's menu (**Save to…**) to download a `.excalidraw` file.
- Several boards: **New**, **Rename**, **Delete**.
- The editor is Excalidraw 0.17.6 (MIT, github.com/excalidraw/excalidraw), vendored in `docs/site/whiteboard/vendor` so it works offline.
:::
