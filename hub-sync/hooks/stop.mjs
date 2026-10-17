// Stop: if code changed, the session must leave docs updated (or a stated reason) and a summary in the traceability log.
import { configured, cfg, input, load, save, out, hub, git, fingerprint } from "./lib.mjs";
const inp = input();
if (!configured() || cfg.mode === "warn") out({});
const s = load(inp.session_id);
const needs = [];
if (s.edited.length && !s.docs) needs.push("update the relevant doc page (hub_doc_write), or log why no doc is affected (hub_log with kind \"docs\")");
if (s.edited.length && !s.summary) needs.push("finish the card with hub_finish_task and a short summary of what changed and why");
if (!needs.length && !s.drift) {
  const head = git(["rev-parse", "HEAD"]);
  if (head) await hub("PUT", "/sync", { head, branch: git(["rev-parse", "--abbrev-ref", "HEAD"]) || "", dirty: fingerprint() }).catch(() => {});
}
if (!needs.length || inp.stop_hook_active || s.blocks >= 2) out({});
s.blocks++; save(inp.session_id, s);
out({ decision: "block", reason: `Before stopping, ${needs.join(", and ")}. Files changed: ${s.edited.slice(0, 8).join(", ")}.` });
