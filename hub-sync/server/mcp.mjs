#!/usr/bin/env node
// Minimal MCP server (stdio, no dependencies) exposing one hub project to Claude.
// Env: HUB_URL, HUB_PROJECT, HUB_TOKEN (the project token from the hub's Settings tab).
import { createInterface } from "node:readline";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { drift, hasDrift, formatDrift, DRIFT_PROTOCOL } from "../hooks/lib.mjs";

const URL_ = (process.env.HUB_URL || "").replace(/\/+$/, "");
const PROJECT = process.env.HUB_PROJECT || "";
const TOKEN = process.env.HUB_TOKEN || "";

const gitAt = () => {                         // the commit (and branch) an entry was written at, for PR reports
  const run = (args) => { const r = spawnSync("git", args, { encoding: "utf8", cwd: process.env.CLAUDE_PROJECT_DIR || process.cwd() }); return r.status === 0 ? r.stdout.trim() : ""; };
  return { sha: run(["rev-parse", "HEAD"]), branch: run(["rev-parse", "--abbrev-ref", "HEAD"]) };
};
async function hub(method, path, body, raw = false) {
  if (!URL_ || !PROJECT || !TOKEN) throw new Error("HUB_URL, HUB_PROJECT and HUB_TOKEN must be set");
  const r = await fetch(raw ? `${URL_}/api/hub${path}` : `${URL_}/api/hub/projects/${PROJECT}${path}`, {
    method, headers: { "Content-Type": "application/json", Authorization: `Bearer ${TOKEN}`, "X-Hub-Project": PROJECT },
    body: body ? JSON.stringify(path === "/activity" && method === "POST" ? { ...gitAt(), ...body } : body) : undefined, signal: AbortSignal.timeout(15000),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `hub answered ${r.status}`);
  return j;
}
const str = (d) => ({ type: "string", description: d });

// Pages are rendered here, where Python and the repository are: docs-studio's Markdown, presets and animations (render/hubdoc.py).
const RENDER = fileURLToPath(new URL("../render/hubdoc.py", import.meta.url));
const python = () => process.env.HUB_PYTHON || (process.platform === "win32" ? "python" : "python3");
function renderPage(page) {
  const r = spawnSync(python(), [RENDER, "render"], { input: JSON.stringify(page), encoding: "utf8", env: process.env, timeout: 60000, maxBuffer: 32e6 });
  if (r.error || r.status !== 0) return { error: (r.error?.message || r.stderr || "render failed").trim().slice(-400) };
  try { return JSON.parse(r.stdout); } catch { return { error: "renderer gave no JSON" }; }
}
const htmlToText = (h) => String(h || "")
  .replace(/<(script|style|svg)[\s\S]*?<\/\1>/gi, "")
  .replace(/<\/(p|h[1-6]|li|tr|div|section|details|summary|pre)>/gi, "\n")
  .replace(/<[^>]+>/g, "")
  .replace(/&nbsp;/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&")
  .replace(/\n\s*\n\s*\n+/g, "\n\n").trim();

const tools = {
  hub_board: {
    description: "List the project's board: columns and cards (id, title, column, owner).",
    schema: { type: "object", properties: {} },
    run: async () => {
      const b = await hub("GET", "/board");
      return b.columns.map((c) => `## ${c.title} (${c.id})\n` + (b.cards.filter((t) => t.column === c.id).sort((x, y) => x.order - y.order).map((t) => `- ${t.id} ${t.title}${t.owner ? " [" + t.owner + "]" : ""}`).join("\n") || "(empty)")).join("\n\n");
    },
  },
  hub_start_task: {
    description: "Claim a board card before changing code. Pass `card` to take an existing card, or `title` to create one. The card moves to 'running'. Required by the edit guard.",
    schema: { type: "object", properties: { card: str("existing card id, e.g. t_ab12cd"), title: str("title for a new card"), description: str("what will be done") } },
    run: async (a) => {
      let id = a.card;
      if (!id) { if (!a.title) throw new Error("give a card id or a title"); id = (await hub("POST", "/board", { title: a.title, description: a.description || "", column: "running", owner: "agent" })).card.id; }
      else await hub("PATCH", `/board/${id}`, { column: "running", owner: "agent" });
      await hub("POST", "/activity", { kind: "task", summary: `Started: ${a.title || id}`, card: id });
      return `Claimed ${id}. You can now edit code.`;
    },
  },
  hub_update_task: {
    description: "Update a card: move it to another column, change its title or description.",
    schema: { type: "object", properties: { card: str("card id"), column: str("column id from hub_board (e.g. backlog, planned, running, review, done or the project's own)"), title: str("new title"), description: str("new description") }, required: ["card"] },
    run: async (a) => { const { card, ...patch } = a; await hub("PATCH", `/board/${card}`, patch); return `Updated ${card}.`; },
  },
  hub_finish_task: {
    description: "Finish the claimed card: moves it to review (or done) and writes your summary into the traceability log. Call when the work is complete.",
    schema: { type: "object", properties: { card: str("card id"), summary: str("what changed and why, 1-3 sentences"), column: { type: "string", enum: ["review", "done", "blocked"] } }, required: ["card", "summary"] },
    run: async (a) => {
      await hub("PATCH", `/board/${a.card}`, { column: a.column || "review" });
      await hub("POST", "/activity", { kind: "summary", summary: a.summary, card: a.card });
      return `Card ${a.card} moved to ${a.column || "review"}; summary logged.`;
    },
  },
  hub_drift: {
    description: "Show work that happened outside the hub (commits and uncommitted changes since the hub's last synced commit) and how to reconcile it. Call when the session starts with a DRIFT notice, or any time you suspect untracked work.",
    schema: { type: "object", properties: {} },
    run: async () => {
      const d = drift((await hub("GET", "/sync")).sync);
      if (!d) return "Not a git repository: drift cannot be computed.";
      if (!hasDrift(d)) return d.baseline ? "No baseline yet; it is set when a session starts." : "No drift: the hub is in sync with HEAD.";
      return formatDrift(d) + "\n\n" + DRIFT_PROTOCOL;
    },
  },
  hub_reconcile: {
    description: "Record reconciled drift: what changed and the decisions behind it. Writes a drift entry and one decision entry per item to the traceability log, adds a done card, and moves the hub's sync point to HEAD. Use after drafting (and asking the user about risky or ambiguous items).",
    schema: { type: "object", properties: {
      summary: str("one-line summary of the untracked work"),
      items: { type: "array", description: "what changed and why", items: { type: "object", properties: { what: str("the change"), why: str("the reason / decision"), alternatives: str("alternatives considered or rejected, if known"), confidence: { type: "string", enum: ["known", "inferred", "confirmed-by-user"] } }, required: ["what"] } },
      docs: str("page updated (after hub_doc_write), or why no doc is affected") }, required: ["summary", "items", "docs"] },
    run: async (a) => {
      const d = drift((await hub("GET", "/sync")).sync);
      if (!d) throw new Error("Not a git repository");
      const items = Array.isArray(a.items) ? a.items : [];
      if (!items.length) throw new Error("items must list at least one change");
      const detail = items.map((i) => `- ${i.what}${i.why ? "\n  why: " + i.why : ""}${i.alternatives ? "\n  alternatives: " + i.alternatives : ""} [${i.confidence || "inferred"}]`).join("\n");
      const range = d.base ? `${d.base.slice(0, 7)}..${d.head.slice(0, 7)}` : d.head.slice(0, 7);
      await hub("POST", "/activity", { kind: "drift", summary: `Reconciled untracked work (${range}): ${a.summary}`, detail: `${detail}\ndocs: ${a.docs}\ncommits: ${d.commits.map((c) => c.sha).join(", ") || "none (uncommitted)"}` });
      for (const i of items.filter((x) => x.why).slice(0, 15)) await hub("POST", "/activity", { kind: "decision", summary: String(i.what).slice(0, 480), detail: `why: ${i.why}${i.alternatives ? "\nalternatives: " + i.alternatives : ""}\nconfidence: ${i.confidence || "inferred"}` });
      await hub("POST", "/board", { title: `Reconciled: ${a.summary}`.slice(0, 200), description: detail, column: "done", owner: "agent" });
      await hub("PUT", "/sync", { head: d.head, branch: d.branch, dirty: d.fp });
      return `Recorded ${items.length} item(s) and moved the sync point to ${d.head.slice(0, 7)}. Edits are unblocked.`;
    },
  },
  hub_docs_list: {
    description: "List the project's documentation pages.",
    schema: { type: "object", properties: {} },
    run: async () => (await hub("GET", "/docs")).pages.map((p) => `- ${p.id}: ${p.title} [group ${p.group || "pages"}, ${p.format || "md"}] (updated ${p.updated})`).join("\n") || "(no pages)",
  },
  hub_doc_read: {
    description: "Read one documentation page. Markdown pages come back as written; pages imported as HTML come back as their Markdown source when known, else as plain text.",
    schema: { type: "object", properties: { id: str("page id") }, required: ["id"] },
    run: async (a) => {
      const d = await hub("GET", `/docs/${a.id}`);
      const text = d.format === "html" ? (d.md || htmlToText(d.body)) : d.body;
      const note = d.format === "html" ? "; writing it back with hub_doc_write replaces the rendered layout with Markdown" : "";
      return `# ${d.title}\n(group: ${d.groupTitle || d.group || "Pages"}, format: ${d.format || "md"}${note})\n\n${text}`;
    },
  },
  hub_doc_write: {
    description: "Create or replace a documentation page. Markdown plus diagram directives that render (and animate) like the rest of the docs: :::flow, :::sequence, :::zones, :::layers, :::swimlane, :::state, :::er, :::tree, :::mindmap, :::chart, :::gantt, :::stats, :::cards, :::steps, :::timeline, :::details Title ... and anim=packets|trace|flow|reveal|draw|pulse. Call hub_diagram_help for the exact syntax before drawing. Use after behaviour or architecture changes.",
    schema: { type: "object", properties: { id: str("page id: lowercase, digits, dashes"), title: str("page title"), body: str("Markdown with optional ::: diagram directives"), lede: str("one-sentence summary shown under the title"),
      group: str("sidebar group id, e.g. how-it-works (see hub_docs_list)"), groupTitle: str("sidebar group title when creating a new group"),
      status: { type: "string", enum: ["done", "running", "planned", ""], description: "badge on the page: built, in progress, planned" } }, required: ["id", "title", "body"] },
    run: async (a) => {
      const meta = { title: a.title, lede: a.lede, group: a.group, groupTitle: a.groupTitle };
      let groupTitle = a.groupTitle;
      if (!groupTitle && a.group) groupTitle = ((await hub("GET", "/nav")).groups || []).find((g) => g.id === a.group)?.title;
      const r = renderPage({ id: a.id, title: a.title, groupTitle: groupTitle || "Pages", lede: a.lede || "", md: a.body, status: a.status || "" });
      if (r.html) {
        await hub("PUT", `/docs/${a.id}`, { ...meta, format: "html", body: r.html, md: a.body });
        return `Page ${a.id} saved (rendered with diagrams).${r.redacted?.length ? " Redacted: " + r.redacted.join(", ") + "." : ""}`;
      }
      await hub("PUT", `/docs/${a.id}`, { ...meta, format: "md", body: a.body });
      return `Page ${a.id} saved as plain Markdown (diagram renderer unavailable: ${r.error}). Directives will show as text; install Python 3.9+ or set HUB_PYTHON.`;
    },
  },
  hub_diagram_help: {
    description: "The diagram and animation vocabulary for hub_doc_write (flow, sequence, zones, layers, charts, cards ... with examples). Read it before drawing a diagram.",
    schema: { type: "object", properties: {} },
    run: async () => readFileSync(new URL("../../skills/docs-studio/references/presets.md", import.meta.url), "utf8") + "\n\n" + readFileSync(new URL("../../skills/docs-studio/references/authoring.md", import.meta.url), "utf8"),
  },
  hub_scan: {
    description: "Rescan the repository now and update the Auto pages (overview, folder structure, module dependency graph, git activity, dependencies, TODOs). Runs by itself after commits; use it to refresh on demand.",
    schema: { type: "object", properties: { force: { type: "boolean", description: "push every page even if unchanged" } } },
    run: async (a) => {
      const r = spawnSync(python(), [RENDER, "scan", "--push", ...(a.force ? ["--force"] : [])], { encoding: "utf8", env: process.env, timeout: 180000 });
      if (r.error || r.status !== 0) throw new Error((r.stderr || r.error?.message || "scan failed").slice(-800));
      return r.stdout.trim().slice(-1500) || "Scanned.";
    },
  },
  hub_import_site: {
    description: "Import this repository's built docs-studio site into the hub project: every page as rendered, the sidebar groups and the status board. Use when the user asks to bring existing docs into Docs Studio.",
    schema: { type: "object", properties: { site: str("built site, default docs/site/index.html"), board: str("board file, default docs/board/board.yaml"), dryRun: { type: "boolean" } } },
    run: async (a) => {
      const args = [fileURLToPath(new URL("../import_site.py", import.meta.url)), ...(a.site ? ["--site", a.site] : []), ...(a.board ? ["--board", a.board] : []), ...(a.dryRun ? ["--dry-run"] : [])];
      const r = spawnSync(python(), args, { encoding: "utf8", env: process.env, cwd: process.env.CLAUDE_PROJECT_DIR || process.cwd(), timeout: 600000, maxBuffer: 32e6 });
      const out = ((r.stdout || "") + (r.stderr || "")).trim();
      if (r.error || (r.status !== 0 && !a.dryRun)) throw new Error(out.slice(-1200) || r.error?.message || "import failed");
      return out.slice(-1500);
    },
  },
  hub_lists: {
    description: "The project's to-do list and brainstorming list (shared with the owner on the Docs Studio home screen). Open items first.",
    schema: { type: "object", properties: {} },
    run: async () => {
      const r = await hub("GET", "/lists", null, true);
      const fmt = (it) => `- ${it.done ? "[x]" : "[ ]"} ${it.id} ${it.text}${it.notes ? " — " + it.notes.replace(/\s+/g, " ").slice(0, 160) : ""}${it.card ? " (on the board: " + it.card + ")" : ""}`;
      const part = (k, title) => `## ${title}\n` + (r[k].filter((i) => !i.done).concat(r[k].filter((i) => i.done)).map(fmt).join("\n") || "(empty)");
      return part("todo", "To do") + "\n\n" + part("ideas", "Brainstorming");
    },
  },
  hub_list_add: {
    description: "Add to the project's to-do list (a concrete thing to do later, outside the current card) or brainstorming list (an idea, option or question worth keeping). Use when the user mentions one in passing or you spot one; don't use it for the task you are doing now (that is a board card).",
    schema: { type: "object", properties: { list: { type: "string", enum: ["todo", "ideas"] }, text: str("one line"), notes: str("optional context: why, links, trade-offs") }, required: ["list", "text"] },
    run: async (a) => { const r = await hub("POST", `/lists/${a.list}/${PROJECT}`, { text: a.text, notes: a.notes || "" }, true); return `Added ${r.item.id} to ${a.list === "todo" ? "the to-do list" : "brainstorming"}.`; },
  },
  hub_list_done: {
    description: "Mark a to-do (or idea) done, by its id from hub_lists.",
    schema: { type: "object", properties: { list: { type: "string", enum: ["todo", "ideas"] }, id: str("item id, e.g. i_1a2b3c4d") }, required: ["list", "id"] },
    run: async (a) => { await hub("PATCH", `/lists/${a.list}/${PROJECT}/${a.id}`, { done: true }, true); return `Marked ${a.id} done.`; },
  },
  hub_log: {
    description: "Append an entry to the traceability log. kind: summary | note | docs (use `docs` to record why no doc needed changing) | commit.",
    schema: { type: "object", properties: { summary: str("one or two sentences"), kind: { type: "string", enum: ["summary", "note", "docs", "commit"] }, card: str("related card id") }, required: ["summary"] },
    run: async (a) => { await hub("POST", "/activity", { kind: a.kind || "note", summary: a.summary, card: a.card }); return "Logged."; },
  },
};

const send = (o) => process.stdout.write(JSON.stringify({ jsonrpc: "2.0", ...o }) + "\n");
createInterface({ input: process.stdin }).on("line", async (line) => {
  let m; try { m = JSON.parse(line); } catch { return; }
  if (m.id === undefined) return;                                   // notifications need no reply
  try {
    if (m.method === "initialize") return send({ id: m.id, result: { protocolVersion: m.params?.protocolVersion || "2024-11-05", capabilities: { tools: {} }, serverInfo: { name: "hub", version: "0.1.0" } } });
    if (m.method === "ping") return send({ id: m.id, result: {} });
    if (m.method === "tools/list") return send({ id: m.id, result: { tools: Object.entries(tools).map(([name, t]) => ({ name, description: t.description, inputSchema: t.schema })) } });
    if (m.method === "tools/call") {
      const t = tools[m.params?.name];
      if (!t) return send({ id: m.id, error: { code: -32602, message: "unknown tool" } });
      try { return send({ id: m.id, result: { content: [{ type: "text", text: String(await t.run(m.params.arguments || {})) }] } }); }
      catch (e) { return send({ id: m.id, result: { isError: true, content: [{ type: "text", text: e.message }] } }); }
    }
    send({ id: m.id, error: { code: -32601, message: "method not found" } });
  } catch (e) { send({ id: m.id, error: { code: -32603, message: e.message } }); }
});
