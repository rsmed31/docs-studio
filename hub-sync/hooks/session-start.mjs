import { configured, cfg, input, hub, out, load, save, drift, hasDrift, formatDrift, scanInBackground } from "./lib.mjs";
const inp = input();
if (!configured()) out({});
try {
  const [b, sy] = await Promise.all([hub("GET", "/board"), hub("GET", "/sync")]);
  const col = (id) => b.cards.filter((c) => c.column === id);
  const line = (c) => `- ${c.id} ${c.title}`;
  const d = drift(sy.sync);
  const s = load(inp.session_id);
  const parts = [
    `Hub project "${cfg.project}" is connected (enforcement: ${cfg.mode}).`,
    "Rules: before editing code, claim a board card with hub_start_task (new card or an existing id). When the work is done call hub_finish_task with a short summary. When behaviour changes, update the matching doc with hub_doc_write (diagrams render and animate: see hub_diagram_help). Auto pages (structure, module graph, activity, dependencies, TODOs) rescan themselves after commits.",
    col("running").length ? "In progress:\n" + col("running").map(line).join("\n") : "Nothing in progress.",
    col("planned").length ? "Planned:\n" + col("planned").slice(0, 8).map(line).join("\n") : "",
  ];
  if (d && d.baseline) {                                   // first connection: adopt the current commit as the baseline
    await hub("PUT", "/sync", { head: d.head, branch: d.branch, dirty: d.fp }).catch(() => {});
  } else if (hasDrift(d)) {
    s.drift = { head: d.head, commits: d.commits.length, dirty: d.dirty.length };
    save(inp.session_id, s);
    parts.push("", "DRIFT DETECTED: work happened outside the hub.", formatDrift(d, false),
      "Before any other work call hub_drift, then reconcile it with hub_reconcile (draft what changed and why from the diffs or your memory; ask the user only about risky or ambiguous decisions). Code edits are blocked until this is done.");
  }
  scanInBackground();                                    // Auto pages catch up with commits made outside Claude
  out({ hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: parts.filter((x) => x !== "").join("\n") } });
} catch (e) {
  out({ hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: `Hub project "${cfg.project}" is configured but unreachable (${e.message}). Board enforcement will not apply until it is back; changes made now will show up as drift next time.` } });
}
