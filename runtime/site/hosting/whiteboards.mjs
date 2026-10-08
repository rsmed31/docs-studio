// Whiteboard storage for Netlify: one JSON document per board in a Netlify Blobs store.
// GET /api/whiteboards -> {boards}; GET/PUT/DELETE /api/whiteboards/<id>.
import { getStore } from "@netlify/blobs";

const ID = /^wb_[a-z0-9]{4,40}$/;
const MAX_BYTES = 5 * 1024 * 1024; // Netlify Functions cap request bodies near 6 MB

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });

export default async (req) => {
  const store = getStore("whiteboards");
  const id = new URL(req.url).pathname.replace(/\/+$/, "").split("/").pop();
  const isList = id === "whiteboards";

  if (isList) {
    if (req.method !== "GET") return json(405, { error: "method not allowed" });
    const { blobs } = await store.list();
    const boards = (await Promise.all(blobs.map(async ({ key }) => {
      const r = await store.getWithMetadata(key);
      return r ? { id: key, title: r.metadata?.title || key, updated: r.metadata?.updated || "" } : null;
    }))).filter(Boolean);
    boards.sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
    return json(200, { boards, commits: false });
  }

  if (!ID.test(id)) return json(400, { error: "invalid", errors: ["a board id looks like wb_xxxx"] });

  if (req.method === "GET") {
    const doc = await store.get(id, { type: "json" });
    return doc ? json(200, doc) : json(404, { error: "not found", errors: ["no board with this id"] });
  }
  if (req.method === "PUT") {
    const text = await req.text();
    if (text.length > MAX_BYTES) return json(413, { error: "too large", errors: ["board is over 5 MB (remove large images)"] });
    let p;
    try { p = JSON.parse(text); } catch { p = null; }
    if (!p || typeof p !== "object" || (p.scene !== null && typeof p.scene !== "object"))
      return json(400, { error: "invalid", errors: ["the body must be {title, scene}"] });
    const doc = { type: "excalidraw-board", id, title: String(p.title || "Untitled").slice(0, 120),
                  updated: String(p.updated || ""), scene: p.scene };
    await store.setJSON(id, doc, { metadata: { title: doc.title, updated: doc.updated } });
    return json(200, { saved: true, committed: false, note: "saved on the server" });
  }
  if (req.method === "DELETE") {
    await store.delete(id);
    return json(200, { deleted: true, committed: false });
  }
  return json(405, { error: "method not allowed" });
};

export const config = { path: ["/api/whiteboards", "/api/whiteboards/*"] };
