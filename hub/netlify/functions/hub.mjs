// Docs Studio API (Netlify Function + Netlify Blobs). Everything lives under /api/hub/*.
//
// Auth: a signed session cookie (people) or "Authorization: Bearer hub_<token>" (the Claude plugin, one project).
// Env: HUB_SECRET (cookie signing, required), HUB_SETUP_CODE (lets the first owner register, required once).
import { getStore } from "@netlify/blobs";
import ACCESS from "../access.mjs";
import { createHmac, randomBytes, scryptSync, timingSafeEqual, createHash, createCipheriv, createDecipheriv } from "node:crypto";

const SLUG = /^[a-z0-9][a-z0-9-]{1,40}$/;
const CARD_ID = /^t_[a-z0-9]{6,12}$/;
const WB_ID = /^wb_[a-z0-9]{4,40}$/;
const EMAIL = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$/;
const MAX_JSON = 5 * 1024 * 1024;
const COOKIE = "hub_session";
const SESSION_DAYS = 14;
const COLUMNS = [
  { id: "backlog", title: "Backlog", status: "planned" }, { id: "planned", title: "Planned", status: "planned" }, { id: "running", title: "In progress", status: "running" },
  { id: "review", title: "Review", status: "running" }, { id: "done", title: "Done", status: "done" }, { id: "blocked", title: "Blocked", status: "blocked" },
];

class HttpError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
const bad = (msg) => new HttpError(400, msg);

const store = () => getStore({ name: "hub", consistency: "strong" });   // read-your-writes: tokens, boards and docs must not look stale
const get = (k) => store().get(k, { type: "json" });
const put = (k, v) => store().setJSON(k, v);
const del = (k) => store().delete(k);
const keys = async (prefix) => (await store().list({ prefix })).blobs.map((b) => b.key);

const now = () => new Date().toISOString();
const rid = (n = 4) => randomBytes(n).toString("hex");
const b64 = (b) => Buffer.from(b).toString("base64url");
const sha = (s) => createHash("sha256").update(s).digest("hex");
const eq = (a, b) => { const x = Buffer.from(a), y = Buffer.from(b); return x.length === y.length && timingSafeEqual(x, y); };

function secret() {
  const s = process.env.HUB_SECRET;
  if (!s || s.length < 16) throw new HttpError(500, "HUB_SECRET is not set (16+ characters) in the Netlify environment");
  return s;
}
const sign = (payload) => { const p = b64(JSON.stringify(payload)); return p + "." + createHmac("sha256", secret()).update(p).digest("base64url"); };
function unsign(tok) {
  const [p, sig] = String(tok || "").split(".");
  if (!p || !sig || !eq(sig, createHmac("sha256", secret()).update(p).digest("base64url"))) return null;
  try { const v = JSON.parse(Buffer.from(p, "base64url").toString()); return v.x > Date.now() ? v : null; } catch { return null; }
}
// The project token stays viewable by the owner: kept encrypted (AES-256-GCM, key derived from HUB_SECRET); auth still checks only its hash.
const tokKey = () => scryptSync(secret(), "hub-token", 32);
function sealToken(t) { const iv = randomBytes(12), c = createCipheriv("aes-256-gcm", tokKey(), iv), d = Buffer.concat([c.update(t, "utf8"), c.final()]); return { iv: iv.toString("hex"), tag: c.getAuthTag().toString("hex"), data: d.toString("hex") }; }
function openToken(e) { try { const d = createDecipheriv("aes-256-gcm", tokKey(), Buffer.from(e.iv, "hex")); d.setAuthTag(Buffer.from(e.tag, "hex")); return Buffer.concat([d.update(Buffer.from(e.data, "hex")), d.final()]).toString("utf8"); } catch { return null; } }
const hashPw = (pw, salt = randomBytes(16).toString("hex")) => ({ salt, hash: scryptSync(pw, salt, 32).toString("hex") });
const checkPw = (pw, u) => eq(scryptSync(pw, u.salt, 32).toString("hex"), u.hash);

const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers } });
const cookie = (value, maxAge) => `${COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;

function text(v, name, max, { required = true } = {}) {
  if (v == null || v === "") { if (required) throw bad(`${name} is required`); return ""; }
  if (typeof v !== "string") throw bad(`${name} must be text`);
  if (v.length > max) throw bad(`${name} is longer than ${max} characters`);
  return v.trim();
}

// ---- who is calling ------------------------------------------------------------------------ //
async function whoami(req) {
  const auth = req.headers.get("authorization") || "";
  if (auth.startsWith("Bearer hub_")) {
    const h = sha(auth.slice(7));
    const slug = req.headers.get("x-hub-project") || "";
    if (!SLUG.test(slug)) throw new HttpError(401, "send X-Hub-Project with the token");
    const p = await get(`projects/${slug}`);
    if (!p || !p.tokenHash || !eq(p.tokenHash, h)) throw new HttpError(401, "invalid project token");
    return { kind: "token", name: "claude", project: slug };
  }
  const m = (req.headers.get("cookie") || "").match(new RegExp(`(?:^|; )${COOKIE}=([^;]+)`));
  const s = m && unsign(m[1]);
  if (!s) return null;
  const u = await get(`users/${s.e}`);
  if (!u || (u.role !== "owner" && !(await allowed(u.email)))) return null;      // access removed: treated as signed out
  return { kind: "user", email: u.email, name: u.name, role: u.role };
}
const staticAllowed = () => [...ACCESS.allowed, ...String(process.env.HUB_ALLOWED_EMAILS || "").split(",")].map((e) => e.trim().toLowerCase()).filter(Boolean);
async function allowed(email) {
  email = String(email || "").toLowerCase();
  return staticAllowed().includes(email) || ((await get("access")) || { emails: [] }).emails.includes(email);
}
async function people() {
  const fixed = staticAllowed(), added = ((await get("access")) || { emails: [] }).emails;
  const projects = (await Promise.all((await keys("projects/")).map(get))).filter(Boolean);
  return Promise.all([...new Set([...fixed, ...added])].map(async (email) => {
    const u = await get(`users/${email}`);
    return { email, name: u?.name || "", hasAccount: !!u, fixed: fixed.includes(email), projects: projects.filter((p) => (p.members || []).includes(email)).map((p) => p.slug) };
  }));
}
const need = (who) => { if (!who) throw new HttpError(401, "sign in first"); return who; };
const needOwner = (who) => { need(who); if (who.kind !== "user" || who.role !== "owner") throw new HttpError(403, "owner only"); };
const actor = (who) => (who.kind === "token" ? "claude" : who.name || who.email);

async function project(who, slug, { write = false } = {}) {
  need(who);
  if (!SLUG.test(slug)) throw bad("invalid project id");
  const p = await get(`projects/${slug}`);
  if (!p) throw new HttpError(404, "no such project");
  if (who.kind === "token") { if (who.project !== slug) throw new HttpError(403, "token is for another project"); }
  else if (who.role !== "owner" && !(p.members || []).includes(who.email)) throw new HttpError(404, "no such project");
  return p;
}

async function log(slug, who, kind, summary, extra = {}) {
  const at = now();
  await put(`activity/${slug}/${at}-${rid(3)}`, { at, by: actor(who), via: who.kind === "token" ? "claude" : "web", kind, summary: String(summary).slice(0, 500), ...extra });
}

// ---- routes -------------------------------------------------------------------------------- //
async function route(req, who, parts, url) {
  const method = req.method;
  const body = async () => {
    const t = await req.text();
    if (t.length > MAX_JSON) throw new HttpError(413, "body over 5 MB");
    try { const v = JSON.parse(t || "{}"); if (v && typeof v === "object") return v; } catch { /* fall through */ }
    throw bad("body must be a JSON object");
  };
  const [a, b, c, d] = parts;

  if (a === "me" && method === "GET") return json(200, { user: who && who.kind === "user" ? { email: who.email, name: who.name, role: who.role } : null, token: who && who.kind === "token" ? { project: who.project } : null });

  if (a === "setup" && method === "POST") {
    const v = await body();
    if ((await keys("users/")).length) throw new HttpError(409, "already set up");
    const code = process.env.HUB_SETUP_CODE;
    if (!code || !eq(String(v.code || ""), code)) throw new HttpError(403, "wrong setup code");
    return register(v, "owner");
  }
  if (a === "join" && method === "POST") {
    const v = await body();
    const inv = await get(`invites/${sha(String(v.invite || ""))}`);
    if (!inv || inv.expires < Date.now()) throw new HttpError(403, "this invite is invalid or expired");
    const email = String(v.email || "").toLowerCase();
    if (inv.email && inv.email !== email) throw new HttpError(403, `this invite is for ${inv.email}`);
    if (!(await allowed(email))) throw new HttpError(403, "this email is not authorized for Docs Studio: ask the owner");
    const res = await register(v, "member", inv.projects || []);
    await del(`invites/${sha(String(v.invite))}`);
    return res;
  }
  if (a === "login" && method === "POST") {
    const v = await body();
    const u = EMAIL.test(String(v.email || "").toLowerCase()) ? await get(`users/${String(v.email).toLowerCase()}`) : null;
    if (!u || !checkPw(String(v.password || ""), u)) throw new HttpError(401, "wrong email or password");
    if (u.role !== "owner" && !(await allowed(u.email))) throw new HttpError(403, "your access to Docs Studio was removed: ask the owner");
    return session(u);
  }
  if (a === "logout" && method === "POST") return json(200, { ok: true }, { "Set-Cookie": cookie("", 0) });

  // People who may enter: the access.mjs list, HUB_ALLOWED_EMAILS, and the owner's own list (Blobs).
  if (a === "access") {
    needOwner(who);
    if (method === "GET") return json(200, { people: await people() });
    if (method === "POST") {                       // {email, projects?}: authorize someone (and give them a sign-up link)
      const v = await body();
      const email = String(v.email || "").trim().toLowerCase();
      if (!EMAIL.test(email)) throw bad("a valid email is required");
      const projects = Array.isArray(v.projects) ? v.projects.filter((s) => SLUG.test(s)) : [];
      const list = (await get("access")) || { emails: [] };
      if (!list.emails.includes(email) && !staticAllowed().includes(email)) { list.emails.push(email); await put("access", list); }
      const user = await get(`users/${email}`);
      for (const s of projects) { const p = await get(`projects/${s}`); if (p && user) await put(`projects/${s}`, { ...p, members: [...new Set([...(p.members || []), email])] }); }
      let invite = null;
      if (!user) {
        invite = "inv_" + randomBytes(16).toString("base64url");
        await put(`invites/${sha(invite)}`, { email, projects, expires: Date.now() + 7 * 864e5, by: who.email });
      }
      return json(200, { email, invite, hasAccount: !!user, people: await people() });
    }
    if (method === "DELETE") {                     // ?email=: revoke (takes effect on their next request)
      const email = String(url.searchParams.get("email") || "").toLowerCase();
      if (staticAllowed().includes(email)) throw bad(`${email} is listed in netlify/access.mjs or HUB_ALLOWED_EMAILS: remove it there`);
      const list = (await get("access")) || { emails: [] };
      list.emails = list.emails.filter((e) => e !== email);
      await put("access", list);
      return json(200, { people: await people() });
    }
  }

  if (a === "invites" && method === "POST") {
    needOwner(who);
    const v = await body();
    const projects = Array.isArray(v.projects) ? v.projects.filter((s) => SLUG.test(s)) : [];
    const email = String(v.email || "").trim().toLowerCase();
    if (!EMAIL.test(email) || !(await allowed(email))) throw bad("authorize the email first (People on the projects page)");
    const code = "inv_" + randomBytes(16).toString("base64url");
    await put(`invites/${sha(code)}`, { email, projects, expires: Date.now() + 7 * 864e5, by: who.email });
    return json(200, { invite: code, expiresInDays: 7 });
  }
  if (a === "users" && method === "GET") {
    needOwner(who);
    const us = await Promise.all((await keys("users/")).map(get));
    return json(200, { users: us.map((u) => ({ email: u.email, name: u.name, role: u.role })) });
  }

  // To-do and brainstorming lists: one list per project (and a "general" one), shown together on the home screen.
  if (a === "lists") return lists(req, who, parts.slice(1), method, body);

  if (a === "projects" && !b) {
    need(who);
    if (method === "GET") {
      const all = (await Promise.all((await keys("projects/")).map(get))).filter(Boolean);
      const mine = who.kind === "token" ? all.filter((p) => p.slug === who.project) : who.role === "owner" ? all : all.filter((p) => (p.members || []).includes(who.email));
      return json(200, { projects: mine.map(pub).sort((x, y) => x.name.localeCompare(y.name)) });
    }
    if (method === "POST") {
      needOwner(who);
      const v = await body();
      const name = text(v.name, "name", 80);
      const slug = String(v.slug || name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
      if (!SLUG.test(slug)) throw bad("choose a name with letters or digits");
      if (await get(`projects/${slug}`)) throw new HttpError(409, "a project with this id exists");
      const p = { slug, name, description: text(v.description, "description", 400, { required: false }), members: [], created: now(), createdBy: who.email };
      await put(`projects/${slug}`, p);
      await put(`board/${slug}`, { version: 1, columns: COLUMNS, cards: [] });
      await log(slug, who, "project", `Project created: ${name}`);
      return json(201, { project: pub(p) });
    }
  }

  if (a === "projects" && b) {
    const p = await project(who, b);
    if (!c && method === "GET") return json(200, { project: pub(p), ...(who.kind === "user" && who.role === "owner" ? { members: p.members, hasToken: !!p.tokenHash } : {}) });
    if (c === "members" && method === "PUT") {
      needOwner(who);
      const v = await body();
      const members = [...new Set((Array.isArray(v.members) ? v.members : []).map((e) => String(e).toLowerCase()))];
      for (const e of members) if (!(await get(`users/${e}`))) throw bad(`no user ${e}: send an invite first`);
      await put(`projects/${b}`, { ...p, members });
      await log(b, who, "members", `Members set: ${members.join(", ") || "none"}`);
      return json(200, { members });
    }
    if (c === "token" && method === "GET") {
      needOwner(who);
      return json(200, { token: p.tokenEnc ? openToken(p.tokenEnc) : null, hasToken: !!p.tokenHash });
    }
    if (c === "token" && method === "POST") {
      needOwner(who);
      const t = "hub_" + randomBytes(24).toString("base64url");
      await put(`projects/${b}`, { ...p, tokenHash: sha(t), tokenEnc: sealToken(t) });
      await log(b, who, "token", "Plugin token rotated");
      return json(200, { token: t, note: "store it as HUB_TOKEN" });
    }
    if (c === "board") return board(req, who, p, d, method, body);
    if (c === "docs") return docs(who, p, d, method, body, url);
    if (c === "nav") {                       // sidebar groups (titles, icons) and the home page of the project
      if (method === "GET") return json(200, (await get(`nav/${b}`)) || { home: null, groups: [] });
      if (method === "PUT") {
        const v = await body();
        const groups = (Array.isArray(v.groups) ? v.groups : []).slice(0, 40).filter((g) => SLUG.test(g?.id || "")).map((g) => ({ id: g.id, title: String(g.title || g.id).slice(0, 60), icon: String(g.icon || "").slice(0, 4000) }));
        const nav = { home: SLUG.test(v.home || "") ? v.home : null, groups };
        await put(`nav/${b}`, nav);
        return json(200, nav);
      }
    }
    if (c === "activity") {
      if (method === "GET") {
        const limit = Math.min(Number(url.searchParams.get("limit")) || 100, 300);
        const ks = (await keys(`activity/${b}/`)).sort().slice(-limit).reverse();
        return json(200, { activity: (await Promise.all(ks.map(get))).filter(Boolean) });
      }
      if (method === "POST") {
        const v = await body();
        const kinds = ["summary", "note", "task", "docs", "commit", "decision", "drift"];
        const kind = kinds.includes(v.kind) ? v.kind : "note";
        await log(b, who, kind, text(v.summary, "summary", 500), { detail: v.detail ? String(v.detail).slice(0, 4000) : undefined, sha: /^[a-f0-9]{7,40}$/.test(String(v.sha || "")) ? v.sha : undefined, branch: v.branch ? String(v.branch).slice(0, 100) : undefined, card: CARD_ID.test(v.card || "") ? v.card : undefined, files: Array.isArray(v.files) ? v.files.slice(0, 20).map((f) => String(f).slice(0, 200)) : undefined });
        return json(201, { ok: true });
      }
    }
    if (c === "sync") {                       // the last commit the hub knows about (drift watermark)
      if (method === "GET") return json(200, { sync: (await get(`sync/${b}`)) || null });
      if (method === "PUT") {
        const v = await body();
        if (!/^[a-f0-9]{7,40}$/.test(String(v.head || ""))) throw bad("head must be a commit sha");
        const sync = { head: v.head, branch: String(v.branch || "").slice(0, 100), dirty: /^[a-f0-9]{40}$/.test(String(v.dirty || "")) ? v.dirty : "", at: now(), by: actor(who) };
        await put(`sync/${b}`, sync);
        return json(200, { sync });
      }
    }
    if (c === "wb") return whiteboards(who, p, d, method, body);
  }
  throw new HttpError(404, "no such route");
}

const pub = (p) => ({ slug: p.slug, name: p.name, description: p.description, created: p.created });

async function register(v, role, projects = []) {
  const email = String(v.email || "").toLowerCase();
  if (!EMAIL.test(email)) throw bad("a valid email is required");
  const pw = String(v.password || "");
  if (pw.length < 10) throw bad("password must be at least 10 characters");
  if (await get(`users/${email}`)) throw new HttpError(409, "this email already has an account");
  const u = { email, name: text(v.name, "name", 60), role, ...hashPw(pw), created: now() };
  await put(`users/${email}`, u);
  for (const s of projects) { const p = await get(`projects/${s}`); if (p) await put(`projects/${s}`, { ...p, members: [...new Set([...(p.members || []), email])] }); }
  return session(u);
}
const session = (u) => json(200, { user: { email: u.email, name: u.name, role: u.role } }, { "Set-Cookie": cookie(sign({ e: u.email, x: Date.now() + SESSION_DAYS * 864e5 }), SESSION_DAYS * 86400) });

// ---- board --------------------------------------------------------------------------------- //
// Same shape as docs/board/board.yaml (and what theme/board.js edits): {version, columns[{id,title,status}], cards[], archived[]}.
const STATUSES = ["planned", "running", "done", "blocked"];
const CARD_KEYS = ["id", "title", "package", "column", "order", "owner", "labels", "branch", "sha", "links", "created", "updated", "description", "history", "archived_at"];
const short = (v, name, max) => { if (v == null || v === "") return undefined; if (typeof v !== "string" && typeof v !== "number") throw bad(`${name} must be text`); const s = String(v).trim(); if (s.length > max) throw bad(`${name} is longer than ${max} characters`); return s || undefined; };

function cleanCard(c, cols, n) {
  if (!c || typeof c !== "object") throw bad(`card ${n}: not an object`);
  if (!CARD_ID.test(c.id || "")) throw bad(`card ${n}: invalid id ${String(c.id).slice(0, 20)}`);
  if (cols && !cols.has(c.column)) throw bad(`card ${c.id}: unknown column ${c.column}`);
  const o = { id: c.id, title: text(String(c.title ?? ""), `card ${c.id} title`, 200) };
  for (const [k, max] of [["package", 40], ["column", 40], ["owner", 60], ["branch", 120], ["sha", 64], ["created", 40], ["updated", 40], ["archived_at", 40]]) { const v = short(c[k], `${c.id} ${k}`, max); if (v !== undefined) o[k] = v; }
  if (c.description) o.description = text(String(c.description), `${c.id} description`, 8000);
  o.order = Number(c.order) || 0;
  if (Array.isArray(c.labels)) o.labels = c.labels.slice(0, 12).map((l) => String(l).slice(0, 40));
  if (Array.isArray(c.links)) o.links = c.links.slice(0, 20).filter((l) => JSON.stringify(l).length < 600);
  if (Array.isArray(c.history)) o.history = c.history.slice(-30).filter((h) => h && typeof h === "object").map((h) => Object.fromEntries(Object.entries(h).slice(0, 8).map(([k, v]) => [String(k).slice(0, 20), String(v).slice(0, 120)])));
  return Object.fromEntries(CARD_KEYS.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));
}
function cleanBoard(v, version) {
  if (!v || !Array.isArray(v.columns) || !v.columns.length || v.columns.length > 15 || !Array.isArray(v.cards) || v.cards.length > 3000) throw bad("board must have columns (1-15) and cards (up to 3000)");
  const columns = v.columns.map((c) => {
    const col = { id: text(String(c?.id ?? ""), "column id", 40), title: text(String(c?.title ?? ""), "column title", 60), status: STATUSES.includes(c?.status) ? c.status : "planned" };
    if (!SLUG.test(col.id)) throw bad(`column id ${col.id}: lowercase letters, digits, dashes`);
    return col;
  });
  const ids = new Set(columns.map((c) => c.id));
  const cards = v.cards.map((c, n) => cleanCard(c, ids, n));
  const archived = Array.isArray(v.archived) ? v.archived.slice(-2000).map((c, n) => cleanCard(c, null, n)) : [];
  const seen = new Set();
  for (const c of [...cards, ...archived]) { if (seen.has(c.id)) throw bad(`duplicate card id ${c.id}`); seen.add(c.id); }
  return { version, columns, cards, archived };
}
const boardEtag = (bd) => sha(JSON.stringify([bd.columns, bd.cards, bd.archived || []])).slice(0, 16);
const boardOut = (bd) => ({ version: bd.version, columns: bd.columns, cards: bd.cards, archived: bd.archived || [] });

function boardDiff(old, nw) {
  const om = new Map(old.cards.map((c) => [c.id, c])), nm = new Map(nw.cards.map((c) => [c.id, c]));
  const wasArchived = new Set((old.archived || []).map((c) => c.id)), out = [];
  for (const c of nw.cards) {
    const o = om.get(c.id);
    if (!o) out.push({ card: c.id, s: wasArchived.has(c.id) ? `Card restored: ${c.title}` : `Card created: ${c.title} [${c.column}]` });
    else if (o.column !== c.column) out.push({ card: c.id, s: `Card moved: ${c.title} ${o.column} -> ${c.column}` });
    else if (o.title !== c.title || (o.description || "") !== (c.description || "") || (o.owner || "") !== (c.owner || "")) out.push({ card: c.id, s: `Card edited: ${c.title}` });
  }
  for (const o of old.cards) if (!nm.has(o.id)) out.push({ card: o.id, s: `Card archived: ${o.title}` });
  if (JSON.stringify(old.columns) !== JSON.stringify(nw.columns)) out.push({ s: "Columns changed: " + nw.columns.map((c) => c.title).join(", ") });
  return out;
}

// Column names Claude uses (done, review, running...) mapped onto a project's own columns by their status.
function resolveColumn(bd, name) {
  if (bd.columns.some((c) => c.id === name)) return name;
  const status = { done: "done", review: "running", running: "running", planned: "planned", backlog: "planned", blocked: "blocked" }[name];
  const hits = bd.columns.filter((c) => c.status === status);
  if (!hits.length) return null;
  return (name === "review" ? hits[hits.length - 1] : hits[0]).id;
}

async function board(req, who, p, id, method, body) {
  const key = `board/${p.slug}`;
  const bd = (await get(key)) || { version: 1, columns: COLUMNS, cards: [], archived: [] };
  const cols = new Set(bd.columns.map((c) => c.id));
  const save = async () => { bd.version++; await put(key, bd); };
  const hist = (card, entry) => { card.history = [...(card.history || []), { at: now(), by: actor(who), ...entry }].slice(-30); };
  if (!id && method === "GET") return json(200, bd);

  // The original kanban (theme/board.js): whole-board GET/PUT with an etag, 409 on a concurrent change.
  if (id === "state") {
    if (method === "GET") return json(200, { board: boardOut(bd), etag: boardEtag(bd) });
    if (method === "PUT") {
      const v = await body();
      const match = String(req.headers.get("if-match") || "").replace(/^W\//, "").replace(/"/g, "").trim();
      if (match !== boardEtag(bd)) return json(409, { error: "conflict", errors: ["the board changed meanwhile"], board: boardOut(bd), etag: boardEtag(bd) });
      const nw = cleanBoard(v.board, bd.version + 1);
      const changes = boardDiff(bd, nw);
      Object.assign(bd, nw);
      await put(key, bd);
      for (const ch of changes.slice(0, 10)) await log(p.slug, who, "task", ch.s, ch.card ? { card: ch.card } : {});
      if (changes.length > 10) await log(p.slug, who, "task", `${changes.length - 10} more board changes`);
      return json(200, { board: boardOut(bd), etag: boardEtag(bd), changed: changes.length > 0, committed: false });
    }
    throw new HttpError(405, "method not allowed");
  }

  if (!id && method === "PUT") {                 // full replace, used by the importer
    const v = await body();
    const nw = cleanBoard(v, bd.version + 1);
    Object.assign(bd, nw);
    await put(key, bd);
    await log(p.slug, who, "task", `Board imported: ${nw.cards.length} cards, ${nw.columns.length} columns`);
    return json(200, { version: bd.version, cards: nw.cards.length });
  }

  if (!id && method === "POST") {
    const v = await body();
    const column = (v.column && resolveColumn(bd, v.column)) || bd.columns[0].id;
    const order = Math.max(0, ...bd.cards.filter((c) => c.column === column).map((c) => c.order || 0)) + 1;
    const card = cleanCard({ id: "t_" + rid(3), title: v.title, description: v.description, column, order, owner: v.owner || (who.kind === "token" ? "agent" : "owner"),
                             labels: Array.isArray(v.labels) ? v.labels : [], created: now(), updated: now() }, cols, 0);
    hist(card, { event: "created", to: column });
    bd.cards.push(card);
    await save();
    await log(p.slug, who, "task", `Card created: ${card.title} [${column}]`, { card: card.id });
    return json(201, { card, version: bd.version });
  }
  if (id && !CARD_ID.test(id)) throw bad("invalid card id");
  const i = bd.cards.findIndex((c) => c.id === id);
  if (i < 0) throw new HttpError(404, "no such card");
  const card = bd.cards[i];

  if (method === "PATCH") {
    const v = await body();
    const before = card.column;
    if ("title" in v) card.title = text(v.title, "title", 200);
    if ("description" in v) card.description = text(v.description, "description", 8000, { required: false });
    if ("owner" in v) card.owner = text(v.owner, "owner", 60, { required: false });
    if ("labels" in v) card.labels = Array.isArray(v.labels) ? v.labels.slice(0, 12).map((l) => String(l).slice(0, 40)) : [];
    if ("column" in v) {
      const col = resolveColumn(bd, v.column);
      if (!col) throw bad(`unknown column: use one of ${[...cols].join(", ")}`);
      v.column = col;
      card.column = col;
      card.order = typeof v.order === "number" ? v.order : Math.max(0, ...bd.cards.filter((c) => c.column === v.column).map((c) => c.order || 0)) + 1;
    } else if (typeof v.order === "number") card.order = v.order;
    card.updated = now();
    if (before !== card.column) hist(card, { event: "moved", from: before, to: card.column });
    await save();
    await log(p.slug, who, "task", before !== card.column ? `Card moved: ${card.title} ${before} -> ${card.column}` : `Card updated: ${card.title}`, { card: card.id });
    return json(200, { card, version: bd.version });
  }
  if (method === "DELETE") {
    bd.cards.splice(i, 1);
    hist(card, { event: "archived" });
    card.archived_at = now();
    bd.archived = [...(bd.archived || []), card];
    await save();
    await log(p.slug, who, "task", `Card archived: ${card.title}`, { card: card.id });
    return json(200, { deleted: true, version: bd.version });
  }
  throw new HttpError(405, "method not allowed");
}

// ---- docs ---------------------------------------------------------------------------------- //
// A page is Markdown (written by people or Claude) or HTML (imported from a built docs site, rendered as is after sanitizing in the browser).
async function docs(who, p, id, method, body, url) {
  const base = `docs/${p.slug}/`;
  const meta = ({ id: i, title, group, groupTitle, order, format, kind, updated, updatedBy }) => ({ id: i, title, group, groupTitle, order, format, kind, updated, updatedBy });
  const sortPages = (a, b) => (a.order ?? 1e9) - (b.order ?? 1e9) || a.title.localeCompare(b.title);
  if (!id && method === "GET") {
    const ds = (await Promise.all((await keys(base)).map(get))).filter(Boolean).sort(sortPages);
    return json(200, { pages: url.searchParams.get("full") ? ds : ds.map(meta) });
  }
  if (!SLUG.test(id || "")) throw bad("page id: lowercase letters, digits, dashes");
  if (method === "GET") { const d = await get(base + id); if (!d) throw new HttpError(404, "no such page"); return json(200, d); }
  if (method === "PUT") {
    const v = await body();
    const old = await get(base + id);
    const format = v.format === "html" ? "html" : "md";
    const d = { id, title: text(v.title ?? old?.title, "title", 120), format,
                body: text(v.body, "body", format === "html" ? 1_500_000 : 200_000, { required: false }),
                group: SLUG.test(v.group || "") ? v.group : old?.group || "pages",
                groupTitle: text(v.groupTitle ?? old?.groupTitle ?? "Pages", "groupTitle", 60, { required: false }) || "Pages",
                order: Number.isFinite(Number(v.order)) && v.order !== null && v.order !== "" ? Number(v.order) : old?.order ?? 1000,
                kind: v.kind === "generated" ? "generated" : "written",
                lede: text(v.lede ?? old?.lede ?? "", "lede", 600, { required: false }),
                md: format === "html" ? text(v.md ?? (v.body === old?.body ? old?.md : "") ?? "", "md", 200_000, { required: false }) : undefined,
                updated: now(), updatedBy: actor(who), created: old?.created || now() };
    await put(base + id, d);
    if (!v.quiet) await log(p.slug, who, "docs", `${old ? "Page updated" : "Page created"}: ${d.title}`, { page: id });
    return json(200, { saved: true, updated: d.updated });
  }
  if (method === "DELETE") { await del(base + id); await log(p.slug, who, "docs", `Page deleted: ${id}`, { page: id }); return json(200, { deleted: true }); }
  throw new HttpError(405, "method not allowed");
}

// ---- to-do and brainstorming lists ----------------------------------------------------------- //
// lists/<project|general>/<todo|ideas> = {items: [{id, text, notes, done, by, at, updated, card}]}
const LIST_KINDS = ["todo", "ideas"];
const GENERAL = "general";
async function lists(req, who, rest, method, body) {
  need(who);
  const [kind, scope, id, action] = rest;
  const canSee = async (slug) => {
    if (slug === GENERAL) { if (who.kind === "token") throw new HttpError(403, "the plugin token only reaches its project"); return { slug: GENERAL, name: "General" }; }
    return project(who, slug);
  };
  if (!kind && method === "GET") {                        // everything the caller can see, newest first
    const visible = who.kind === "token" ? [await project(who, who.project)] : (await Promise.all((await keys("projects/")).map(get))).filter((p) => p && (who.role === "owner" || (p.members || []).includes(who.email)));
    const scopes = [...visible.map((p) => ({ slug: p.slug, name: p.name })), ...(who.kind === "token" ? [] : [{ slug: GENERAL, name: "General" }])];
    const out = { todo: [], ideas: [], projects: scopes };
    for (const s of scopes) for (const k of LIST_KINDS) {
      const l = (await get(`lists/${s.slug}/${k}`)) || { items: [] };
      out[k].push(...l.items.map((it) => ({ ...it, project: s.slug, projectName: s.name })));
    }
    for (const k of LIST_KINDS) out[k].sort((x, y) => (y.at || "").localeCompare(x.at || ""));
    return json(200, out);
  }
  if (!LIST_KINDS.includes(kind)) throw bad("list is todo or ideas");
  if (!scope || !(scope === GENERAL || SLUG.test(scope))) throw bad("choose a project (or general)");
  const p = await canSee(scope);
  const key = `lists/${scope}/${kind}`;
  const l = (await get(key)) || { items: [] };
  const noun = kind === "todo" ? "To-do" : "Idea";
  const note = async (summary) => { if (scope !== GENERAL) await log(scope, who, kind === "todo" ? "task" : "note", summary); };

  if (!id && method === "POST") {
    const v = await body();
    const it = { id: "i_" + rid(4), text: text(v.text, "text", 300), notes: text(v.notes, "notes", 4000, { required: false }), done: false, by: actor(who), at: now(), updated: now() };
    l.items.push(it);
    if (l.items.length > 1000) throw bad("this list is full (1000 items): clean up done ones");
    await put(key, l);
    await note(`${noun} added: ${it.text}`);
    return json(201, { item: { ...it, project: scope, projectName: p.name } });
  }
  const it = l.items.find((x) => x.id === id);
  if (!it) throw new HttpError(404, "no such item");
  if (action === "promote" && method === "POST") {          // an idea becomes a card on the project's board
    if (scope === GENERAL) throw bad("pick a project for this idea first");
    const bkey = `board/${scope}`, bd = (await get(bkey)) || { version: 1, columns: COLUMNS, cards: [], archived: [] };
    const column = bd.columns[0].id;
    const card = cleanCard({ id: "t_" + rid(3), title: it.text.slice(0, 200), description: it.notes || "", column, order: Math.max(0, ...bd.cards.filter((c) => c.column === column).map((c) => c.order || 0)) + 1,
                             owner: "owner", labels: ["idea"], created: now(), updated: now(), history: [{ at: now(), event: "created", to: column, by: actor(who) }] }, new Set(bd.columns.map((c) => c.id)), 0);
    bd.cards.push(card); bd.version++;
    await put(bkey, bd);
    it.card = card.id; it.updated = now();
    await put(key, l);
    await log(scope, who, "task", `Idea moved to the board: ${it.text}`, { card: card.id });
    return json(200, { item: { ...it, project: scope, projectName: p.name }, card });
  }
  if (method === "PATCH") {
    const v = await body();
    if ("text" in v) it.text = text(v.text, "text", 300);
    if ("notes" in v) it.notes = text(v.notes, "notes", 4000, { required: false });
    if ("done" in v) { it.done = !!v.done; if (it.done) await note(`${noun} done: ${it.text}`); }
    it.updated = now();
    await put(key, l);
    return json(200, { item: { ...it, project: scope, projectName: p.name } });
  }
  if (method === "DELETE") {
    l.items = l.items.filter((x) => x.id !== id);
    await put(key, l);
    return json(200, { deleted: true });
  }
  throw new HttpError(405, "method not allowed");
}

// ---- whiteboards (same shapes the editor already uses) -------------------------------------- //
async function whiteboards(who, p, id, method, body) {
  const base = `wb/${p.slug}/`;
  if (!id && method === "GET") {
    const ks = await keys(base);
    const bs = (await Promise.all(ks.map(async (k) => { const r = await store().getWithMetadata(k); return r ? { id: k.slice(base.length), title: r.metadata?.title || k, updated: r.metadata?.updated || "" } : null; }))).filter(Boolean);
    return json(200, { boards: bs.sort((x, y) => (y.updated || "").localeCompare(x.updated || "")), commits: false });
  }
  if (!WB_ID.test(id || "")) throw bad("a board id looks like wb_xxxx");
  if (method === "GET") { const d = await get(base + id); if (!d) throw new HttpError(404, "no such board"); return json(200, d); }
  if (method === "PUT") {
    const v = await body();
    if (v.scene !== null && typeof v.scene !== "object") throw bad("the body must be {title, scene}");
    const d = { type: "excalidraw-board", id, title: String(v.title || "Untitled").slice(0, 120), updated: String(v.updated || now()), scene: v.scene };
    await store().setJSON(base + id, d, { metadata: { title: d.title, updated: d.updated } });
    return json(200, { saved: true, committed: false, note: "saved on the server" });
  }
  if (method === "DELETE") { await del(base + id); return json(200, { deleted: true }); }
  throw new HttpError(405, "method not allowed");
}

export default async (req) => {
  try {
    const url = new URL(req.url);
    const parts = url.pathname.replace(/^\/api\/hub\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
    const who = await whoami(req);
    if (who && who.kind === "user" && req.method !== "GET" && req.headers.get("x-hub") !== "1") throw new HttpError(403, "missing X-Hub header");
    return await route(req, who, parts, url);
  } catch (e) {
    if (e instanceof HttpError) return json(e.status, { error: e.message, errors: [e.message] });
    console.error(e);
    return json(500, { error: "server error", errors: ["server error"] });
  }
};

export const config = { path: ["/api/hub", "/api/hub/*"] };
