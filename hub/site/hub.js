/* Docs Studio home: sign in / set up / join, pick a project (opens /p/<slug>), create projects, authorize people (owner). */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var app = $("#app"), me = null;
  var ICON = '<svg class="ico-svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
  var PLUS = '<svg class="ico-svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
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
  var toastTimer;
  function toast(msg) { var t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 2600); }
  function when(iso) { var d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" }); }

  $("#theme-toggle").addEventListener("click", function () {
    var root = document.documentElement, cur = root.getAttribute("data-theme");
    if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var next = cur === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next); try { localStorage.setItem("avs-docs-theme", next); } catch (e) { /* ignore */ }
  });

  function dialog(title, intro, fields, okLabel, ok) {
    var d = document.createElement("dialog");
    d.innerHTML = "<form><h2>" + esc(title) + "</h2>" + (intro ? '<p class="muted">' + intro + "</p>" : "") +
      fields.map(function (f, i) { return '<label for="f' + i + '">' + esc(f.label) + "</label>" + (f.area ? '<textarea id="f' + i + '" rows="3"></textarea>' : '<input id="f' + i + '" autocomplete="off">'); }).join("") +
      '<div class="hub-err"></div><div class="hub-dlg-actions"><button type="button" class="btn" data-x="1">Cancel</button><button type="submit" class="btn primary">' + esc(okLabel || "OK") + "</button></div></form>";
    document.body.appendChild(d);
    fields.forEach(function (f, i) { $("#f" + i, d).value = f.value || ""; });
    $("[data-x]", d).addEventListener("click", function () { d.close(); d.remove(); });
    $("form", d).addEventListener("submit", function (e) {
      e.preventDefault();
      var v = fields.map(function (f, i) { return $("#f" + i, d).value; });
      Promise.resolve(ok(v)).then(function () { d.close(); d.remove(); }, function (x) { $(".hub-err", d).textContent = x.message; });
    });
    d.showModal();
    var first = $("input,textarea", d); if (first) first.focus();
  }

  // ---- sign in, first owner, invite ------------------------------------------------------- //
  function auth(mode, invite) {
    var title = { login: "Sign in", setup: "Set up the hub", join: "Join the hub" }[mode];
    var intro = { login: "Docs, board, whiteboard and what Claude did, for every project. Access is by invitation only.", setup: "Create the owner account. You need the setup code (HUB_SETUP_CODE on Netlify).", join: "You were invited. Create your account." }[mode];
    app.innerHTML = '<form class="hub-auth"><h1>' + title + "</h1><p>" + intro + "</p>" +
      (mode !== "login" ? '<label for="a-name">Your name</label><input id="a-name" autocomplete="name" required>' : "") +
      '<label for="a-email">Email</label><input id="a-email" type="email" autocomplete="username" required>' +
      '<label for="a-pw">Password' + (mode === "login" ? "" : " (10+ characters)") + '</label><input id="a-pw" type="password" autocomplete="' + (mode === "login" ? "current-password" : "new-password") + '" required>' +
      (mode === "setup" ? '<label for="a-code">Setup code</label><input id="a-code" type="password" required>' : "") +
      '<button class="btn primary" type="submit">' + (mode === "login" ? "Sign in" : mode === "setup" ? "Create the owner account" : "Join") + '</button><div class="hub-err"></div>' +
      '<div class="hub-alt">' + (mode === "login" ? '<a href="#/setup">First time here? Set up the owner account</a>' : '<a href="#/">Back to sign in</a>') + "</div></form>";
    $("form", app).addEventListener("submit", function (e) {
      e.preventDefault();
      var body = { email: $("#a-email").value, password: $("#a-pw").value };
      if ($("#a-name")) body.name = $("#a-name").value;
      if ($("#a-code")) body.code = $("#a-code").value;
      if (invite) body.invite = invite;
      api("POST", mode === "login" ? "/login" : mode === "setup" ? "/setup" : "/join", body)
        .then(function (r) { me = r.user; location.hash = "#/"; route(); }, function (x) { $(".hub-err", app).textContent = x.message; });
    });
    $("#a-" + (mode === "login" ? "email" : "name")).focus();
  }

  // ---- projects -------------------------------------------------------------------------- //
  var projectsCache = [];
  function home() {
    $("#hub-user").innerHTML = '<span class="muted">' + esc(me.name) + (me.role === "owner" ? " · owner" : "") + '</span> <button type="button" class="btn small ghost" id="sign-out">Sign out</button>';
    $("#sign-out").addEventListener("click", function () { api("POST", "/logout").then(function () { me = null; $("#hub-user").innerHTML = ""; route(); }); });
    app.innerHTML = '<div class="hub-hero"><div><h1>Projects</h1><p>Open a project for its docs, board, whiteboard and traceability. Claude keeps them current through the hub-sync plugin.</p></div></div>' +
      '<div class="cards" id="grid"><p class="muted">Loading…</p></div>' +
      listsSection() +
      (me.role === "owner" ? '<section class="hub-section"><div class="hub-hero"><div><h2>People with access</h2><p>Only these people can enter Docs Studio. Removing someone signs them out at once.</p></div>' +
        '<button type="button" class="btn primary" id="add-person">Authorize someone</button></div><div id="people"><p class="muted">Loading…</p></div></section>' : "");
    api("GET", "/projects").then(function (r) {
      projectsCache = r.projects;
      var html = r.projects.map(function (p) {
        return '<a class="card link" href="/p/' + esc(p.slug) + '"><div class="card-top"><span class="ico">' + ICON + '</span></div><div class="card-title">' + esc(p.name) + '</div><p class="card-text">' +
          esc(p.description || "No description yet.") + '</p><p class="card-meta">Created ' + esc(when(p.created)) + '</p><span class="card-go" aria-hidden="true">&rarr;</span></a>';
      }).join("");
      if (me.role === "owner") html += '<button type="button" class="card link hub-new" id="new"><div class="card-top"><span class="ico">' + PLUS + '</span></div><div class="card-title">New project</div><p class="card-text">Start with an empty board and pages; Claude fills them as it works.</p></button>';
      if (!r.projects.length && me.role !== "owner") html = '<p class="muted">No project yet. Ask the owner to add you to one.</p>';
      $("#grid").innerHTML = html;
      var nb = $("#new");
      if (nb) nb.addEventListener("click", function () {
        dialog("New project", "", [{ label: "Name" }, { label: "Description (optional)", area: true }], "Create", function (v) {
          return api("POST", "/projects", { name: v[0], description: v[1] }).then(function (r2) { location.href = "/p/" + r2.project.slug; });
        });
      });
      if (me.role === "owner") loadPeople();
      loadLists();
    }, function (e) { $("#grid").innerHTML = '<p class="muted">' + esc(e.message) + "</p>"; });
    var add = $("#add-person");
    if (add) add.addEventListener("click", function () { authorize(""); });
  }

  // ---- to-do and brainstorming (every project, on the home screen) -------------------------- //
  var L = { data: null, filter: "", showDone: false };
  var CHECK = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M5 12l5 5L20 7" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  function listsSection() {
    return '<section class="hub-section"><div class="hub-hero"><div><h2>To do and brainstorming</h2><p>Across all your projects. Claude can add to them too, through the plugin.</p></div>' +
      '<div class="hub-row"><select id="l-filter" aria-label="Show project"><option value="">All projects</option></select>' +
      '<label class="hub-check"><input type="checkbox" id="l-done"> Show done</label></div></div>' +
      '<div class="hub-lists"><div class="hub-list" data-kind="todo"><h3>To do <span class="k-count" id="n-todo"></span></h3>' + addForm("todo", "Add a to-do…") + '<ul id="l-todo"></ul></div>' +
      '<div class="hub-list" data-kind="ideas"><h3>Brainstorming <span class="k-count" id="n-ideas"></span></h3>' + addForm("ideas", "Drop an idea…") + '<ul id="l-ideas"></ul></div></div></section>';
  }
  function addForm(kind, ph) {
    return '<form class="hub-add" data-kind="' + kind + '"><input name="text" placeholder="' + ph + '" maxlength="300" autocomplete="off" aria-label="' + ph + '">' +
      '<select name="project" aria-label="Project"></select><button class="btn primary" type="submit">Add</button></form>';
  }
  function loadLists() {
    if (!$("#l-todo")) return;
    api("GET", "/lists").then(function (r) {
      L.data = r;
      var opts = r.projects.map(function (p) { return '<option value="' + esc(p.slug) + '">' + esc(p.name) + "</option>"; }).join("");
      var f = $("#l-filter"), keep = f.value;
      f.innerHTML = '<option value="">All projects</option>' + opts; f.value = keep;
      Array.prototype.forEach.call(document.querySelectorAll(".hub-add select"), function (s) {
        var k = s.value; s.innerHTML = opts; s.value = k || L.filter || (r.projects[0] ? r.projects[0].slug : "general");
      });
      drawLists();
    }, function (e) { $("#l-todo").innerHTML = '<li class="muted">' + esc(e.message) + "</li>"; });
  }
  function drawLists() {
    ["todo", "ideas"].forEach(function (kind) {
      var items = L.data[kind].filter(function (it) { return (!L.filter || it.project === L.filter) && (L.showDone || !it.done); });
      if (kind === "todo") items.sort(function (a, b) { return (a.done - b.done) || (b.at || "").localeCompare(a.at || ""); });
      var open = L.data[kind].filter(function (it) { return (!L.filter || it.project === L.filter) && !it.done; }).length;
      $("#n-" + kind).textContent = open;
      $("#l-" + kind).innerHTML = items.length ? items.map(function (it) {
        var ref = 'data-kind="' + kind + '" data-p="' + esc(it.project) + '" data-id="' + esc(it.id) + '"';
        return '<li class="hub-item' + (it.done ? " done" : "") + '"' + ' ' + ref + ">" +
          (kind === "todo" ? '<button type="button" class="hub-tick" data-a="toggle" aria-label="' + (it.done ? "Mark not done" : "Mark done") + '">' + (it.done ? CHECK : "") + "</button>" : '<span class="hub-bulb" aria-hidden="true">✦</span>') +
          '<div class="hub-item-main"><div class="hub-item-text">' + esc(it.text) + "</div>" + (it.notes ? '<div class="hub-item-notes">' + esc(it.notes) + "</div>" : "") +
          '<div class="hub-item-meta"><a class="hub-chip" href="' + (it.project === "general" ? "#/" : "/p/" + esc(it.project)) + '">' + esc(it.projectName) + "</a> " + esc(it.by) + " · " + esc(when(it.at)) +
          (it.card ? ' · <a href="/p/' + esc(it.project) + '#hub-board">on the board</a>' : "") + "</div></div>" +
          '<div class="hub-item-acts">' + (kind === "ideas" && !it.card && it.project !== "general" ? '<button type="button" class="btn small" data-a="promote" title="Create a board card from this idea">To board</button>' : "") +
          (kind === "ideas" && !it.done ? '<button type="button" class="btn small ghost" data-a="toggle" title="Archive this idea">Archive</button>' : "") +
          '<button type="button" class="btn small ghost" data-a="edit">Edit</button><button type="button" class="btn small ghost" data-a="delete" aria-label="Delete">✕</button></div></li>';
      }).join("") : '<li class="muted hub-empty-l">' + (kind === "todo" ? "Nothing to do here." : "No ideas yet.") + "</li>";
    });
  }
  function itemOf(li) { var k = li.getAttribute("data-kind"); return L.data[k].filter(function (x) { return x.id === li.getAttribute("data-id") && x.project === li.getAttribute("data-p"); })[0]; }
  function itemPath(li, extra) { return "/lists/" + li.getAttribute("data-kind") + "/" + encodeURIComponent(li.getAttribute("data-p")) + "/" + encodeURIComponent(li.getAttribute("data-id")) + (extra || ""); }
  document.addEventListener("submit", function (e) {
    var f = e.target.closest && e.target.closest(".hub-add"); if (!f) return;
    e.preventDefault();
    var t = f.elements.text.value.trim(); if (!t) return;
    api("POST", "/lists/" + f.getAttribute("data-kind") + "/" + encodeURIComponent(f.elements.project.value), { text: t })
      .then(function () { f.elements.text.value = ""; f.elements.text.focus(); loadLists(); }, function (x) { toast(x.message); });
  });
  document.addEventListener("change", function (e) {
    if (e.target.id === "l-filter") { L.filter = e.target.value; if (L.filter) Array.prototype.forEach.call(document.querySelectorAll(".hub-add select"), function (s) { s.value = L.filter; }); drawLists(); }
    if (e.target.id === "l-done") { L.showDone = e.target.checked; drawLists(); }
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".hub-item [data-a]"); if (!b) return;
    var li = b.closest(".hub-item"), it = itemOf(li), a = b.getAttribute("data-a");
    if (a === "toggle") api("PATCH", itemPath(li), { done: !it.done }).then(loadLists, function (x) { toast(x.message); });
    else if (a === "delete") { if (confirm("Delete \"" + it.text + "\"?")) api("DELETE", itemPath(li)).then(loadLists, function (x) { toast(x.message); }); }
    else if (a === "promote") api("POST", itemPath(li, "/promote")).then(function (r) { toast("Card " + r.card.id + " added to the board"); loadLists(); }, function (x) { toast(x.message); });
    else if (a === "edit") dialog("Edit", "", [{ label: "Text", value: it.text }, { label: "Notes", value: it.notes || "", area: true }], "Save", function (v) {
      return api("PATCH", itemPath(li), { text: v[0], notes: v[1] }).then(loadLists);
    });
  });

  // ---- people (owner) ------------------------------------------------------------------- //
  function loadPeople(list) {
    var box = $("#people"); if (!box) return;
    (list ? Promise.resolve({ people: list }) : api("GET", "/access")).then(function (r) {
      var name = function (slug) { var p = projectsCache.filter(function (x) { return x.slug === slug; })[0]; return p ? p.name : slug; };
      box.innerHTML = r.people.length ? '<div class="tablewrap"><table><thead><tr><th>Email</th><th>Account</th><th>Projects</th><th></th></tr></thead><tbody>' + r.people.map(function (p) {
        return "<tr><td>" + esc(p.email) + (p.name ? '<br><span class="muted">' + esc(p.name) + "</span>" : "") + "</td><td>" +
          (p.hasAccount ? '<span class="badge done">Active</span>' : '<span class="badge planned">Not signed up yet</span>') + "</td><td>" +
          (p.projects.length ? p.projects.map(function (s) { return esc(name(s)); }).join(", ") : '<span class="muted">none yet</span>') + '</td><td class="hub-actions">' +
          '<button type="button" class="btn small" data-act="projects" data-email="' + esc(p.email) + '">' + (p.hasAccount ? "Projects" : "Invite link") + "</button>" +
          (p.fixed ? ' <span class="muted" title="Listed in netlify/access.mjs: remove it there">always allowed</span>' : ' <button type="button" class="btn small danger" data-act="remove" data-email="' + esc(p.email) + '">Remove</button>') +
          "</td></tr>";
      }).join("") + "</tbody></table></div>" : '<p class="muted">Nobody yet: only you can enter.</p>';
    }, function (e) { box.innerHTML = '<p class="muted">' + esc(e.message) + "</p>"; });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("#people [data-act]"); if (!b) return;
    var email = b.getAttribute("data-email");
    if (b.getAttribute("data-act") === "projects") authorize(email);
    else if (confirm("Remove " + email + "? They are signed out and cannot enter Docs Studio any more.")) {
      api("DELETE", "/access?email=" + encodeURIComponent(email)).then(function (r) { toast("Access removed"); loadPeople(r.people); }, function (x) { toast(x.message); });
    }
  });
  function authorize(email) {
    var d = document.createElement("dialog");
    d.innerHTML = "<form><h2>" + (email ? "Access for " + esc(email) : "Authorize someone") + '</h2><p class="muted">They can enter Docs Studio and open the projects you tick.</p>' +
      (email ? "" : '<label for="p-email">Email</label><input id="p-email" type="email" autocomplete="off" required>') +
      '<label>Projects</label><div class="hub-checks">' + (projectsCache.length ? projectsCache.map(function (p) {
        return '<label class="hub-check"><input type="checkbox" value="' + esc(p.slug) + '"> ' + esc(p.name) + "</label>";
      }).join("") : '<span class="muted">No project yet.</span>') + '</div><div class="hub-err"></div><div id="p-link"></div>' +
      '<div class="hub-dlg-actions"><button type="button" class="btn" data-x="1">Close</button><button type="submit" class="btn primary">' + (email ? "Save" : "Authorize") + "</button></div></form>";
    document.body.appendChild(d);
    $("[data-x]", d).addEventListener("click", function () { d.close(); d.remove(); loadPeople(); });
    $("form", d).addEventListener("submit", function (ev) {
      ev.preventDefault();
      var projects = Array.prototype.slice.call(d.querySelectorAll(".hub-check input:checked")).map(function (i) { return i.value; });
      api("POST", "/access", { email: email || $("#p-email", d).value, projects: projects }).then(function (r) {
        loadPeople(r.people);
        if (r.invite) {
          var link = location.origin + "/#/join/" + r.invite;
          $("#p-link", d).innerHTML = '<p>Send this sign-up link to <strong>' + esc(r.email) + '</strong> (single use, 7 days, only works with that email):</p>' +
            '<div class="hub-copy"><pre><code>' + esc(link) + '</code></pre><button type="button" class="btn small" id="p-copy">Copy link</button></div>';
          $("#p-copy", d).addEventListener("click", function () { (navigator.clipboard ? navigator.clipboard.writeText(link) : Promise.reject()).then(function () { toast("Link copied"); }, function () { toast("Select the link and copy it"); }); });
        } else { toast("Saved"); d.close(); d.remove(); }
      }, function (x) { $(".hub-err", d).textContent = x.message; });
    });
    d.showModal();
  }

  function route() {
    var parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
    if (parts[0] === "p" && parts[1]) { location.replace("/p/" + encodeURIComponent(parts[1])); return; }   // old links
    if (parts[0] === "join" && parts[1]) return auth("join", parts[1]);
    if (!me) return auth(parts[0] === "setup" ? "setup" : "login");
    home();
  }
  window.addEventListener("hashchange", route);
  api("GET", "/me").then(function (r) { me = r.user; route(); }, function (e) {
    app.innerHTML = '<p class="muted">The hub API is not reachable here (' + esc(e.message) + "). It runs on Netlify.</p>";
  });
})();
