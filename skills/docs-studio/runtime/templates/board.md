---
id: board
title: Status board
group: Plan
order: 80
layout: board
summary: Every task on one board, kept in the repository. Drag cards, edit them, add your own.
---

:::board
:::

:::note
**One board, one source.** The board is the file `docs/board/board.yaml`; this page is its view. To edit it and save into the repository, open the docs through the studio server (`python docs/site/studio.py start`). Opened as a plain file the board still works, but changes stay in this browser until you download `board.yaml`.
:::

:::details For agents: update the board from the command line
From the repository root (Python and PyYAML only):

```
python docs/board/board.py list --column running
python docs/board/board.py add --title "Write the importer" --column planned --owner agent
python docs/board/board.py move <id> running
python docs/board/board.py update <id> --description "what changed"
python docs/board/board.py remove <id>
python docs/board/board.py columns
```

Cards move between columns (`backlog`, `planned`, `running`, `review`, `merged`, `deployed`, `blocked`); a removed card is archived, never lost.
:::
