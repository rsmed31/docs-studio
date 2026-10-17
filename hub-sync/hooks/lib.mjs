// Shared by the hook scripts: read the hook input, keep per-session state, talk to the hub.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const cfg = {
  url: (process.env.HUB_URL || "").replace(/\/+$/, ""),
  project: process.env.HUB_PROJECT || "",
  token: process.env.HUB_TOKEN || "",
  mode: (process.env.HUB_ENFORCE || "block").toLowerCase(),   // block | warn | off
};
export const configured = () => !!(cfg.url && cfg.project && cfg.token) && cfg.mode !== "off";

export function input() {
  try { return JSON.parse(readFileSync(0, "utf8") || "{}"); } catch { return {}; }
}
const stateFile = (sid) => join(tmpdir(), `hub-sync-${String(sid || "x").replace(/[^\w-]/g, "")}.json`);
export function load(sid) {
  try { return existsSync(stateFile(sid)) ? JSON.parse(readFileSync(stateFile(sid), "utf8")) : fresh(); } catch { return fresh(); }
}
const fresh = () => ({ card: null, edited: [], docs: false, summary: false, blocks: 0 });
export const save = (sid, s) => { try { writeFileSync(stateFile(sid), JSON.stringify(s)); } catch { /* best effort */ } };
export const out = (o) => { process.stdout.write(JSON.stringify(o)); process.exit(0); };

export async function hub(method, path, body) {
  const r = await fetch(`${cfg.url}/api/hub/projects/${cfg.project}${path}`, {
    method, headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.token}`, "X-Hub-Project": cfg.project },
    body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(8000),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `hub answered ${r.status}`);
  return j;
}
// Files that are documentation, not code: editing them never needs a card.
export const isDocFile = (p) => /(^|[\/])(docs?|site[\/]src)[\/]|\.(md|mdx|txt)$/i.test(String(p || ""));

// ---- drift: work that happened outside the hub (no plugin, other machine, a human, hooks off) ---- //
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
export const projectDir = () => process.env.CLAUDE_PROJECT_DIR || process.cwd();
export function git(args, cwd = projectDir()) {
  try { return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 32e6 }).replace(/\s+$/, ""); } catch { return null; }
}
// Fingerprint of the uncommitted state, so changes already reconciled (or made in a tracked session) are not reported again.
export function fingerprint(cwd = projectDir()) {
  const st = git(["status", "--porcelain"], cwd);
  if (st === null) return "";
  return createHash("sha1").update(st + "\u0000" + (git(["diff", "HEAD"], cwd) || "")).digest("hex");
}
const RISKY = /(package(-lock)?\.json|pnpm-lock|yarn\.lock|requirements[^/]*\.txt|pyproject\.toml|Dockerfile|docker-compose|\.github\/|migrations?\/|alembic|\.env|netlify\.toml|vercel\.json|schema|\.sql$|settings\.json)/i;

// sync = {head, branch, at} from the hub. Returns null when not in a git repo.
export function drift(sync, cwd = projectDir()) {
  const head = git(["rev-parse", "HEAD"], cwd);
  if (!head) return null;
  const branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd) || "";
  const d = { head, branch, base: sync?.head || null, commits: [], files: [], dirty: [], note: "", baseline: !sync?.head };
  const porcelain = git(["status", "--porcelain"], cwd) || "";
  d.fp = fingerprint(cwd);
  d.dirty = sync?.dirty && sync.dirty === d.fp ? [] : porcelain.split("\n").filter(Boolean).slice(0, 60).map((l) => l.slice(3));
  if (sync?.head && sync.head !== head) {
    let base = sync.head;
    if (git(["merge-base", "--is-ancestor", sync.head, "HEAD"], cwd) === null) {      // history was rewritten or another branch
      d.note = `The last synced commit ${sync.head.slice(0, 7)} is not an ancestor of HEAD (rebase or other branch); using commits since ${sync.at}.`;
      const oldest = (git(["log", `--since=${sync.at}`, "--format=%H"], cwd) || "").split("\n").filter(Boolean).pop();
      base = oldest ? `${oldest}^` : head;
    }
    const log = git(["log", `${base}..HEAD`, "--format=%h\t%an\t%ad\t%s", "--date=short", "-n", "60"], cwd) || "";
    d.commits = log.split("\n").filter(Boolean).map((l) => { const [sha, who, date, ...s] = l.split("\t"); return { sha, who, date, subject: s.join("\t") }; });
    const ns = {};
    (git(["diff", "--name-status", base, "HEAD"], cwd) || "").split("\n").filter(Boolean).forEach((l) => { const [st, ...p] = l.split("\t"); ns[p[p.length - 1]] = st[0]; });
    (git(["diff", "--numstat", base, "HEAD"], cwd) || "").split("\n").filter(Boolean).slice(0, 200).forEach((l) => {
      const [a, r, ...p] = l.split("\t"), path = p.join("\t"), add = +a || 0, del = +r || 0;
      d.files.push({ path, add, del, status: ns[path] || "M", risky: RISKY.test(path), large: add + del > 300 });
    });
  }
  return d;
}
export const hasDrift = (d) => !!d && !d.baseline && (d.commits.length > 0 || d.dirty.length > 0);

export function formatDrift(d, full = true) {
  const area = (p) => (p.includes("/") ? p.split("/")[0] : "(root)");
  const groups = {};
  d.files.forEach((f) => { (groups[area(f.path)] ||= []).push(f); });
  const out = [`${d.commits.length} commit(s) and ${d.dirty.length} uncommitted file(s) are not in the hub (last synced: ${d.base ? d.base.slice(0, 7) : "never"}, now ${d.head.slice(0, 7)} on ${d.branch}).`];
  if (d.note) out.push(d.note);
  if (!full) return out.join("\n");
  if (d.commits.length) out.push("Commits (newest first):", ...d.commits.slice(0, 25).map((c) => `- ${c.sha} ${c.date} ${c.who}: ${c.subject}`));
  Object.entries(groups).forEach(([g, fs]) => out.push(`Area ${g}: ${fs.length} file(s), +${fs.reduce((n, f) => n + f.add, 0)}/-${fs.reduce((n, f) => n + f.del, 0)}`, ...fs.slice(0, 8).map((f) => `  ${f.status} ${f.path}${f.risky ? "  [RISKY: config/deps/schema]" : ""}${f.large ? "  [LARGE]" : ""}`)));
  if (d.dirty.length) out.push("Uncommitted:", ...d.dirty.slice(0, 20).map((p) => `  ${p}`));
  return out.join("\n");
}
export const DRIFT_PROTOCOL = `How to reconcile (do this before any new work):
1. DRAFT, do not interrogate. Write what changed per area, and the decisions behind it. If you remember this work from this conversation, say so (confidence "known"). If you only know it from the diff or commit messages, mark it "inferred". Read the diffs of RISKY or LARGE files and any deleted files before drafting.
2. ASK the user only what you cannot infer, in ONE batched question (AskUserQuestion, at most 3 questions): the reason behind deletions, dependency/schema/config changes, and design choices that had plausible alternatives. Skip trivial changes, never ask about what a commit message already explains.
3. RECORD with hub_reconcile: a one-line summary, items [{what, why, alternatives, confidence}], and docs: which page you updated (hub_doc_write first) or why none is affected.`;

// ---- Auto pages: rescan the repository in the background (render/hubdoc.py scan --push) ---- //
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
export function scanInBackground() {
  if ((process.env.HUB_AUTOSCAN || "on").toLowerCase() === "off") return;
  try {
    const py = process.env.HUB_PYTHON || (process.platform === "win32" ? "python" : "python3");
    const child = spawn(py, [fileURLToPath(new URL("../render/hubdoc.py", import.meta.url)), "scan", "--push", "--quiet"],
      { detached: true, stdio: "ignore", windowsHide: true, env: process.env, cwd: projectDir() });
    child.on("error", () => {});
    child.unref();
  } catch { /* python missing: the Auto pages just stay as they are */ }
}
