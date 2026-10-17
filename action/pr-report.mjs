// Docs Studio PR report (GitHub Action, node24, no dependencies).
// One sticky comment per pull request: what changed (areas, risky files, deletions), whether the docs kept up,
// and, when a Docs Studio hub is connected, what Claude did and decided while making these commits, and why.
import { execFileSync, spawnSync } from "node:child_process";
import { appendFileSync, existsSync, readFileSync } from "node:fs";

const input = (name, def = "") => (process.env[`INPUT_${name.replace(/ /g, "_").toUpperCase()}`] ?? def).trim() || def;
const HUB_URL = input("hub-url").replace(/\/+$/, ""), HUB_PROJECT = input("hub-project"), HUB_TOKEN = input("hub-token");
const GH_TOKEN = input("github-token"), CHECK_DOCS = input("check-docs", "auto"), FAIL_STALE = input("fail-on-stale-docs", "false") === "true";
const COMMENT = input("comment", "true") === "true";
const MARK = "<!-- docs-studio-pr-report -->";
const RISKY = /(package(-lock)?\.json|pnpm-lock|yarn\.lock|requirements[^/]*\.txt|pyproject\.toml|go\.(mod|sum)|Cargo\.(toml|lock)|Gemfile|Dockerfile|docker-compose|\.github\/workflows\/|migrations?\/|alembic|\.env|netlify\.toml|vercel\.json|schema|\.sql$|settings\.json|terraform|\.tf$)/i;
const DOCS = /(^|\/)(docs?|documentation)\/|(^|\/)(README|CHANGELOG|CONTRIBUTING|ARCHITECTURE)[^/]*$|\.mdx?$/i;

const git = (...args) => { try { return execFileSync("git", args, { encoding: "utf8", maxBuffer: 64e6 }).trim(); } catch { return ""; } };
const esc = (s) => String(s ?? "").replace(/\|/g, "\\|").replace(/</g, "&lt;");
const warn = (m) => console.log(`::warning::${m}`);

const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
const pr = event.pull_request;
if (!pr) { console.log("Not a pull_request event: nothing to report."); process.exit(0); }
const base = pr.base.sha, head = pr.head.sha;
const have = (sha) => spawnSync("git", ["cat-file", "-e", `${sha}^{commit}`]).status === 0;
if (!have(base) || !have(head)) git("fetch", "--no-tags", "origin", base, head);
if (!have(base)) warn("Base commit not available: use actions/checkout with fetch-depth: 0.");

// ---- what changed ---------------------------------------------------------------------------- //
const commits = git("log", "--format=%H%x09%h%x09%an%x09%aI%x09%s", `${base}..${head}`).split("\n").filter(Boolean)
  .map((l) => { const [sha, short, who, at, ...s] = l.split("\t"); return { sha, short, who, at, subject: s.join("\t") }; });
const status = {};
git("diff", "--name-status", `${base}...${head}`).split("\n").filter(Boolean).forEach((l) => { const [st, ...p] = l.split("\t"); status[p[p.length - 1]] = st[0]; });
const files = git("diff", "--numstat", `${base}...${head}`).split("\n").filter(Boolean).map((l) => {
  const [a, d, ...p] = l.split("\t"); const path = p.join("\t").replace(/^.*=> /, "").replace(/[{}]/g, "");
  return { path, add: +a || 0, del: +d || 0, st: status[path] || "M" };
});
const area = (p) => (p.includes("/") ? p.split("/")[0] + "/" : "(root)");
const areas = {};
for (const f of files) { const a = (areas[area(f.path)] ||= { files: 0, add: 0, del: 0 }); a.files++; a.add += f.add; a.del += f.del; }
const code = files.filter((f) => !DOCS.test(f.path)), docs = files.filter((f) => DOCS.test(f.path));
const risky = files.filter((f) => RISKY.test(f.path)), deleted = files.filter((f) => f.st === "D"), large = files.filter((f) => f.add + f.del > 400);

// ---- do the docs keep up? --------------------------------------------------------------------- //
let docsCheck = null;                                    // {state: fresh|stale|error, detail}
const builder = ["docs/site/build.py", "site/build.py"].find((p) => existsSync(p));
if (builder && CHECK_DOCS !== "false") {
  spawnSync("python3", ["-m", "pip", "install", "--quiet", "pyyaml"], { stdio: "ignore" });
  const r = spawnSync("python3", [builder, "--check"], { encoding: "utf8" });
  docsCheck = r.status === 0 ? { state: "fresh", detail: "the generated docs site matches its sources" }
    : r.status === 1 ? { state: "stale", detail: (r.stderr || r.stdout || "").trim().split("\n").slice(-2).join(" ") || "rebuild needed" }
    : { state: "error", detail: (r.stderr || "").trim().split("\n").pop() || "check failed" };
}

// ---- what Claude did and why (Docs Studio hub) ------------------------------------------------- //
let hub = null;
if (HUB_URL && HUB_PROJECT && HUB_TOKEN) {
  try {
    const r = await fetch(`${HUB_URL}/api/hub/projects/${HUB_PROJECT}/activity?limit=300`, {
      headers: { Authorization: `Bearer ${HUB_TOKEN}`, "X-Hub-Project": HUB_PROJECT }, signal: AbortSignal.timeout(20000) });
    if (!r.ok) throw new Error(`hub answered ${r.status}`);
    const shas = new Set(commits.flatMap((c) => [c.sha, c.short]));
    const since = commits.length ? new Date(Math.min(...commits.map((c) => Date.parse(c.at))) - 6 * 3600e3).toISOString() : pr.created_at;
    const branch = pr.head.ref;
    const all = (await r.json()).activity || [];
    // An entry belongs to this PR when it was written at one of its commits, or on its branch since its first commit.
    const mine = all.filter((a) => (a.sha && (shas.has(a.sha) || shas.has(a.sha.slice(0, 7)))) || (!a.sha && a.at >= since && (!a.branch || a.branch === branch)) || (a.branch === branch && a.at >= since));
    hub = { all: mine, url: `${HUB_URL}/p/${HUB_PROJECT}` };
  } catch (e) { warn(`Docs Studio hub not reachable: ${e.message}`); hub = { error: e.message }; }
}

// ---- the comment ------------------------------------------------------------------------------- //
const out = [MARK, "## Docs Studio report", ""];
const verdict = [];
verdict.push(`**${commits.length} commit${commits.length === 1 ? "" : "s"}**, ${files.length} file${files.length === 1 ? "" : "s"} (+${files.reduce((n, f) => n + f.add, 0)} −${files.reduce((n, f) => n + f.del, 0)})`);
if (code.length && !docs.length) verdict.push("⚠️ code changed, **no docs changed**");
else if (docs.length) verdict.push(`📝 ${docs.length} doc file${docs.length === 1 ? "" : "s"} updated`);
if (docsCheck) verdict.push(docsCheck.state === "fresh" ? "✅ docs site up to date" : docsCheck.state === "stale" ? "❌ docs site is stale" : "⚠️ docs check failed");
if (risky.length) verdict.push(`🔶 ${risky.length} risky file${risky.length === 1 ? "" : "s"}`);
out.push(verdict.join(" · "), "");

if (hub && hub.all) {
  const by = (k) => hub.all.filter((a) => a.kind === k);
  const summaries = by("summary"), decisions = by("decision"), drift = by("drift"), docsLog = by("docs"), tasks = by("task");
  out.push("### What Claude did and why", "");
  if (!hub.all.length) out.push(`_No Claude activity recorded in [the hub](${hub.url}) for these commits. Work done without the plugin shows up as drift at the next session._`, "");
  for (const s of summaries) out.push(`- ${esc(s.summary)}${s.card ? ` \`${s.card}\`` : ""}`);
  if (decisions.length) {
    out.push("", "**Decisions**", "");
    for (const d of decisions) {
      const why = (d.detail || "").split("\n").map((l) => l.trim()).filter(Boolean);
      out.push(`- **${esc(d.summary)}**${why.length ? "  \n  " + why.map(esc).join("  \n  ") : ""}`);
    }
  }
  if (drift.length) { out.push("", "**Reconciled work done outside the hub**", ""); for (const d of drift) out.push(`- ${esc(d.summary)}`); }
  if (docsLog.length) { out.push("", "**Pages updated in the hub**", ""); for (const d of docsLog.slice(0, 12)) out.push(`- ${esc(d.summary)}`); }
  const moved = tasks.filter((t) => /moved|created|archived/i.test(t.summary)).slice(0, 12);
  if (moved.length) { out.push("", "<details><summary>Board moves</summary>", ""); for (const t of moved) out.push(`- ${esc(t.summary)}`); out.push("", "</details>"); }
  out.push("", `[Open the project in Docs Studio](${hub.url})`, "");
} else if (hub && hub.error) out.push(`_Docs Studio hub not reachable (${esc(hub.error)}): only the repository analysis is shown._`, "");

out.push("### What changed", "", "| Area | Files | + | − |", "|---|---:|---:|---:|");
for (const [a, v] of Object.entries(areas).sort((x, y) => (y[1].add + y[1].del) - (x[1].add + x[1].del)).slice(0, 15)) out.push(`| \`${esc(a)}\` | ${v.files} | ${v.add} | ${v.del} |`);
out.push("");
if (risky.length || deleted.length || large.length) {
  out.push("**Look closer**", "");
  for (const f of risky.slice(0, 15)) out.push(`- 🔶 \`${esc(f.path)}\`: dependencies, config, schema or CI`);
  for (const f of deleted.slice(0, 15)) out.push(`- 🗑️ \`${esc(f.path)}\` deleted`);
  for (const f of large.slice(0, 10)) out.push(`- 📏 \`${esc(f.path)}\`: +${f.add} −${f.del}`);
  out.push("");
}
if (docsCheck) out.push(`**Docs site:** ${docsCheck.state === "fresh" ? "✅" : docsCheck.state === "stale" ? "❌" : "⚠️"} ${esc(docsCheck.detail)}${docsCheck.state === "stale" ? `. Run \`python ${builder}\` and commit the result.` : ""}`, "");
out.push("<details><summary>Commits</summary>", "", ...commits.slice(0, 50).map((c) => `- \`${c.short}\` ${esc(c.subject)} (${esc(c.who)})`), "", "</details>", "",
  "<sub>Made by <a href=\"https://github.com/rsmed31/docs-studio\">Docs Studio</a>: visibility for work done with Claude Code.</sub>");
const body = out.join("\n");

if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, body.replace(MARK, "") + "\n");
if (COMMENT && GH_TOKEN) {
  const api = (method, path, data) => fetch(`${process.env.GITHUB_API_URL || "https://api.github.com"}${path}`, {
    method, headers: { Authorization: `Bearer ${GH_TOKEN}`, Accept: "application/vnd.github+json", "Content-Type": "application/json" }, body: data ? JSON.stringify(data) : undefined });
  const repo = process.env.GITHUB_REPOSITORY, n = pr.number;
  const list = await (await api("GET", `/repos/${repo}/issues/${n}/comments?per_page=100`)).json();
  const mine = Array.isArray(list) ? list.find((c) => (c.body || "").includes(MARK)) : null;
  const res = mine ? await api("PATCH", `/repos/${repo}/issues/comments/${mine.id}`, { body }) : await api("POST", `/repos/${repo}/issues/${n}/comments`, { body });
  if (!res.ok) warn(`Could not post the comment (${res.status}). Give the workflow "pull-requests: write" permission.`);
  else console.log(mine ? "Updated the report comment." : "Posted the report comment.");
}
if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, `docs-state=${docsCheck ? docsCheck.state : "none"}\nclaude-entries=${hub && hub.all ? hub.all.length : 0}\n`);
if (FAIL_STALE && docsCheck && docsCheck.state === "stale") { console.log("::error::The docs site is stale: rebuild it and commit the result."); process.exit(1); }
