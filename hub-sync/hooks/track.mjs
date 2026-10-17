// PostToolUse: remember what happened this session (claimed card, edited files, docs written, summary logged).
import { configured, input, load, save, out, isDocFile, scanInBackground } from "./lib.mjs";
const inp = input();
if (!configured()) out({});
const s = load(inp.session_id), name = String(inp.tool_name || "");
if (/^(Edit|Write|NotebookEdit)$/.test(name)) {
  const p = inp.tool_input?.file_path || inp.tool_input?.notebook_path || "";
  if (isDocFile(p)) s.docs = true;
  else if (p && !s.edited.includes(p)) s.edited.push(p);
} else if (/hub_start_task$/.test(name)) {
  const m = JSON.stringify(inp.tool_response || "").match(/t_[a-z0-9]{6,12}/);
  if (m) s.card = m[0];
} else if (/hub_finish_task$/.test(name)) {
  s.summary = true; s.card = null; s.edited = []; s.docs = false;
} else if (/hub_doc_write$/.test(name)) s.docs = true;
else if (/hub_reconcile$/.test(name)) { if (!/isError/.test(JSON.stringify(inp.tool_response || ""))) { s.drift = null; s.docs = true; } }
else if (/hub_log$/.test(name)) { if (inp.tool_input?.kind === "summary") s.summary = true; if (inp.tool_input?.kind === "docs") s.docs = true; }
if (name === "Bash" && /\bgit\b[^|;&]*\bcommit\b/.test(String(inp.tool_input?.command || ""))) scanInBackground();   // Auto pages follow every commit
save(inp.session_id, s);
out({});
