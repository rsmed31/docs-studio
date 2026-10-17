// PreToolUse on Edit/Write: code changes need a claimed board card.
import { configured, cfg, input, load, out, isDocFile } from "./lib.mjs";
const inp = input();
if (!configured()) out({});
const target = inp.tool_input?.file_path || inp.tool_input?.notebook_path || "";
if (isDocFile(target)) out({});
const s = load(inp.session_id);
if (s.drift) {
  const why = "Work happened outside the hub since the last sync. Call hub_drift, reconcile it with hub_reconcile (ask the user about risky or ambiguous decisions), then retry.";
  if (cfg.mode === "warn") out({ hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "allow", additionalContext: why } });
  out({ hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: why } });
}
if (s.card) out({});
const why = "No board card is claimed for this work. Call hub_start_task (title for a new card, or card id for an existing one) first, then retry the edit.";
if (cfg.mode === "warn") out({ hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "allow", additionalContext: why } });
out({ hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: why } });
