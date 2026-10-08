/* Status board: a kanban over docs/board/board.yaml.
 *
 * Served by docs/site/studio.py start the board loads and saves through /api/board (the repository file is
 * the source of truth, saves are committed one file at a time). Opened as a plain file it still works
 * on the copy built into the page, keeps your changes in this browser (guarded localStorage) and lets
 * you download board.yaml. The text form written here mirrors docs/board/board.py (dumps).
 */
(function () {
  'use strict';
  var root = document.getElementById('board-root');
  var seedEl = document.getElementById('board-data');
  if (!root || !seedEl) return;
  var seed = null;
  try { seed = JSON.parse(seedEl.textContent); } catch (e) { seed = null; }
  if (!seed || !seed.board) return;

  var OWNERS = ['owner', 'agent', 'integrator'];
  var STATUSES = ['planned', 'running', 'done', 'blocked'];
  var STATUS_LABEL = { planned: 'Counts as planned', running: 'Counts as in progress', done: 'Counts as built', blocked: 'Blocked' };
  var KEY = 'avs-board-v1';
  var HISTORY_KEEP = 30;
  var SAVE_DELAY = 900;

  // ---- tiny helpers ---------------------------------------------------------------- //
  var store = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem(k, v); return true; } catch (e) { return false; } },
    del: function (k) { try { window.localStorage.removeItem(k); } catch (e) { /* ignore */ } }
  };
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function $(sel, ctx) { return (ctx || root).querySelector(sel); }
  function $$(sel, ctx) { return Array.prototype.slice.call((ctx || root).querySelectorAll(sel)); }
  function nowIso() { return new Date().toISOString().replace(/\.\d+Z$/, 'Z'); }
  function newId(taken) {
    var chars = 'abcdefghijklmnopqrstuvwxyz0123456789', id;
    do {
      var bytes = new Uint8Array(6);
      if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(bytes); else for (var i = 0; i < 6; i++) bytes[i] = Math.floor(Math.random() * 256);
      id = 't_';
      for (var j = 0; j < 6; j++) id += chars.charAt(bytes[j] % chars.length);
    } while (taken[id]);
    return id;
  }
  function slug(text) {
    var s = String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^[^a-z]+/, '').slice(0, 32).replace(/-+$/, '');
    return s || 'column';
  }
  function fmtTime(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso || '';
    try { return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso; }
  }
  function announce(msg) { var el = $('.bd-live'); if (el) { el.textContent = ''; setTimeout(function () { el.textContent = msg; }, 30); } }

  // ---- state ----------------------------------------------------------------------- //
  var S = {
    board: clone(seed.board), base: clone(seed.board), etag: seed.etag, baseEtag: seed.etag,
    mode: 'probing',          // probing | served | local
    why: '',                  // local mode: file or http
    save: 'saved',            // saved | dirty | saving | error
    msg: '', rev: 0, retries: 0,
    f: { q: '', pkg: '', label: '', owner: '' },
    panel: null,              // { kind: 'card', id, tab, prevTitle } | { kind: 'columns', confirm }
    composer: null, grab: null, newId: null, flash: null, storageOk: true, merged: false
  };
  var saveTimer = null, retryTimer = null, snackTimer = null, lastDragEnd = 0;

  function colIndex(id) { for (var i = 0; i < S.board.columns.length; i++) if (S.board.columns[i].id === id) return i; return -1; }
  function colById(id) { var i = colIndex(id); return i < 0 ? null : S.board.columns[i]; }
  function cardById(id) { for (var i = 0; i < S.board.cards.length; i++) if (S.board.cards[i].id === id) return S.board.cards[i]; return null; }
  function cardsOf(colId) {
    return S.board.cards.filter(function (c) { return c.column === colId; }).sort(function (a, b) { return a.order - b.order; });
  }
  function normalizeOrders() {
    var b = S.board, first = b.columns[0].id;
    b.cards.forEach(function (c) { if (colIndex(c.column) < 0) c.column = first; });
    b.cards.sort(function (x, y) { return colIndex(x.column) - colIndex(y.column) || x.order - y.order || (x.id < y.id ? -1 : 1); });
    var n = {};
    b.cards.forEach(function (c) { n[c.column] = (n[c.column] || 0) + 1; c.order = n[c.column]; });
  }

  // ---- filters ---------------------------------------------------------------------- //
  function filtering() { var f = S.f; return !!(f.q || f.pkg || f.label || f.owner); }
  function passes(c) {
    var f = S.f;
    if (f.pkg && (c.package || '') !== f.pkg) return false;
    if (f.label && (c.labels || []).indexOf(f.label) < 0) return false;
    if (f.owner && c.owner !== f.owner) return false;
    if (f.q) {
      var hay = [c.title, c.id, c.package, c.description, c.owner, c.branch, c.sha, (c.labels || []).join(' ')].join(' ').toLowerCase();
      var toks = f.q.toLowerCase().split(/\s+/).filter(Boolean);
      for (var i = 0; i < toks.length; i++) if (hay.indexOf(toks[i]) < 0) return false;
    }
    return true;
  }

  // ---- markdown preview (small and safe: everything is escaped first) ------------------ //
  function safeUrl(u) { return /^https?:\/\//i.test(u) || !/^[a-z][a-z0-9+.-]*:/i.test(u); }
  function inl(s) {
    var t = esc(s);
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
    t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, a, u) { return safeUrl(u) ? '<a href="' + u + '" target="_blank" rel="noopener">' + a + '</a>' : m; });
    return t;
  }
  function mdHtml(text) {
    var out = '', list = false, para = [];
    function flush() { if (para.length) { out += '<p>' + inl(para.join(' ')) + '</p>'; para = []; } }
    String(text || '').split('\n').forEach(function (ln) {
      var m = /^\s*[-*]\s+(.*)$/.exec(ln);
      if (m) { flush(); if (!list) { out += '<ul>'; list = true; } out += '<li>' + inl(m[1]) + '</li>'; }
      else if (!ln.trim()) { flush(); if (list) { out += '</ul>'; list = false; } }
      else { if (list) { out += '</ul>'; list = false; } para.push(ln.trim()); }
    });
    flush();
    if (list) out += '</ul>';
    return out || '<p class="bd-hint">Nothing to preview.</p>';
  }
  function plain(text) { return String(text || '').replace(/`|\*\*|\*|^\s*[-*]\s+/gm, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/\s+/g, ' ').trim(); }

  // ---- canonical text form (mirrors docs/board/board.py) ------------------------------- //
  var CARD_KEYS = ['id', 'title', 'package', 'column', 'order', 'owner', 'labels', 'branch', 'sha', 'links', 'created', 'updated', 'description', 'history'];
  var ARCH_KEYS = CARD_KEYS.slice(0, 12).concat(['archived_at'], CARD_KEYS.slice(12));
  var OPTIONAL = { package: 1, branch: 1, sha: 1, description: 1 };
  function cleanDescription(v) {
    var lines = String(v == null ? '' : v).replace(/\r\n?/g, '\n').split('\n').map(function (l) { return l.replace(/\s+$/, ''); });
    while (lines.length && !lines[0]) lines.shift();
    while (lines.length && !lines[lines.length - 1]) lines.pop();
    return lines.join('\n');
  }
  function canonCard(c, keys) {
    var o = {}, src = clone(c);
    ['title', 'package', 'branch', 'sha', 'column', 'owner'].forEach(function (k) { if (typeof src[k] === 'string') src[k] = src[k].trim(); });
    if (typeof src.sha === 'string') src.sha = src.sha.toLowerCase();
    src.description = cleanDescription(src.description);
    var seen = {};
    src.labels = (src.labels || []).map(function (l) { return String(l).trim().toLowerCase(); }).filter(function (l) { if (!l || seen[l]) return false; seen[l] = 1; return true; });
    src.links = (src.links || []).filter(function (l) { return l && String(l.url || '').trim(); }).map(function (l) {
      var x = { url: String(l.url).trim() };
      if (l.title && String(l.title).trim()) x.title = String(l.title).trim();
      return x;
    });
    src.history = (src.history || []).slice(-HISTORY_KEEP);
    keys.forEach(function (k) {
      var v = src[k];
      if (OPTIONAL[k] && !v) return;
      if (v === undefined || v === null || v === '') return;
      o[k] = v;
    });
    if (!o.labels) o.labels = [];
    if (!o.links) o.links = [];
    if (!o.history) o.history = [];
    return o;
  }
  function canonBoard(b) {
    var cols = b.columns.map(function (c) { return { id: c.id, title: c.title, status: c.status }; });
    var idx = {};
    cols.forEach(function (c, i) { idx[c.id] = i; });
    var cards = clone(b.cards).sort(function (x, y) { return idx[x.column] - idx[y.column] || x.order - y.order || (x.id < y.id ? -1 : 1); });
    var n = {};
    cards.forEach(function (c) { n[c.column] = (n[c.column] || 0) + 1; c.order = n[c.column]; });
    var arch = clone(b.archived || []).sort(function (x, y) { return (x.archived_at < y.archived_at ? -1 : x.archived_at > y.archived_at ? 1 : 0) || (x.id < y.id ? -1 : 1); });
    return {
      version: b.version, columns: cols,
      cards: cards.map(function (c) { return canonCard(c, CARD_KEYS); }),
      archived: arch.map(function (c) { return canonCard(c, ARCH_KEYS); })
    };
  }
  var PLAIN = /^[A-Za-z][A-Za-z0-9_.\/-]{0,79}$/;
  var RESERVED = { 'true': 1, 'false': 1, 'null': 1, 'yes': 1, 'no': 1, 'on': 1, 'off': 1, 'y': 1, 'n': 1 };
  function q(v) { return JSON.stringify(String(v)).replace(/\u0085/g, '\\u0085').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029'); }
  function sc(v) {
    if (typeof v === 'number') return String(v);
    v = String(v);
    return PLAIN.test(v) && !RESERVED[v.toLowerCase()] ? v : q(v);
  }
  function textLines(key, v, indent) {
    var block = v.indexOf('\n') >= 0 && v.indexOf('\t') < 0 && !/^\s/.test(v) && v.split('\n').every(function (l) { return l === l.replace(/\s+$/, ''); });
    if (!block) return [indent + key + ': ' + q(v)];
    return [indent + key + ': |-'].concat(v.split('\n').map(function (l) { return l ? indent + '  ' + l : ''; }));
  }
  function cardLines(c) {
    var lines = [], first = true;
    ARCH_KEYS.forEach(function (k) {
      var v = c[k];
      if (v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length)) return;
      var lead = first ? '  - ' : '    ';
      first = false;
      if (k === 'labels') lines.push(lead + 'labels: [' + v.map(sc).join(', ') + ']');
      else if (k === 'links') {
        lines.push(lead + 'links:');
        v.forEach(function (l) {
          var parts = [];
          if (l.title) parts.push('title: ' + q(l.title));
          if (l.url) parts.push('url: ' + sc(l.url));
          lines.push('      - ' + parts[0]);
          parts.slice(1).forEach(function (p) { lines.push('        ' + p); });
        });
      } else if (k === 'history') {
        lines.push(lead + 'history:');
        v.forEach(function (ev) {
          var parts = [];
          ['at', 'event', 'from', 'to', 'by'].forEach(function (f) { if (ev[f]) parts.push(f + ': ' + (f === 'at' ? q(ev[f]) : sc(ev[f]))); });
          lines.push('      - ' + parts[0]);
          parts.slice(1).forEach(function (p) { lines.push('        ' + p); });
        });
      } else if (k === 'description') lines = lines.concat(textLines(k, v, '    '));
      else if (k === 'title' || k === 'created' || k === 'updated' || k === 'archived_at') lines.push(lead + k + ': ' + q(v));
      else lines.push(lead + k + ': ' + sc(v));
    });
    return lines;
  }
  function toYaml(b) {
    var out = ['version: ' + b.version, 'columns:'];
    b.columns.forEach(function (c) { out.push('  - id: ' + sc(c.id), '    title: ' + q(c.title), '    status: ' + sc(c.status)); });
    ['cards', 'archived'].forEach(function (part) {
      if (!b[part].length) { out.push(part + ': []'); return; }
      out.push(part + ':');
      b[part].forEach(function (c) { out = out.concat(cardLines(c)); });
    });
    return out.join('\n') + '\n';
  }
  function contentOf(c) {
    var o = {};
    ['title', 'package', 'branch', 'sha', 'description', 'column', 'owner'].forEach(function (k) { o[k] = (c[k] || '').toString().trim(); });
    o.labels = c.labels || [];
    o.links = (c.links || []).map(function (l) { return { title: l.title || '', url: l.url || '' }; });
    return JSON.stringify(o);
  }
  // Same rules as board.apply_changes: history, created/updated and the archive come from here.
  function applyChanges(old, neu, by) {
    var now = nowIso(), out = clone(neu), oc = {}, oa = {}, present = {};
    old.cards.forEach(function (c) { oc[c.id] = c; });
    old.archived.forEach(function (c) { oa[c.id] = c; });
    out.cards.concat(out.archived).forEach(function (c) { present[c.id] = true; });
    Object.keys(oa).concat(Object.keys(oc)).forEach(function (id) {
      if (present[id]) return;
      var prev = oc[id] || oa[id], gone = clone(prev);
      if (oc[id]) { gone.archived_at = now; gone.history = (gone.history || []).concat([{ at: now, event: 'archived', by: by }]); }
      else gone.archived_at = prev.archived_at || now;
      out.archived.push(gone);
    });
    ['cards', 'archived'].forEach(function (part) {
      out[part].forEach(function (card) {
        var prev = oc[card.id] || oa[card.id];
        if (!prev) {
          card.created = card.updated = now;
          card.history = [{ at: now, event: 'created', to: card.column, by: by }];
          if (part === 'archived') { card.archived_at = now; card.history.push({ at: now, event: 'archived', by: by }); }
          return;
        }
        var history = (prev.history || []).slice(), wasArch = !!oa[card.id];
        card.created = prev.created; card.updated = prev.updated;
        if (part === 'cards' && wasArch) { history.push({ at: now, event: 'restored', to: card.column, by: by }); card.updated = now; }
        else if (part === 'cards' && prev.column !== card.column) { history.push({ at: now, event: 'moved', from: prev.column, to: card.column, by: by }); card.updated = now; }
        else if (part === 'cards' && contentOf(prev) !== contentOf(card)) card.updated = now;
        else if (part === 'archived' && !wasArch) { history.push({ at: now, event: 'archived', by: by }); card.updated = now; }
        else if (part === 'archived' && contentOf(prev) !== contentOf(card)) card.updated = now;
        card.history = history;
        if (part === 'archived') card.archived_at = wasArch ? prev.archived_at : now;
      });
    });
    out = canonBoard(out);
    out.version = old.version;
    var body = function (b) { return toYaml(Object.assign({}, b, { version: 0 })); };
    if (body(out) !== body(canonBoard(old))) out.version = old.version + 1;
    return out;
  }

  // ---- merging a concurrent edit (base = what I loaded, mine, theirs = the file now) ----- //
  function mergeBoards(base, mine, theirs) {
    function index(b) {
      var m = {};
      b.cards.forEach(function (c) { m[c.id] = { c: c, arch: false }; });
      (b.archived || []).forEach(function (c) { m[c.id] = { c: c, arch: true }; });
      return m;
    }
    function seqs(b) {
      var m = {};
      b.columns.forEach(function (c) { m[c.id] = []; });
      b.cards.slice().sort(function (x, y) { return x.order - y.order; }).forEach(function (c) { (m[c.column] = m[c.column] || []).push(c.id); });
      return m;
    }
    function same(x, y) {
      if (!x || !y) return !x && !y;
      return x.arch === y.arch && contentOf(x.c) === contentOf(y.c);
    }
    var B = index(base), M = index(mine), T = index(theirs), sb = seqs(base), sm = seqs(mine), st = seqs(theirs);
    var cols = JSON.stringify(mine.columns) !== JSON.stringify(base.columns) ? clone(mine.columns) : clone(theirs.columns);
    var res = { version: theirs.version, columns: cols, cards: [], archived: [] };
    var known = {};
    cols.forEach(function (c) { known[c.id] = true; });
    var ids = {};
    [B, M, T].forEach(function (x) { Object.keys(x).forEach(function (id) { ids[id] = true; }); });
    Object.keys(ids).forEach(function (id) {
      var b = B[id], m = M[id], t = T[id];
      var pick = !same(b, m) ? m : t;
      if (!pick) return;
      var card = clone(pick.c);
      if (!known[card.column]) card.column = cols[0].id;
      var col = pick.c.column, seq = (m && sm[col] && JSON.stringify(sm[col]) !== JSON.stringify(sb[col] || [])) ? sm[col] : null;
      var useMine = seq && m && m.c.column === col;
      var src = useMine ? sm[col] : (t && t.c.column === col ? st[col] : sm[col]);
      var i = src ? src.indexOf(id) : -1;
      card.order = (i < 0 ? 0.999 : (i + 0.5) / Math.max(1, src.length)) * 1000;
      if (pick.arch) { if (!card.archived_at) card.archived_at = nowIso(); res.archived.push(card); } else res.cards.push(card);
    });
    return res;
  }

  // ---- saving ------------------------------------------------------------------------------ //
  function touch() {
    S.rev++;
    S.save = 'dirty'; S.msg = '';
    paintStatus();
    schedule();
  }
  function schedule() {
    clearTimeout(saveTimer);
    if (S.mode === 'served') saveTimer = setTimeout(doSave, SAVE_DELAY);
    else if (S.mode === 'local') localPersist();
  }
  function blankTitle() { return S.board.cards.some(function (c) { return !String(c.title || '').trim(); }); }
  function doSave() {
    clearTimeout(saveTimer); clearTimeout(retryTimer);
    if (S.mode !== 'served' || S.save === 'saving') return;
    if (blankTitle()) { S.save = 'dirty'; S.msg = 'Give the new card a title to save.'; paintStatus(); return; }
    var sent = S.rev;
    S.save = 'saving'; paintStatus();
    var body = JSON.stringify({ board: S.board });
    fetch('/api/board', { method: 'PUT', headers: { 'Content-Type': 'application/json', 'If-Match': '"' + S.etag + '"' }, body: body, cache: 'no-store' })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        var j = res.body || {};
        if (res.status === 200 && j.board) {
          S.base = clone(j.board); S.etag = j.etag; S.retries = 0;
          if (S.rev === sent) { S.board = clone(j.board); S.save = 'saved'; S.msg = j.committed ? 'Committed ' + j.commit : ''; render(); }
          else { S.save = 'dirty'; paintStatus(); schedule(); }
        } else if (res.status === 409 && j.board && S.retries < 3) {
          S.retries++;
          S.board = mergeBoards(S.base, S.board, j.board);
          S.base = clone(j.board); S.etag = j.etag; S.merged = true;
          normalizeOrders(); render(); toast('The board changed in the repo. Your edits were merged with it.');
          S.save = 'dirty';
          doSave();
        } else {
          S.save = 'error';
          S.msg = (j.errors && j.errors[0]) || (res.status === 409 ? 'The board keeps changing elsewhere. Reload the page.' : 'The server refused the save (' + res.status + ').');
          paintStatus();
        }
      })
      .catch(function () {
        S.save = 'error'; S.msg = 'Cannot reach the local server. Changes are not saved yet.';
        paintStatus();
        retryTimer = setTimeout(doSave, 8000);
      });
  }
  function localPersist() {
    var same = JSON.stringify(canonBoard(S.board)) === JSON.stringify(canonBoard(S.base));
    if (same) { store.del(KEY); S.storageOk = true; return; }
    S.storageOk = store.set(KEY, JSON.stringify({ baseEtag: S.baseEtag, base: S.base, board: S.board, at: Date.now() }));
    paintStatus();
  }
  function poll() {
    if (S.mode !== 'served' || S.save !== 'saved' || S.panel || document.hidden || document.body.classList.contains('bd-dragging')) return;
    fetch('/api/board', { cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.board || j.etag === S.etag || S.save !== 'saved' || S.panel) return;
        S.board = clone(j.board); S.base = clone(j.board); S.etag = j.etag;
        render(); toast('The board was updated in the repo.');
      }).catch(function () { /* the server may have stopped: nothing to do */ });
  }

  // ---- mutations ----------------------------------------------------------------------------- //
  function changed() { normalizeOrders(); render(); touch(); }
  function moveCard(id, colId, beforeId) {
    var c = cardById(id);
    if (!c || colIndex(colId) < 0) return;
    var peers = cardsOf(colId).filter(function (x) { return x.id !== id; }), idx = -1;
    if (beforeId) peers.some(function (x, i) { if (x.id === beforeId) { idx = i; return true; } return false; });
    if (idx < 0) idx = peers.length;
    peers.splice(idx, 0, c);
    c.column = colId;
    peers.forEach(function (x, i) { x.order = i + 1; });
  }
  function addCard(colId, title, extra) {
    var taken = {};
    S.board.cards.concat(S.board.archived).forEach(function (c) { taken[c.id] = 1; });
    var now = nowIso();
    var card = Object.assign({ id: newId(taken), title: title, column: colId, order: 1e6, owner: 'owner', labels: [], links: [], created: now, updated: now, history: [] }, extra || {});
    S.board.cards.push(card);
    S.flash = card.id;
    return card;
  }
  function deleteCard(id) {
    var c = cardById(id);
    if (!c) return;
    var pos = c.order, idx = S.board.cards.indexOf(c);
    S.board.cards.splice(idx, 1);
    // A card the repo has never seen is simply dropped; one it knows moves into `archived`.
    var known = S.base.cards.concat(S.base.archived).some(function (x) { return x.id === id; });
    if (known) { c.archived_at = nowIso(); S.board.archived.push(c); }
    if (S.panel && S.panel.id === id) closePanel(true);
    changed();
    snack('Deleted “' + (c.title || 'card') + '”.', 'Undo', function () {
      var k = S.board.archived.indexOf(c);
      if (k >= 0) S.board.archived.splice(k, 1);
      delete c.archived_at;
      c.order = pos - 0.5;
      S.board.cards.push(c);
      S.flash = c.id;
      changed();
      announce('Restored ' + c.title);
    });
    announce('Deleted ' + (c.title || 'card') + '. Undo is available.');
  }

  // ---- toasts ------------------------------------------------------------------------------------ //
  function toast(msg) {
    var t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { t.hidden = true; }, 3200);
  }
  function snack(msg, label, fn) {
    var el = $('.bd-snack');
    el.innerHTML = '<span></span><button type="button">' + esc(label) + '</button>';
    el.firstChild.textContent = msg;
    el.hidden = false;
    $('button', el).onclick = function () { el.hidden = true; clearTimeout(snackTimer); fn(); };
    clearTimeout(snackTimer);
    snackTimer = setTimeout(function () { el.hidden = true; }, 9000);
  }

  // ---- skeleton and rendering ------------------------------------------------------------------------- //
  function skeleton() {
    root.innerHTML =
      '<div class="bd-bar">' +
      '<div class="bd-filters" role="search"><input class="bd-search" type="search" placeholder="Search cards" aria-label="Search cards" autocomplete="off">' +
      '<select class="bd-select" data-f="pkg" aria-label="Filter by package"></select>' +
      '<select class="bd-select" data-f="label" aria-label="Filter by label"></select>' +
      '<select class="bd-select" data-f="owner" aria-label="Filter by owner"></select>' +
      '<button type="button" class="btn small ghost" data-bd="clear" hidden>Clear filters</button></div>' +
      '<div class="bd-actions"><span class="bd-pill" role="status" aria-live="polite"><i></i><span class="t"></span></span>' +
      '<button type="button" class="btn small" data-bd="retry" hidden>Retry</button>' +
      '<button type="button" class="btn small" data-bd="columns">Columns</button>' +
      '<button type="button" class="btn small primary" data-bd="add">Add card</button></div>' +
      '</div>' +
      '<div class="bd-note" hidden></div>' +
      '<div class="bd-cols"></div>' +
      '<div class="bd-live sr-only" aria-live="assertive"></div>' +
      '<div class="bd-scrim" hidden></div>' +
      '<aside class="bd-panel" hidden></aside>' +
      '<div class="bd-snack" role="status" hidden></div>';
  }
  function fillSelect(sel, label, values, current) {
    var html = '<option value="">' + esc(label) + '</option>' + values.map(function (v) { return '<option value="' + esc(v) + '"' + (v === current ? ' selected' : '') + '>' + esc(v) + '</option>'; }).join('');
    if (sel.getAttribute('data-h') !== html) { sel.innerHTML = html; sel.setAttribute('data-h', html); }
    sel.value = current;
  }
  function renderBar() {
    var pk = {}, lb = {};
    S.board.cards.forEach(function (c) { if (c.package) pk[c.package] = 1; (c.labels || []).forEach(function (l) { lb[l] = 1; }); });
    fillSelect($('[data-f="pkg"]'), 'All packages', Object.keys(pk).sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; }), S.f.pkg);
    fillSelect($('[data-f="label"]'), 'All labels', Object.keys(lb).sort(), S.f.label);
    fillSelect($('[data-f="owner"]'), 'All owners', OWNERS, S.f.owner);
    $('[data-bd="clear"]').hidden = !filtering();
    paintStatus();
  }
  function paintStatus() {
    var pill = $('.bd-pill'), t = $('.t', pill), note = $('.bd-note'), retry = $('[data-bd="retry"]');
    var cls = 'busy', text = 'Connecting...';
    if (S.mode === 'served') {
      if (S.save === 'saved') { cls = 'ok'; text = 'Saved to the repo'; }
      else if (S.save === 'saving') { cls = 'busy'; text = 'Saving...'; }
      else if (S.save === 'error') { cls = 'err'; text = 'Not saved'; }
      else { cls = 'warn'; text = 'Unsaved changes'; }
    } else if (S.mode === 'local') { cls = 'warn'; text = 'Not saved to the repo'; }
    pill.className = 'bd-pill ' + cls;
    t.textContent = text;
    pill.title = S.msg || '';
    retry.hidden = !(S.mode === 'served' && S.save === 'error');
    var html = '';
    if (S.mode === 'local') {
      html = '<b>Not saved to the repo.</b><span>' + (S.why === 'file'
        ? 'This page was opened as a file, so changes stay in this browser.'
        : 'This server cannot save the board.') + ' To save into the repo run <code>python docs/site/studio.py start</code> and open the link it prints.</span>' +
        (S.storageOk ? '' : '<span><b>This browser would not keep your changes.</b> Download before you close the page.</span>') +
        '<span class="sp"></span><button type="button" class="btn small primary" data-bd="download">Download board.yaml</button>' +
        '<button type="button" class="btn small ghost" data-bd="reset">Discard my changes</button>';
      note.className = 'bd-note';
    } else if (S.mode === 'served' && (S.save === 'error' || (S.save === 'dirty' && S.msg))) {
      html = '<b>' + (S.save === 'error' ? 'Not saved.' : 'Not saved yet.') + '</b><span>' + esc(S.msg) + '</span>';
      note.className = 'bd-note';
    }
    if (note.innerHTML !== html) note.innerHTML = html;
    note.hidden = !html;
  }
  function cardHtml(c, col) {
    var labels = (c.labels || []).map(function (l) { return '<span class="bc-label">' + esc(l) + '</span>'; }).join('');
    var foot = [];
    if (c.branch) foot.push('<code title="Branch">' + esc(c.branch) + '</code>');
    if (c.sha) foot.push('<code title="Commit">' + esc(c.sha) + '</code>');
    if ((c.links || []).length) foot.push('<span>' + c.links.length + (c.links.length === 1 ? ' link' : ' links') + '</span>');
    return '<article class="bcard' + (S.flash === c.id ? ' is-new' : '') + (S.grab && S.grab.id === c.id ? ' is-grabbed' : '') + '" tabindex="0" data-id="' + esc(c.id) + '" ' +
      'aria-label="' + esc((c.title || 'Untitled') + '. ' + (col ? col.title : '') + '. Enter to edit, Space to move.') + '">' +
      '<div class="bc-top">' + (c.package ? '<span class="bc-pkg" title="Package">' + esc(c.package) + '</span>' : '<span class="bc-id">' + esc(c.id) + '</span>') +
      '<span class="bc-own own-' + esc(c.owner) + '" title="Owner">' + esc(c.owner) + '</span></div>' +
      '<div class="bc-title">' + esc(c.title || 'Untitled') + '</div>' +
      (c.description ? '<p class="bc-desc">' + esc(plain(c.description)) + '</p>' : '') +
      (labels ? '<div class="bc-labels">' + labels + '</div>' : '') +
      (foot.length ? '<div class="bc-foot">' + foot.join('') + '</div>' : '') + '</article>';
  }
  function renderCols() {
    var host = $('.bd-cols'), keep = document.activeElement, keepId = keep && keep.closest && keep.closest('.bcard') && keep.classList.contains('bcard') ? keep.getAttribute('data-id') : null;
    var composerVal = '';
    var oldInput = $('.bd-compose input');
    if (oldInput) composerVal = oldInput.value;
    var scroll = host.scrollLeft;
    host.innerHTML = S.board.columns.map(function (col) {
      var all = cardsOf(col.id), vis = all.filter(passes), f = filtering();
      var add = S.composer === col.id
        ? '<form class="bd-compose" data-col="' + esc(col.id) + '"><input class="bd-in" type="text" maxlength="200" placeholder="Card title" aria-label="Card title" required>' +
          '<div class="row"><button class="btn small primary" type="submit">Add</button><button class="btn small ghost" type="button" data-bd="compose-cancel">Cancel</button></div></form>'
        : '<button type="button" class="bd-add" data-bd="col-add" data-col="' + esc(col.id) + '">+ Add card</button>';
      return '<section class="bd-col ' + esc(col.status) + '" data-col="' + esc(col.id) + '" aria-label="' + esc(col.title) + ', ' + all.length + ' cards">' +
        '<header class="bd-col-head"><h3 class="bd-col-title" title="' + esc(col.title) + '">' + esc(col.title) + '</h3>' +
        '<span class="bd-count" title="' + all.length + ' cards">' + (f ? vis.length + '/' + all.length : all.length) + '</span>' +
        '<button type="button" class="bd-icon" data-bd="col-add" data-col="' + esc(col.id) + '" aria-label="Add a card to ' + esc(col.title) + '" title="Add a card">+</button></header>' +
        '<div class="bd-list" data-col="' + esc(col.id) + '">' + vis.map(function (c) { return cardHtml(c, col); }).join('') + '</div>' +
        '<div class="bd-empty">' + (all.length ? 'No cards match the filters' : 'No cards yet') + '</div>' + add + '</section>';
    }).join('');
    host.scrollLeft = scroll;
    var input = $('.bd-compose input');
    if (input) { input.value = composerVal; input.focus(); }
    else if (keepId) { var el = $('.bcard[data-id="' + keepId + '"]'); if (el) el.focus({ preventScroll: true }); }
    S.flash = null;
  }
  function render() { renderBar(); renderCols(); }

  // ---- side panel ---------------------------------------------------------------------------------- //
  function selectHtml(field, values, current, labelFor) {
    return '<select class="bd-in" data-f="' + field + '">' + values.map(function (v) {
      return '<option value="' + esc(v) + '"' + (v === current ? ' selected' : '') + '>' + esc(labelFor ? labelFor(v) : v) + '</option>';
    }).join('') + '</select>';
  }
  function chipsHtml(card) {
    return (card.labels || []).map(function (l, i) { return '<span class="bd-chip">' + esc(l) + '<button type="button" data-bd="label-del" data-i="' + i + '" aria-label="Remove label ' + esc(l) + '">&times;</button></span>'; }).join('') +
      '<input type="text" data-bd-label placeholder="' + ((card.labels || []).length ? '' : 'Add a label') + '" aria-label="Add a label" maxlength="30">';
  }
  function linksHtml(card) {
    return (card.links || []).map(function (l, i) {
      return '<div class="bd-link"><input class="bd-in" data-link="title" data-i="' + i + '" value="' + esc(l.title || '') + '" placeholder="Title" aria-label="Link title" maxlength="80">' +
        '<input class="bd-in" data-link="url" data-i="' + i + '" value="' + esc(l.url || '') + '" placeholder="https://... or docs/plans/x.md" aria-label="Link address" maxlength="500">' +
        '<button type="button" class="bd-icon" data-bd="link-del" data-i="' + i + '" aria-label="Remove link">&times;</button></div>';
    }).join('') + '<button type="button" class="btn small" data-bd="link-add">Add link</button>';
  }
  function historyHtml(card) {
    var h = (card.history || []).slice().reverse();
    if (!h.length) return '<p class="bd-hint">No history yet.</p>';
    return '<ul class="bd-hist">' + h.map(function (ev) {
      var what = ev.event === 'moved' ? 'Moved ' + esc(ev.from || '') + ' to ' + esc(ev.to || '') : ev.event === 'created' ? 'Created in ' + esc(ev.to || '') : ev.event === 'restored' ? 'Restored to ' + esc(ev.to || '') : 'Deleted';
      return '<li><time>' + esc(fmtTime(ev.at)) + '</time>' + what + ' <span class="bd-hint">by ' + esc(ev.by || '') + '</span></li>';
    }).join('') + '</ul>';
  }
  function panelCardHtml(c) {
    var pk = {};
    S.board.cards.forEach(function (x) { if (x.package) pk[x.package] = 1; });
    var colOpts = S.board.columns.map(function (x) { return x.id; });
    return '<div class="bd-panel-head"><h3>' + (S.newId === c.id ? 'New card' : 'Edit card') + '</h3><span class="bc-id">' + esc(c.id) + '</span>' +
      '<button type="button" class="bd-icon" data-bd="close" aria-label="Close">&times;</button></div>' +
      '<div class="bd-panel-body">' +
      '<div class="bd-field"><label for="bd-f-title">Title</label><input id="bd-f-title" class="bd-in" data-f="title" maxlength="200" value="' + esc(c.title) + '" autocomplete="off">' +
      '<span class="bd-hint bad" data-hint="title" hidden>A card needs a title.</span></div>' +
      '<div class="bd-grid2"><div class="bd-field"><label>Column</label>' + selectHtml('column', colOpts, c.column, function (v) { return colById(v).title; }) + '</div>' +
      '<div class="bd-field"><label>Owner</label>' + selectHtml('owner', OWNERS, c.owner) + '</div></div>' +
      '<div class="bd-grid2"><div class="bd-field"><label for="bd-f-package">Package</label><input id="bd-f-package" class="bd-in" data-f="package" list="bd-packages" maxlength="40" value="' + esc(c.package || '') + '" placeholder="e.g. ORCH" autocomplete="off">' +
      '<datalist id="bd-packages">' + Object.keys(pk).sort().map(function (p) { return '<option value="' + esc(p) + '">'; }).join('') + '</datalist></div>' +
      '<div class="bd-field"><label for="bd-f-branch">Branch</label><input id="bd-f-branch" class="bd-in" data-f="branch" maxlength="100" value="' + esc(c.branch || '') + '" placeholder="studio/..." autocomplete="off"></div></div>' +
      '<div class="bd-field"><label for="bd-f-sha">Commit</label><input id="bd-f-sha" class="bd-in" data-f="sha" maxlength="12" value="' + esc(c.sha || '') + '" placeholder="short hash" autocomplete="off"><span class="bd-hint bad" data-hint="sha" hidden>Use the short hex form (4 to 12 characters).</span></div>' +
      '<div class="bd-field"><span class="lab">Labels</span><div class="bd-chips" data-chips>' + chipsHtml(c) + '</div></div>' +
      '<div class="bd-field"><span class="lab">Description</span>' +
      '<div class="bd-tabs" role="group" aria-label="Description view"><button type="button" data-bd="tab" data-tab="write" aria-pressed="true">Write</button><button type="button" data-bd="tab" data-tab="preview" aria-pressed="false">Preview</button></div>' +
      '<textarea class="bd-in" data-f="description" maxlength="20000" placeholder="Markdown: lists, **bold**, `code`, [links](https://...)" aria-label="Description">' + esc(c.description || '') + '</textarea>' +
      '<div class="bd-preview" data-preview hidden></div></div>' +
      '<div class="bd-field"><span class="lab">Links</span><div data-links>' + linksHtml(c) + '</div></div>' +
      '<details><summary>History (' + (c.history || []).length + ')</summary>' + historyHtml(c) + '<p class="bd-hint">Created ' + esc(fmtTime(c.created)) + '. Updated ' + esc(fmtTime(c.updated)) + '.</p></details>' +
      '</div>' +
      '<div class="bd-panel-foot"><button type="button" class="btn danger" data-bd="delete">Delete card</button><span class="sp"></span><button type="button" class="btn primary" data-bd="close">Done</button></div>';
  }
  function panelColumnsHtml() {
    var cols = S.board.columns, confirm = S.panel.confirm;
    return '<div class="bd-panel-head"><h3>Columns</h3><button type="button" class="bd-icon" data-bd="close" aria-label="Close">&times;</button></div><div class="bd-panel-body">' +
      '<p class="bd-hint">Rename, reorder or add columns. The status decides how a column counts in the build progress bar on the home page.</p><div>' +
      cols.map(function (c, i) {
        var n = cardsOf(c.id).length;
        return '<div class="bd-cols-row" data-col="' + esc(c.id) + '">' +
          '<span><button type="button" class="bd-icon" data-bd="col-up" data-col="' + esc(c.id) + '" aria-label="Move ' + esc(c.title) + ' left"' + (i === 0 ? ' disabled' : '') + '>&larr;</button>' +
          '<button type="button" class="bd-icon" data-bd="col-down" data-col="' + esc(c.id) + '" aria-label="Move ' + esc(c.title) + ' right"' + (i === cols.length - 1 ? ' disabled' : '') + '>&rarr;</button></span>' +
          '<input class="bd-in" data-colf="title" data-col="' + esc(c.id) + '" value="' + esc(c.title) + '" maxlength="40" aria-label="Column name">' +
          '<select class="bd-in" data-colf="status" data-col="' + esc(c.id) + '" aria-label="Status of ' + esc(c.title) + '">' +
          STATUSES.map(function (s) { return '<option value="' + s + '"' + (s === c.status ? ' selected' : '') + '>' + s + '</option>'; }).join('') + '</select>' +
          '<span class="n" title="Cards">' + n + '</span>' +
          (confirm === c.id
            ? '<button type="button" class="btn small danger-solid" data-bd="col-del-yes" data-col="' + esc(c.id) + '">Confirm</button>'
            : '<button type="button" class="bd-icon" data-bd="col-del" data-col="' + esc(c.id) + '" aria-label="Delete ' + esc(c.title) + '"' + (cols.length < 2 ? ' disabled' : '') + '>&times;</button>') +
          '</div>' + (confirm === c.id ? '<p class="bd-hint bad">' + (n ? n + ' card' + (n === 1 ? '' : 's') + ' move to ' + esc(cols[i ? i - 1 : 1].title) + '. ' : '') + 'Press Confirm to delete the column.</p>' : '');
      }).join('') + '</div>' +
      '<form class="bd-cols-add" data-bd-colform><div class="bd-field"><label for="bd-newcol">New column</label><div class="row" style="display:flex;gap:6px"><input id="bd-newcol" class="bd-in" maxlength="40" placeholder="Column name" autocomplete="off"><button class="btn primary" type="submit">Add column</button></div></div></form></div>' +
      '<div class="bd-panel-foot"><span class="sp"></span><button type="button" class="btn primary" data-bd="close">Done</button></div>';
  }
  function showPanel(focusSel) {
    var p = $('.bd-panel'), scrim = $('.bd-scrim');
    p.innerHTML = S.panel.kind === 'card' ? panelCardHtml(cardById(S.panel.id)) : panelColumnsHtml();
    p.hidden = false; scrim.hidden = false;
    p.setAttribute('role', 'dialog'); p.setAttribute('aria-label', S.panel.kind === 'card' ? 'Edit card' : 'Columns');
    var f = focusSel && $(focusSel, p);
    if (f) { f.focus(); if (f.select && f.tagName === 'INPUT' && S.newId) f.select(); }
  }
  function openCard(id, focusSel) {
    var c = cardById(id);
    if (!c) return;
    S.panel = { kind: 'card', id: id, tab: 'write', prevTitle: c.title };
    showPanel(focusSel || '[data-f="title"]');
  }
  function openColumns() { S.panel = { kind: 'columns', confirm: null }; showPanel('[data-bd-colform] input'); }
  function closePanel(silent) {
    var p = S.panel;
    if (!p) return;
    S.panel = null;
    var panel = $('.bd-panel');
    panel.hidden = true; panel.innerHTML = ''; $('.bd-scrim').hidden = true;
    if (p.kind === 'card' && !silent) {
      var c = cardById(p.id);
      if (c && !String(c.title || '').trim()) {
        if (S.newId === c.id) { S.board.cards.splice(S.board.cards.indexOf(c), 1); S.newId = null; changed(); return; }
        c.title = p.prevTitle || 'Untitled';
        changed();
      } else { render(); }
      var el = c && $('.bcard[data-id="' + c.id + '"]');
      if (el) el.focus({ preventScroll: true });
    }
    S.newId = null;
    if (S.save === 'dirty' && S.mode === 'served') schedule();
  }
  function refreshChips() { var c = cardById(S.panel.id); $('[data-chips]').innerHTML = chipsHtml(c); var i = $('[data-chips] input'); if (i) i.focus(); }
  function refreshLinks() { var c = cardById(S.panel.id); $('[data-links]').innerHTML = linksHtml(c); }

  function onPanelField(el) {
    var c = S.panel && S.panel.kind === 'card' ? cardById(S.panel.id) : null;
    if (!c) return;
    var f = el.getAttribute('data-f'), v = el.value;
    if (f === 'column') { moveCard(c.id, v, null); normalizeOrders(); renderCols(); touch(); return; }
    if (f === 'owner') c.owner = v;
    else if (f === 'title') { c.title = v; var h = $('[data-hint="title"]'); if (h) h.hidden = !!v.trim(); }
    else if (f === 'sha') { c.sha = v.trim().toLowerCase(); var hs = $('[data-hint="sha"]'); if (hs) hs.hidden = !c.sha || /^[0-9a-f]{4,12}$/.test(c.sha); }
    else c[f] = v;
    renderCols(); touch();
  }
  function onPanelClick(ev) {
    var b = ev.target.closest('[data-bd]');
    if (!b || !S.panel) return;
    var act = b.getAttribute('data-bd'), c = S.panel.kind === 'card' ? cardById(S.panel.id) : null, i = +b.getAttribute('data-i');
    if (act === 'close') closePanel();
    else if (act === 'delete' && c) deleteCard(c.id);
    else if (act === 'label-del' && c) { c.labels.splice(i, 1); refreshChips(); renderCols(); touch(); }
    else if (act === 'link-add' && c) { c.links = c.links || []; c.links.push({ title: '', url: '' }); refreshLinks(); var ins = $$('[data-link="url"]'); if (ins.length) ins[ins.length - 1].focus(); }
    else if (act === 'link-del' && c) { c.links.splice(i, 1); refreshLinks(); renderCols(); touch(); }
    else if (act === 'tab' && c) {
      var prev = b.getAttribute('data-tab') === 'preview', ta = $('textarea[data-f="description"]'), pv = $('[data-preview]');
      $$('.bd-tabs button').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      ta.hidden = prev; pv.hidden = !prev;
      if (prev) pv.innerHTML = mdHtml(c.description);
    }
    else if (act === 'col-up' || act === 'col-down') {
      var from = colIndex(b.getAttribute('data-col')), to = from + (act === 'col-up' ? -1 : 1);
      if (to < 0 || to >= S.board.columns.length) return;
      S.board.columns.splice(to, 0, S.board.columns.splice(from, 1)[0]);
      changed(); showPanel('[data-bd="' + act + '"][data-col="' + b.getAttribute('data-col') + '"]');
    }
    else if (act === 'col-del') { S.panel.confirm = b.getAttribute('data-col'); showPanel('[data-bd="col-del-yes"]'); }
    else if (act === 'col-del-yes') {
      var id = b.getAttribute('data-col'), idx = colIndex(id), target = S.board.columns[idx ? idx - 1 : 1];
      cardsOf(id).forEach(function (card) { moveCard(card.id, target.id, null); });
      S.board.columns.splice(idx, 1);
      S.panel.confirm = null;
      changed(); showPanel('[data-bd-colform] input');
    }
  }

  // ---- toolbar and column events ---------------------------------------------------------------------- //
  root.addEventListener('input', function (ev) {
    var el = ev.target;
    if (el.classList.contains('bd-search')) { S.f.q = el.value.trim(); renderCols(); renderBar(); return; }
    if (el.closest('.bd-panel')) {
      if (el.hasAttribute('data-f')) onPanelField(el);
      else if (el.hasAttribute('data-link')) {
        var c = cardById(S.panel.id), l = c.links[+el.getAttribute('data-i')];
        l[el.getAttribute('data-link')] = el.value;
        renderCols(); touch();
      } else if (el.hasAttribute('data-colf')) {
        var col = colById(el.getAttribute('data-col'));
        if (el.getAttribute('data-colf') === 'title') { if (!el.value.trim()) return; col.title = el.value.trim(); }
        else col.status = el.value;
        renderCols(); touch();
      }
    }
  });
  root.addEventListener('change', function (ev) {
    var el = ev.target, f = el.getAttribute('data-f');
    if (el.classList.contains('bd-select') && f) { S.f[f] = el.value; renderCols(); renderBar(); }
    else if (el.closest('.bd-panel') && el.tagName === 'SELECT' && el.hasAttribute('data-colf')) { /* handled on input */ }
  });
  root.addEventListener('keydown', function (ev) {
    var el = ev.target;
    if (el.hasAttribute && el.hasAttribute('data-bd-label') && (ev.key === 'Enter' || ev.key === ',')) {
      ev.preventDefault();
      var v = el.value.trim().toLowerCase().replace(/,/g, '');
      var c = cardById(S.panel.id);
      if (v && c.labels.indexOf(v) < 0 && c.labels.length < 12) { c.labels.push(v); refreshChips(); renderCols(); touch(); } else el.value = '';
    } else if (el.hasAttribute && el.hasAttribute('data-bd-label') && ev.key === 'Backspace' && !el.value) {
      var c2 = cardById(S.panel.id);
      if (c2.labels.length) { c2.labels.pop(); refreshChips(); renderCols(); touch(); }
    } else if (ev.key === 'Escape' && S.panel && !S.grab) { ev.preventDefault(); closePanel(); }
    else if (ev.key === 'Escape' && el.closest && el.closest('.bd-compose')) { S.composer = null; renderCols(); }
  });
  root.addEventListener('submit', function (ev) {
    var form = ev.target;
    ev.preventDefault();
    if (form.classList.contains('bd-compose')) {
      var t = $('input', form).value.trim();
      if (!t) return;
      var card = addCard(form.getAttribute('data-col'), t);
      S.composer = form.getAttribute('data-col');
      changed();
      announce('Added ' + card.title);
    } else if (form.hasAttribute('data-bd-colform')) {
      var name = $('input', form).value.trim();
      if (!name) return;
      var id = slug(name), n = 2, base = id;
      while (colIndex(id) >= 0) id = base.slice(0, 28) + '-' + n++;
      S.board.columns.push({ id: id, title: name, status: 'planned' });
      changed(); showPanel('[data-bd-colform] input');
    }
  });
  root.addEventListener('click', function (ev) {
    var t = ev.target;
    if (t.closest('.bd-panel')) { onPanelClick(ev); return; }
    if (t.classList.contains('bd-scrim')) { closePanel(); return; }
    var b = t.closest('[data-bd]');
    if (b) {
      var act = b.getAttribute('data-bd');
      if (act === 'clear') { S.f = { q: '', pkg: '', label: '', owner: '' }; $('.bd-search').value = ''; render(); }
      else if (act === 'retry') { S.retries = 0; doSave(); }
      else if (act === 'columns') openColumns();
      else if (act === 'add') {
        var first = S.board.columns[0].id;
        var card = addCard(first, '');
        S.newId = card.id;
        normalizeOrders(); renderCols(); openCard(card.id);
      }
      else if (act === 'col-add') { S.composer = b.getAttribute('data-col'); renderCols(); }
      else if (act === 'compose-cancel') { S.composer = null; renderCols(); }
      else if (act === 'download') download();
      else if (act === 'reset') {
        if (!window.confirm('Discard your changes in this browser and go back to the board built into this page?')) return;
        S.board = clone(seed.board); S.base = clone(seed.board); S.baseEtag = seed.etag; store.del(KEY); S.save = 'saved'; render();
      }
      return;
    }
    var card2 = t.closest('.bcard');
    if (card2 && Date.now() - lastDragEnd > 350 && !S.grab) openCard(card2.getAttribute('data-id'));
  });

  // ---- keyboard: Enter edits, Space picks up, arrows move, Space drops, Escape cancels ---------------------- //
  root.addEventListener('keydown', function (ev) {
    var el = ev.target;
    if (!el.classList || !el.classList.contains('bcard')) return;
    var id = el.getAttribute('data-id'), c = cardById(id);
    if (!c) return;
    if (S.grab && S.grab.id === id) {
      var k = ev.key;
      if (k === 'ArrowLeft' || k === 'ArrowRight' || k === 'ArrowUp' || k === 'ArrowDown') { ev.preventDefault(); keyMove(c, k); }
      else if (k === ' ' || k === 'Enter') { ev.preventDefault(); S.grab = null; announce('Dropped ' + c.title + ' in ' + colById(c.column).title + ', position ' + (cardsOf(c.column).indexOf(c) + 1) + ' of ' + cardsOf(c.column).length + '.'); renderCols(); }
      else if (k === 'Escape') { ev.preventDefault(); moveCard(id, S.grab.col, S.grab.before); S.grab = null; changed(); announce('Move cancelled.'); }
      else if (k === 'Tab') { S.grab = null; renderCols(); }
      return;
    }
    if (ev.key === 'Enter' || ev.key === 'e') { ev.preventDefault(); openCard(id); }
    else if (ev.key === ' ') {
      ev.preventDefault();
      var peers = cardsOf(c.column), i = peers.indexOf(c);
      S.grab = { id: id, col: c.column, before: peers[i + 1] ? peers[i + 1].id : null };
      renderCols();
      announce('Picked up ' + c.title + '. Arrow keys move it between columns and up or down. Space drops it, Escape cancels.');
    }
    else if (ev.key === 'Delete') { ev.preventDefault(); deleteCard(id); }
  });
  function keyMove(c, key) {
    var ci = colIndex(c.column), peers = cardsOf(c.column), i = peers.indexOf(c);
    if (key === 'ArrowLeft' || key === 'ArrowRight') {
      var ni = ci + (key === 'ArrowLeft' ? -1 : 1);
      if (ni < 0 || ni >= S.board.columns.length) return;
      var target = S.board.columns[ni].id, tp = cardsOf(target);
      moveCard(c.id, target, tp[Math.min(i, tp.length)] ? tp[Math.min(i, tp.length)].id : null);
    } else {
      var j = i + (key === 'ArrowUp' ? -1 : 1);
      if (j < 0 || j >= peers.length) return;
      moveCard(c.id, c.column, key === 'ArrowUp' ? peers[j].id : (peers[j + 1] ? peers[j + 1].id : null));
    }
    changed();
    announce('In ' + colById(c.column).title + ', position ' + (cardsOf(c.column).indexOf(c) + 1) + ' of ' + cardsOf(c.column).length + '.');
  }

  // ---- pointer drag and drop (mouse, pen and touch with a long press) ----------------------------------------- //
  var drag = null;
  function colsEl() { return $('.bd-cols'); }
  root.addEventListener('pointerdown', function (ev) {
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    var el = ev.target.closest ? ev.target.closest('.bcard') : null;
    if (!el || ev.target.closest('button, a, input, textarea, select') || S.grab || drag) return;
    drag = { el: el, id: el.getAttribute('data-id'), x: ev.clientX, y: ev.clientY, px: ev.clientX, py: ev.clientY, pid: ev.pointerId, type: ev.pointerType, active: false, timer: null, raf: 0 };
    if (ev.pointerType !== 'mouse') drag.timer = setTimeout(function () { if (drag && !drag.active) startDrag(); }, 380);
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    document.addEventListener('pointercancel', onCancel);
  });
  document.addEventListener('touchmove', function (ev) { if (drag && drag.active) ev.preventDefault(); }, { passive: false });
  function startDrag() {
    var r = drag.el.getBoundingClientRect(), g = drag.el.cloneNode(true);
    drag.active = true; drag.ox = drag.px - r.left; drag.oy = drag.py - r.top;
    g.removeAttribute('tabindex'); g.classList.add('bd-ghost'); g.style.width = r.width + 'px';
    document.body.appendChild(g);
    drag.ghost = g;
    drag.el.classList.add('is-dragging');
    document.body.classList.add('bd-dragging');
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    place(); loop();
  }
  function place() {
    drag.ghost.style.left = (drag.px - drag.ox) + 'px';
    drag.ghost.style.top = (drag.py - drag.oy) + 'px';
    retarget();
  }
  function retarget() {
    var cols = $$('.bd-col'), target = null, best = 1e9;
    cols.forEach(function (c) {
      var r = c.getBoundingClientRect(), d = drag.px < r.left ? r.left - drag.px : drag.px > r.right ? drag.px - r.right : 0;
      if (d < best) { best = d; target = c; }
    });
    cols.forEach(function (c) { c.classList.toggle('drop', c === target); });
    if (!target) return;
    var list = $('.bd-list', target), cards = $$('.bcard', list).filter(function (c) { return c !== drag.el; }), before = null;
    for (var i = 0; i < cards.length; i++) {
      var r2 = cards[i].getBoundingClientRect();
      if (drag.py < r2.top + r2.height / 2) { before = cards[i]; break; }
    }
    if (before) { if (drag.el.nextElementSibling !== before || drag.el.parentNode !== list) list.insertBefore(drag.el, before); }
    else if (drag.el.parentNode !== list || list.lastElementChild !== drag.el) list.appendChild(drag.el);
  }
  function loop() {
    if (!drag || !drag.active) return;
    var host = colsEl(), r = host.getBoundingClientRect(), dx = 0, dy = 0;
    if (drag.px < r.left + 56) dx = -16; else if (drag.px > r.right - 56) dx = 16;
    if (drag.py < 84) dy = -14; else if (drag.py > window.innerHeight - 84) dy = 14;
    if (dx) host.scrollLeft += dx;
    if (dy) window.scrollBy(0, dy);
    if (dx || dy) retarget();
    drag.raf = requestAnimationFrame(loop);
  }
  function onMove(ev) {
    if (!drag || ev.pointerId !== drag.pid) return;
    drag.px = ev.clientX; drag.py = ev.clientY;
    if (!drag.active) {
      var d = Math.sqrt(Math.pow(ev.clientX - drag.x, 2) + Math.pow(ev.clientY - drag.y, 2));
      if (drag.type === 'mouse') { if (d > 5) startDrag(); }
      else if (d > 9) endDrag(false);
      return;
    }
    ev.preventDefault();
    place();
  }
  function onUp(ev) { if (drag && ev.pointerId === drag.pid) endDrag(true); }
  function onCancel(ev) { if (drag && ev.pointerId === drag.pid) endDrag(false); }
  function endDrag(commit) {
    var d = drag;
    drag = null;
    clearTimeout(d.timer); cancelAnimationFrame(d.raf);
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    document.removeEventListener('pointercancel', onCancel);
    if (!d.active) return;
    lastDragEnd = Date.now();
    document.body.classList.remove('bd-dragging');
    if (d.ghost) d.ghost.remove();
    $$('.bd-col').forEach(function (c) { c.classList.remove('drop'); });
    if (commit && d.el.parentNode && d.el.closest('.bd-col')) {
      var col = d.el.closest('.bd-col').getAttribute('data-col'), next = d.el.nextElementSibling;
      moveCard(d.id, col, next && next.classList.contains('bcard') ? next.getAttribute('data-id') : null);
      changed();
      var c = cardById(d.id);
      announce('Moved ' + c.title + ' to ' + colById(c.column).title + '.');
    } else { renderCols(); }
  }

  // ---- download and start -------------------------------------------------------------------------------------- //
  function download() {
    var final = applyChanges(S.base, canonBoard(S.board), 'owner');
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([toYaml(final)], { type: 'text/yaml' }));
    a.download = 'board.yaml';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
    toast('board.yaml downloaded. Replace docs/board/board.yaml with it and commit.');
  }
  function goLocal(why) {
    S.mode = 'local'; S.why = why; S.save = 'saved';
    var raw = store.get(KEY), saved = null;
    try { saved = raw ? JSON.parse(raw) : null; } catch (e) { saved = null; }
    if (saved && saved.board && saved.base) {
      if (saved.baseEtag === seed.etag) { S.board = saved.board; S.base = saved.base; S.baseEtag = saved.baseEtag; }
      else { S.board = mergeBoards(saved.base, saved.board, seed.board); S.base = clone(seed.board); S.baseEtag = seed.etag; localPersist(); }
      normalizeOrders();
    }
    render();
  }
  function goServed(j) {
    S.mode = 'served'; S.board = clone(j.board); S.base = clone(j.board); S.etag = j.etag; S.save = 'saved';
    normalizeOrders(); render();
  }
  function probe() {
    if (!/^https?:$/.test(location.protocol) || typeof fetch !== 'function') { goLocal('file'); return; }
    fetch('/api/board', { cache: 'no-store', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('status ' + r.status); return r.json(); })
      .then(function (j) { if (!j || !j.board || !j.etag) throw new Error('shape'); goServed(j); })
      .catch(function () { goLocal('http'); });
  }
  window.addEventListener('beforeunload', function (ev) {
    if (S.mode === 'served' && S.save !== 'saved') { ev.preventDefault(); ev.returnValue = ''; }
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && S.panel && !root.contains(ev.target) && document.getElementById('palette').hidden) closePanel();
  });
  skeleton();
  normalizeOrders();
  render();
  probe();
  setInterval(poll, 15000);
})();
