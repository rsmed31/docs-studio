/* Project view: builds the docs layout (theme/site.js + theme/board.js) from the hub's data, then adds the
 * hub's own pieces: the Workspace pages (board, traceability, settings), saving edits to the hub, and the
 * whiteboard drawer. Everything stored as HTML is sanitized with DOMPurify before it reaches the page. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root = document.documentElement;
  var slug = (location.pathname.match(/^\/p\/([a-z0-9-]+)/) || [])[1] || new URLSearchParams(location.search).get("p") || "";
  var API = "/api/hub/projects/" + encodeURIComponent(slug);
  var me = null, project = null, pages = [], byId = {}, isOwner = false;

  function api(method, path, body) {
    return fetch("/api/hub" + path, { method: method, credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Hub": "1" }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        return r.text().then(function (t) {
          var j = {}; try { j = JSON.parse(t); } catch (e) { /* not JSON */ }
          if (!r.ok) { var err = new Error(j.error || ("Request failed (" + r.status + ")")); err.status = r.status; throw err; }
          return j;
        });
      });
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function clean(html) {
    // animateMotion moves the "packets" along diagram lines (it cannot set attributes, unlike animate/set, which stay forbidden)
    return DOMPurify.sanitize(html, { ADD_TAGS: ["animateMotion"], ADD_ATTR: ["target", "contenteditable", "path", "dur", "begin", "repeatCount", "rotate", "keyPoints", "keyTimes", "calcMode"], FORBID_TAGS: ["style", "script", "iframe", "form", "object", "embed", "link", "meta"] });
  }
  var toastTimer;
  function toast(msg) { var t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 2600); }
  function when(iso) { var d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString([], { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
  function slugify(s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60); }

  // ---- Markdown pages (written in the hub or by Claude) -> the same markup the docs build produces ---- //
  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|#[^)\s]*)\)/g, function (m, t, u) { return '<a href="' + u + '"' + (u[0] === "#" ? "" : ' target="_blank" rel="noopener noreferrer"') + ">" + t + "</a>"; });
  }
  function mdToHtml(src, pid) {
    var lines = String(src || "").replace(/\r\n/g, "\n").split("\n"), out = [], i = 0, list = null, used = {};
    function close() { if (list) { out.push("</" + list + ">"); list = null; } }
    function hid(t) { var b = slugify(t) || "s", k = b, n = 2; while (used[k]) k = b + "-" + n++; used[k] = 1; return pid + "--" + k; }
    while (i < lines.length) {
      var l = lines[i], m;
      if (/^```/.test(l)) { close(); var buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]); i++; out.push("<pre><code>" + esc(buf.join("\n")) + "</code></pre>"); continue; }
      if ((m = /^(#{1,4})\s+(.*)/.exec(l))) { close(); var lv = Math.max(2, m[1].length); out.push("<h" + lv + ' id="' + hid(m[2]) + '">' + inline(m[2]) + "</h" + lv + ">"); }
      else if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        close();
        var row = function (r) { return r.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); }); };
        var head = row(l); i += 2; var rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(row(lines[i++]));
        out.push("<table><thead><tr>" + head.map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") + "</tr></thead><tbody>" +
          rows.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table>");
        continue;
      }
      else if ((m = /^>\s?(.*)/.exec(l))) { close(); out.push("<blockquote><p>" + inline(m[1]) + "</p></blockquote>"); }
      else if ((m = /^\s*[-*]\s+(.*)/.exec(l))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push("<li>" + inline(m[1]) + "</li>"); }
      else if ((m = /^\s*\d+\.\s+(.*)/.exec(l))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push("<li>" + inline(m[1]) + "</li>"); }
      else if (l.trim()) { close(); var para = [l]; while (i + 1 < lines.length && lines[i + 1].trim() && !/^(#|```|\s*[-*]\s|\s*\d+\.\s|>|\s*\|)/.test(lines[i + 1])) para.push(lines[++i]); out.push("<p>" + inline(para.join(" ")) + "</p>"); }
      else close();
      i++;
    }
    close();
    return out.join("\n");
  }
  function head(group, title, lede) {
    return '<header class="page-head"><div class="eyebrow"><span class="crumb-g">' + esc(group) + "</span> </div><h1>" + esc(title) + "</h1>" +
      (lede ? '<p class="lede">' + esc(lede) + "</p>" : "") + "</header>";
  }
  function mdPageHtml(p) {
    var body = String(p.body || "").replace(/^#\s+.*\n+/, "");          // the title is already the page heading
    return head(p.groupTitle || "Pages", p.title, p.lede) +
      '<div class="page-grid"><div class="page-body md" data-editable="1">' + mdToHtml(body, p.id) + "</div></div>";
  }

  // ---- build the page ------------------------------------------------------------------- //
  var ICON_PAGE = '<svg class="ico-svg" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>';
  var ICON_WORK = '<svg class="ico-svg" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>';
  var CHEV = '<svg class="chev" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function article(id, kind, group, inner) {
    var a = document.createElement("article");
    a.className = "page"; a.id = "page-" + id; a.hidden = true;
    a.setAttribute("data-page", id); a.setAttribute("data-kind", kind); a.setAttribute("data-group", group);
    a.innerHTML = inner;
    return a;
  }
  function workspacePages() {
    var list = [
      { id: "hub-board", title: "Board", lede: "Every task of the project. Drag cards between columns; Claude moves its own cards through the plugin.",
        body: '<div id="board-root" class="board-app" data-api="' + API + '/board/state"></div>' },
      { id: "hub-activity", title: "Traceability", lede: "What changed, who did it, and why: board moves, page edits, Claude's summaries and decisions, reconciled drift.",
        body: '<div id="hub-activity"><p class="muted">Loading…</p></div>' }
    ];
    if (isOwner) list.push({ id: "hub-settings", title: "Settings", lede: "Members, the Claude plugin token and how to connect Claude.", body: '<div id="hub-settings"></div>' });
    return list.map(function (w) {
      return { id: w.id, title: w.title, group: "workspace", el: article(w.id, "hub", "workspace",
        head("Workspace", w.title, w.lede) + '<div class="page-grid"><div class="page-body">' + w.body + "</div></div>") };
    });
  }

  function build(nav, boardState) {
    var main = $("#main"), navEl = $("#nav"), groups = [], gmap = {};
    function group(id, title, icon) { if (!gmap[id]) { gmap[id] = { id: id, title: title, icon: icon, items: [] }; groups.push(gmap[id]); } return gmap[id]; }
    group("workspace", "Workspace", ICON_WORK);
    (nav.groups || []).forEach(function (g) { group(g.id, g.title, g.icon ? clean(g.icon) : ICON_PAGE); });
    main.innerHTML = "";

    workspacePages().forEach(function (w) { main.appendChild(w.el); if (w.id !== "hub-settings") gmap.workspace.items.push({ id: w.id, title: w.title }); });   // settings: gear, top right
    pages.forEach(function (p) {
      var g = group(p.group || "pages", p.groupTitle || "Pages", ICON_PAGE);
      var inner = p.format === "html" ? clean(p.body) : (p._html = mdPageHtml(p));
      var a = article(p.id, p.kind === "generated" ? "generated" : "written", g.id, inner);
      if (p.format === "html" && p.kind !== "generated" && !$(".page-body", a)) a.setAttribute("data-kind", "generated");
      // The imported board and whiteboard live in the Workspace and the drawer now.
      $$(".viz-board", a).forEach(function (v) { v.outerHTML = '<p><a class="btn primary" href="#hub-board">Open the board</a></p>'; });
      $$(".wb-embed", a).forEach(function (v) { v.outerHTML = '<p><button type="button" class="btn primary" data-wb-open="1">Open the whiteboard</button></p>'; });
      main.appendChild(a);
      g.items.push({ id: p.id, title: p.title });
    });

    navEl.innerHTML = groups.filter(function (g) { return g.items.length; }).map(function (g) {
      return '<div class="nav-group" data-group="' + esc(g.id) + '"><button type="button" class="nav-title" aria-expanded="false" aria-controls="grp-' + esc(g.id) + '">' +
        '<span class="ico">' + g.icon + '</span><span class="nav-title-t">' + esc(g.title) + "</span>" + CHEV + '</button><div class="nav-items" id="grp-' + esc(g.id) + '">' +
        g.items.map(function (it) { return '<a class="nav-link" href="#' + esc(it.id) + '" data-page="' + esc(it.id) + '" data-group="' + esc(g.id) + '"><span class="dot none"></span><span>' + esc(it.title) + "</span></a>"; }).join("") +
        "</div></div>";
    }).join("");

    var data = { pages: {}, aliases: { overview: nav.home || "" } };
    pages.forEach(function (p) { data.pages[p.id] = { title: p.title, kind: p.kind || "written", md: p.md || (p.format === "md" ? p.body : "") }; });
    addJson("page-data", data);
    addJson("board-data", boardState);

    var latest = pages.reduce(function (m, p) { return p.updated > m ? p.updated : m; }, "");
    root.setAttribute("data-home", nav.home && byId[nav.home] ? nav.home : (pages[0] ? pages[0].id : "hub-board"));
    root.setAttribute("data-build", slug + "@" + latest);
    root.setAttribute("data-edit-scope", slug);
    $("#brand-name").textContent = project.name;
    $("#settings-btn").hidden = !isOwner;
    root.setAttribute("data-site", project.name + " · Docs Studio");
    $("#brand").setAttribute("href", "#" + root.getAttribute("data-home"));
    $("#side-foot").innerHTML = esc(pages.length + " pages") + "<br>" + (latest ? "Updated " + esc(when(latest)) : "");
  }
  function addJson(id, obj) {
    var s = document.createElement("script"); s.type = "application/json"; s.id = id;
    s.textContent = JSON.stringify(obj).replace(/</g, "\\u003c");
    document.body.appendChild(s);
  }
  function load(src) {
    return new Promise(function (ok, ko) { var s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = function () { ko(new Error("could not load " + src)); }; document.body.appendChild(s); });
  }

  // ---- saving in-page edits back to the hub ------------------------------------------------- //
  function saveEdits() {
    var key = "avs-docs-edits-v1:" + slug, stored = null;
    try { stored = JSON.parse(localStorage.getItem(key) || "null"); } catch (e) { stored = null; }
    var edits = stored && stored.pages ? stored.pages : {}, ids = Object.keys(edits).filter(function (id) { return byId[id]; });
    if (!ids.length) { toast("Nothing to save yet: edit some text first."); return; }
    var btn = $("#hub-save"); btn.disabled = true; btn.textContent = "Saving…";
    Promise.all(ids.map(function (id) {
      var p = byId[id], doc = new DOMParser().parseFromString("<div id='x'>" + clean(p.format === "html" ? p.body : p._html) + "</div>", "text/html");
      var pb = $(".page-body", doc), fresh = document.createElement("div");
      fresh.innerHTML = clean(edits[id]);
      $$(".dg-export", fresh).forEach(function (n) { n.remove(); });
      $$("[contenteditable='true']", fresh).forEach(function (n) { n.removeAttribute("contenteditable"); });
      if (pb) pb.innerHTML = fresh.innerHTML;
      return api("PUT", "/projects/" + slug + "/docs/" + id, { title: p.title, format: "html", body: $("#x", doc).innerHTML, group: p.group, groupTitle: p.groupTitle,
        order: p.order, kind: p.kind, lede: p.lede || "", md: "" });
    })).then(function () {
      try { localStorage.removeItem(key); } catch (e) { /* ignore */ }
      toast("Saved to the hub"); setTimeout(function () { location.reload(); }, 600);
    }, function (e) { btn.disabled = false; btn.textContent = "Save to hub"; toast("Not saved: " + e.message); });
  }

  // ---- whiteboard drawer --------------------------------------------------------------------- //
  function wb(open) {
    var d = $("#wb-drawer"), b = $("#wb-body");
    if (open && !b.firstChild) {
      var f = document.createElement("iframe");
      f.title = "Whiteboard"; f.src = "/whiteboard/index.html?project=" + encodeURIComponent(slug);
      b.appendChild(f);
    }
    d.hidden = !open;
    document.body.classList.toggle("wb-open", open);
    $("#wb-open").setAttribute("aria-expanded", open ? "true" : "false");
  }
  function wireWhiteboard() {
    $("#wb-open").addEventListener("click", function () { wb($("#wb-drawer").hidden); });
    $("#wb-close").addEventListener("click", function () { wb(false); });
    $("#wb-wide").addEventListener("click", function () {
      var on = $("#wb-drawer").classList.toggle("wide"); this.setAttribute("aria-pressed", on ? "true" : "false"); this.textContent = on ? "Side panel" : "Full width";
    });
    document.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("[data-wb-open]")) wb(true); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !$("#wb-drawer").hidden && $("#palette").hidden) wb(false);
      var t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
      if (!typing && !e.ctrlKey && !e.metaKey && !e.altKey && (e.key === "w" || e.key === "W") && $("#palette").hidden) wb($("#wb-drawer").hidden);
    });
  }

  // ---- traceability ----------------------------------------------------------------------------- //
  function renderActivity() {
    var box = $("#hub-activity"); if (!box) return;
    Promise.all([api("GET", "/projects/" + slug + "/activity?limit=300"), api("GET", "/projects/" + slug + "/sync").catch(function () { return {}; })]).then(function (r) {
      var acts = r[0].activity, sync = r[1].sync, kinds = {};
      acts.forEach(function (a) { kinds[a.kind] = (kinds[a.kind] || 0) + 1; });
      var syncLine = sync ? "In sync with commit <code>" + esc(sync.head.slice(0, 7)) + "</code> on <code>" + esc(sync.branch || "?") + "</code>, " + esc(when(sync.at)) + ". Later commits are checked for drift when Claude starts."
                          : "No commit recorded yet: the first Claude session with the plugin sets the baseline.";
      box.innerHTML = '<p class="muted">' + syncLine + "</p>" +
        '<div class="tbl-tools"><input class="tbl-filter" id="act-q" type="search" placeholder="Filter the log" aria-label="Filter the log">' +
        '<select id="act-k" aria-label="Kind"><option value="">All kinds</option>' + Object.keys(kinds).sort().map(function (k) { return '<option value="' + esc(k) + '">' + esc(k) + " (" + kinds[k] + ")</option>"; }).join("") + "</select></div>" +
        '<table class="hub-log"><thead><tr><th>When</th><th>Kind</th><th>What</th><th>By</th></tr></thead><tbody>' +
        (acts.length ? acts.map(function (a) {
          return '<tr data-k="' + esc(a.kind) + '"><td class="nowrap">' + esc(when(a.at)) + '</td><td><span class="badge ' + (a.kind === "drift" ? "warn" : a.kind === "decision" ? "planned" : a.kind === "summary" ? "done" : "none") + '">' + esc(a.kind) + "</span></td><td>" +
            esc(a.summary) + (a.card ? ' <code>' + esc(a.card) + "</code>" : "") + (a.detail ? '<details><summary>Details</summary><pre>' + esc(a.detail) + "</pre></details>" : "") +
            "</td><td>" + esc(a.by) + (a.via === "claude" ? ' <span class="badge running">plugin</span>' : "") + "</td></tr>";
        }).join("") : '<tr><td colspan="4">Nothing yet.</td></tr>') + "</tbody></table>";
      function filter() {
        var q = $("#act-q").value.toLowerCase(), k = $("#act-k").value;
        $$("tbody tr", box).forEach(function (tr) { tr.hidden = (k && tr.getAttribute("data-k") !== k) || (q && tr.textContent.toLowerCase().indexOf(q) < 0); });
      }
      $("#act-q").addEventListener("input", filter); $("#act-k").addEventListener("change", filter);
    }, function (e) { box.innerHTML = '<p class="muted">Could not load the log: ' + esc(e.message) + "</p>"; });
  }

  // ---- settings (owner) --------------------------------------------------------------------- //
  function copy(text) {
    function done() { toast("Copied"); }
    function fallback() {
      var ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { toast("Copy failed: select the text"); } ta.remove();
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  }
  function copyBlock(label, text) {
    return '<div class="hub-copy"><div class="hub-copy-head"><strong>' + esc(label) + '</strong><button type="button" class="btn small" data-copy="' + esc(text) + '">Copy</button></div><pre><code>' + esc(text) + "</code></pre></div>";
  }
  function renderSettings() {
    var box = $("#hub-settings"); if (!box) return;
    Promise.all([api("GET", "/projects/" + slug), api("GET", "/projects/" + slug + "/token")]).then(function (r) {
      var info = r[0], tok = r[1], u = location.origin, t = tok.token;
      var html = "<h2>Members</h2><p>Emails of the people who can open this project, separated by commas. They need access first: authorize them from the projects page.</p>" +
        '<div class="hub-row"><input id="members" class="tbl-filter" value="' + esc((info.members || []).join(", ")) + '"><button type="button" class="btn" id="save-members">Save members</button></div>' +
        "<h2>Connect Claude Code</h2><p>The project token lets the docs-studio plugin read and write this project's board, pages, lists and traceability. It stays visible here; rotate it only if it leaked.</p>";
      if (t) {
        var settings = JSON.stringify({ env: { HUB_URL: u, HUB_PROJECT: slug, HUB_TOKEN: t } }, null, 2);
        var workflow = ["name: Docs Studio PR report", "on: pull_request", "permissions:", "  contents: read", "  pull-requests: write", "jobs:", "  report:", "    runs-on: ubuntu-latest",
          "    steps:", "      - uses: actions/checkout@v4", "        with:", "          fetch-depth: 0", "      - uses: rsmed31/docs-studio@v0", "        with:",
          "          hub-url: " + u, "          hub-project: " + slug, "          hub-token: ${{ secrets.DOCS_STUDIO_TOKEN }}"].join("\n");
        html += copyBlock("Token", t) +
          "<h3>1. Install the plugin (once per machine)</h3><p>In Claude Code:</p>" +
          copyBlock("Claude Code", "/plugin marketplace add rsmed31/docs-studio\n/plugin install docs-studio@docs-studio") +
          "<h3>2. Point the project at this hub</h3><p>Save as <code>.claude/settings.local.json</code> in the project's repository (it is git-ignored by Claude Code; do not commit the token).</p>" +
          copyBlock(".claude/settings.local.json", settings) +
          "<h3>3. Bring an existing docs-studio site in (optional)</h3><p>Ask Claude: <em>import our docs site into Docs Studio</em>. It runs <code>hub_import_site</code>: every page as rendered, the sidebar groups and the board.</p>" +
          "<h3>4. Report on every pull request (optional)</h3><p>Add the token as the repository secret <code>DOCS_STUDIO_TOKEN</code>, then this workflow as <code>.github/workflows/docs-studio.yml</code>: each PR gets one comment with what Claude did, the decisions and why, risky files, and whether the docs kept up.</p>" +
          copyBlock(".github/workflows/docs-studio.yml", workflow) +
          '<p><button type="button" class="btn danger" id="rotate">Rotate token</button></p>';
      } else {
        html += (tok.hasToken ? "<p>A token exists from before tokens were viewable. Rotate it once to see it here from now on.</p>" : "") +
          '<p><button type="button" class="btn primary" id="rotate">' + (tok.hasToken ? "Rotate token" : "Create token") + "</button></p>";
      }
      box.innerHTML = html;
      $("#save-members", box).addEventListener("click", function () {
        api("PUT", "/projects/" + slug + "/members", { members: $("#members").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean) })
          .then(function () { toast("Members saved"); }, function (e) { toast(e.message); });
      });
      $("#rotate", box).addEventListener("click", function () {
        if (t && !confirm("Rotate the token? Anything using the old one (plugin, importer) stops working.")) return;
        api("POST", "/projects/" + slug + "/token").then(function () { toast("New token created"); renderSettings(); }, function (e) { toast(e.message); });
      });
    }, function (e) { box.innerHTML = '<p class="muted">' + esc(e.message) + "</p>"; });
  }

  // ---- start ------------------------------------------------------------------------------- //
  function fail(msg) { $("#main").innerHTML = '<div class="hub-empty"><h1>' + esc(msg) + '</h1><p><a class="btn primary" href="/">Back to projects</a></p></div>'; }
  api("GET", "/me").then(function (r) {
    if (!r.user) { location.href = "/"; return; }
    me = r.user; isOwner = me.role === "owner";
    $("#hub-user").innerHTML = '<span class="muted">' + esc(me.name) + '</span> <button type="button" class="btn small ghost" id="sign-out">Sign out</button>';
    $("#sign-out").addEventListener("click", function () { api("POST", "/logout").then(function () { location.href = "/"; }); });
    if (!slug) { fail("No project chosen"); return; }
    return Promise.all([api("GET", "/projects/" + slug), api("GET", "/projects/" + slug + "/docs?full=1"), api("GET", "/projects/" + slug + "/nav"), api("GET", "/projects/" + slug + "/board/state")])
      .then(function (r) {
        project = r[0].project; pages = r[1].pages || [];
        pages.forEach(function (p) { byId[p.id] = p; });
        document.title = project.name + " · Docs Studio";
        build(r[2] || {}, r[3]);
        wireWhiteboard();
        $("#hub-save").addEventListener("click", saveEdits);
        document.addEventListener("click", function (e) { var b = e.target.closest && e.target.closest("[data-copy]"); if (b) copy(b.getAttribute("data-copy")); });
        return load("/theme/site.js").then(function () { return load("/theme/board.js"); }).then(function () { return load("/theme/presets.js"); }).then(function () {
          renderActivity(); renderSettings();
          window.addEventListener("hashchange", function () { if (location.hash === "#hub-activity") renderActivity(); });
        });
      }, function (e) { fail(e.status === 404 ? "This project does not exist, or you are not a member" : e.message); });
  }, function (e) { fail("The hub is not reachable: " + e.message); });
})();
