# Docs Studio: the vision

> **See what your AI coding agent did, why it did it, and whether your docs still tell the truth.**

## The problem: comprehension debt

Coding agents now write more code than their owners can read. Claude Code ships a feature in an afternoon, across forty files, on three parallel branches. What you get back is a diff. A diff shows **what** changed. It does not show:

- **why** it changed: which request, which task, which trade-off;
- **what was decided** along the way, and what was rejected;
- **how the system's shape moved**: a new module, a new dependency, a reversed arrow in the architecture;
- **whether the docs are still true**: they rot faster than ever, because nobody writes them by hand any more;
- **what happened while nobody watched**: a session without the plugin, a teammate's agent, a hotfix at 2 a.m.

Technical debt is code you will have to fix. **Comprehension debt** is code nobody on the team understands any more. Agents make the second kind grow faster than any team can pay it down. Docs Studio is built to pay it down automatically.

## The idea: a comprehension layer for agent-built software

Docs Studio sits next to your coding agent and keeps three loops closed, without asking anyone to do paperwork.

| Loop | Question it answers | How it closes itself |
|---|---|---|
| **Intent** | Why does this change exist? | Hooks refuse code edits until the agent claims a board card; the card moves as work moves. |
| **Decisions** | Why is it built this way? | The agent logs decisions with reasons, alternatives and confidence (*known*, *inferred*, *confirmed by you*). |
| **Knowledge** | What does the system look like now? | Pages scanned from the repo cannot drift; written pages are re-rendered by the agent, with diagrams that animate the flow they describe. |

And one loop that catches everything the others missed:

**Drift.** The hub remembers the last commit it understood. Anything after it, whether done without the plugin, by a human, or on another machine, is flagged at the next session. The agent reconstructs what changed and why from the diffs and its memory, marks each claim *known* or *inferred*, and asks you **one** batched question about only what it cannot infer. History becomes complete again.

## Principles

1. **Zero ceremony.** If it needs discipline, a hook does it. Nobody fills in a form.
2. **Honest by construction.** Scanned facts come from the code. Inferred claims say they are inferred. Unbuilt things say *planned*.
3. **Human attention is the scarcest resource.** Draft first, ask last, ask once, ask only what the repo cannot answer.
4. **Local-first, free to run.** The docs site is one HTML file with no server. The hub runs on a free Netlify site. No vendor lock-in: everything exports.
5. **Safe to leave on.** Hooks never fail a commit or a session. Credentials are redacted before anything leaves the machine. Access is by invitation only.

## Three layers, adopt one at a time

| Layer | For | What you get |
|---|---|---|
| **Docs** (local skill) | anyone, one repo | A living docs site: 20+ diagram presets with animations, repo-scanned pages (structure, module graph, git activity, dependencies, TODOs), status board, whiteboard. Rebuilt on every commit. |
| **Hub** (hosted, optional) | owners and small teams | Every project in one place: board with enforced task cards, traceability log, decision log, drift reconciliation, to-do and brainstorming lists, whiteboards, invitation-only access. |
| **PR report** (GitHub Action) | reviewers and teams | One comment per pull request: what Claude did and why, the decisions, risky files, and whether the docs kept up. Optional check that fails on stale docs. |

## Where it goes next

**Now (shipped):** docs skill, hub, enforced cards, decision log, drift reconciliation, scanned pages, animated diagrams, lists, Claude Code plugin and marketplace, PR report action, one-click Netlify deploy.

**Next:**
- **Session flight recorder.** Each Claude session as one replayable entry: the request, the card, files touched, commands run, commits, decisions, docs updated, cost. The answer to *"what did Claude do while I was away?"*
- **`hub_why <path>`.** Before changing a file, the agent asks the decision log why it is the way it is. Institutional memory for agents, so the next session doesn't undo a deliberate choice.
- **Doc coverage.** Pages declare `covers: src/payments/**`; when those paths change, the page is flagged stale and the PR report says which page lags which code.
- **Architecture diff.** The module graph before and after a PR, drawn side by side: new edges in green, removed in red.
- **Cost per card.** Claude Code's OpenTelemetry usage, attributed to board cards and sessions.

**Then:**
- **Multi-agent radar.** Live view of parallel sessions and worktrees: who holds which card, which files overlap, where they will conflict.
- **Owner inbox and digest.** Decisions that need you, collected asynchronously; a weekly email or Slack digest of what the agents did, what it cost, what waits on you.
- **Editors and chat.** A VS Code panel for the board and decisions; Slack and Teams notifications.
- **Other agents.** The same hooks and MCP for Codex, Cursor and any agent that speaks MCP.

## What success looks like

- Time for a reviewer to understand an agent-made PR: minutes, not an hour.
- Share of changes with a recorded intent: close to 100 %, without anyone being asked.
- Docs pages that lag the code: listed, never silent.
- Work done outside the system: reconciled within one session.

## Who it is for

- **Solo builders** shipping with Claude Code who come back after a week and need to know what happened.
- **Leads** who review agent-made PRs and need the *why* next to the *what*.
- **Small teams** running several agents in parallel who need one shared picture of the work.
