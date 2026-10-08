(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  var root = document.documentElement;
  var BUILD = root.getAttribute('data-build');
  var HOME = root.getAttribute('data-home');
  var blob = {};
  try { blob = JSON.parse($('#page-data').textContent) || {}; } catch (e) { blob = {}; }
  var data = blob.pages || {};
  var aliases = blob.aliases || {};

  // ---- storage (every access guarded: it can be blocked or full) ------------ //
  var EDIT_KEY = 'avs-docs-edits-v1';
  var THEME_KEY = 'avs-docs-theme';
  var store = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem(k, v); return true; } catch (e) { return false; } },
    del: function (k) { try { window.localStorage.removeItem(k); } catch (e) { /* ignore */ } }
  };
  var storageFailed = false;

  var pages = $$('.page');
  var toastTimer = null;
  function toast(msg) {
    var t = $('#toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 2600);
  }
  function escHtml(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  // ---- theme ----------------------------------------------------------------- //
  var savedTheme = store.get(THEME_KEY);
  if (savedTheme === 'light' || savedTheme === 'dark') root.setAttribute('data-theme', savedTheme);
  function toggleTheme() {
    var cur = root.getAttribute('data-theme');
    if (!cur) cur = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    var next = cur === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    store.set(THEME_KEY, next);
  }
  $('#theme-toggle').addEventListener('click', toggleTheme);

  // ---- routing: #page or #page/heading-id ---------------------------------------- //
  function parseHash() {
    var h = '';
    try { h = decodeURIComponent(location.hash.slice(1)); } catch (e) { h = location.hash.slice(1); }
    if (!h) return { page: HOME, anchor: '' };
    var i = h.indexOf('/');
    var page = i < 0 ? h : h.slice(0, i), anchor = i < 0 ? '' : h.slice(i + 1);
    return { page: aliases[page] || page, anchor: anchor };
  }
  function pageEl(id) { return document.getElementById('page-' + id); }
  var scrollSpyHeads = [];

  function openAncestors(node) {
    for (var n = node; n && n !== document.body; n = n.parentElement) {
      if (n.tagName === 'DETAILS') n.open = true;
    }
  }
  function syncNav(el) {
    var id = el.getAttribute('data-page'), group = el.getAttribute('data-group');
    $$('.nav-link').forEach(function (a) {
      var on = a.getAttribute('data-page') === id;
      a.classList.toggle('active', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    $$('.nav-group').forEach(function (g) {
      var cur = g.getAttribute('data-group') === group;
      g.classList.toggle('current', cur);
      if (cur) setGroup(g, true);
    });
    var active = $('.nav-link.active');
    if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
  }
  function setGroup(g, open) {
    g.classList.toggle('open', open);
    var b = $('.nav-title', g);
    if (b) b.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function show() {
    var r = parseHash();
    var el = pageEl(r.page) || pageEl(HOME) || pages[0];
    if (!el) return;
    pages.forEach(function (p) { p.hidden = p !== el; });
    var id = el.getAttribute('data-page');
    syncNav(el);
    document.title = (id === HOME ? '' : $('h1', el).textContent + ' - ') + (document.documentElement.getAttribute('data-title') || 'Docs');
    document.body.classList.remove('nav-open');
    $('#nav-toggle').setAttribute('aria-expanded', 'false');
    var target = r.anchor ? document.getElementById(id + '--' + r.anchor) : null;
    $$('.steps li', el).forEach(function (li) {
      var a = $('a.step', li);
      li.classList.toggle('on', !!a && a.getAttribute('href') === location.hash);
    });
    if (target) {
      openAncestors(target);
      target.scrollIntoView();
      target.classList.remove('flash'); void target.offsetWidth; target.classList.add('flash');
    } else {
      window.scrollTo(0, 0);
    }
    scrollSpyHeads = $$('.page-body h2, .page-body h3, .page-body details.sec', el);
    updateBanner();
  }
  window.addEventListener('hashchange', show);
  document.addEventListener('click', function (ev) {
    var a = ev.target.closest ? ev.target.closest('a[href^="#"]') : null;
    if (!a || a.closest('.results')) return;
    var href = a.getAttribute('href');
    if (href === location.hash) { ev.preventDefault(); show(); }
  });
  var spyTick = false;
  window.addEventListener('scroll', function () {
    if (spyTick) return;
    spyTick = true;
    requestAnimationFrame(function () {
      spyTick = false;
      var cur = null;
      for (var i = 0; i < scrollSpyHeads.length; i++) {
        if (scrollSpyHeads[i].getBoundingClientRect().top < 130) cur = scrollSpyHeads[i]; else if (scrollSpyHeads[i].tagName !== 'DETAILS') break;
      }
      var el = $('.page:not([hidden])');
      if (!el) return;
      var slug = cur ? cur.id.split('--')[1] : '';
      $$('.toc a', el).forEach(function (a) { a.classList.toggle('on', !!slug && a.getAttribute('href').split('/')[1] === slug); });
    });
  }, { passive: true });

  // ---- navigation (accordion) and mobile drawer --------------------------------------- //
  $$('.nav-title').forEach(function (b) {
    b.addEventListener('click', function () { var g = b.parentNode; setGroup(g, !g.classList.contains('open')); });
  });
  $('#nav-toggle').addEventListener('click', function () {
    var on = document.body.classList.toggle('nav-open');
    this.setAttribute('aria-expanded', on ? 'true' : 'false');
  });
  $('#scrim').addEventListener('click', function () { document.body.classList.remove('nav-open'); });

  // ---- expand / collapse sections ----------------------------------------------------- //
  function setAll(open) {
    var el = $('.page:not([hidden])');
    if (!el) return;
    $$('details.sec', el).forEach(function (d) { if (!d.hidden) d.open = open; });
  }

  // ---- reference tables: text filter, column filters, page filter ----------------------- //
  function rowsOf(t) { return $$('tbody tr', t); }
  function refilter(t) {
    var q = (t._q || '').toLowerCase(), pq = (t._pq || '').toLowerCase(), sel = t._sel || {};
    rowsOf(t).forEach(function (tr) {
      var text = tr._text || (tr._text = tr.textContent.toLowerCase());
      var ok = (!q || text.indexOf(q) >= 0) && (!pq || text.indexOf(pq) >= 0);
      if (ok) {
        Object.keys(sel).forEach(function (c) {
          if (sel[c] && ((tr.children[c] || {}).textContent || '').trim() !== sel[c]) ok = false;
        });
      }
      tr.hidden = !ok;
    });
  }
  function enhanceTables() {
    $$('.page[data-kind="generated"] .tablewrap > table').forEach(function (t) {
      var wrap = t.parentNode;
      if (wrap.closest('.item')) return;
      var rows = rowsOf(t);
      if (rows.length < 8 || (wrap.previousElementSibling && wrap.previousElementSibling.classList.contains('tbl-tools'))) return;
      var tools = document.createElement('div');
      tools.className = 'tbl-tools';
      var input = document.createElement('input');
      input.type = 'search'; input.className = 'tbl-filter'; input.placeholder = 'Filter ' + rows.length + ' rows'; input.setAttribute('aria-label', 'Filter this table');
      input.addEventListener('input', function () { t._q = input.value.trim(); refilter(t); });
      tools.appendChild(input);
      var heads = $$('thead th', t);
      heads.forEach(function (th, c) {
        var seen = {}, n = 0, tooLong = false;
        rows.forEach(function (tr) {
          var v = ((tr.children[c] || {}).textContent || '').trim();
          if (v.length > 28) tooLong = true;
          if (v && !seen[v]) { seen[v] = 1; n++; }
        });
        if (tooLong || n < 2 || n > 9 || n > rows.length / 1.6) return;
        var s = document.createElement('select');
        s.setAttribute('aria-label', 'Filter by ' + th.textContent);
        s.innerHTML = '<option value="">' + escHtml(th.textContent) + ': all</option>' +
          Object.keys(seen).sort().map(function (v) { return '<option>' + escHtml(v) + '</option>'; }).join('');
        s.addEventListener('change', function () { t._sel = t._sel || {}; t._sel[c] = s.value; refilter(t); });
        tools.appendChild(s);
      });
      wrap.parentNode.insertBefore(tools, wrap);
    });
  }
  function pageFilter(input) {
    var el = input.closest('.page'), q = input.value.trim().toLowerCase();
    $$('.tablewrap > table', el).forEach(function (t) { if (!t.closest('.item')) { t._pq = q; refilter(t); } });
    $$('.item', el).forEach(function (it) { it.hidden = !!q && (it._text || (it._text = it.textContent.toLowerCase())).indexOf(q) < 0; });
    $$('details.refsec', el).forEach(function (d) {
      if (d._was === undefined) d._was = d.open;
      if (!q) { d.hidden = false; d.open = d._was; d._was = undefined; return; }
      var items = $$('.item', d), rows = $$('tbody tr', d).filter(function (tr) { return !tr.closest('.item'); });
      var n = items.length ? items.filter(function (i) { return !i.hidden; }).length
        : rows.length ? rows.filter(function (r) { return !r.hidden; }).length
          : (d.textContent.toLowerCase().indexOf(q) >= 0 ? 1 : 0);
      d.hidden = n === 0;
      d.open = n > 0;
    });
  }
  document.addEventListener('input', function (ev) {
    var t = ev.target;
    if (t.classList && t.classList.contains('page-filter')) pageFilter(t);
    if (t.classList && t.classList.contains('kfilter')) {
      var q = t.value.trim().toLowerCase(), box = t.closest('.viz');
      $$('.kitem', box).forEach(function (li) { li.hidden = !!q && li.textContent.toLowerCase().indexOf(q) < 0; });
    }
  });
  enhanceTables();

  // ---- search palette (Ctrl+K or /) ------------------------------------------------------ //
  var palette = $('#palette'), q = $('#q'), results = $('#results');
  var index = [], indexDirty = true, hits = [], active = 0;
  var ICONS = {
    page: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
    section: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 9h16M4 15h16M10 3L8 21M16 3l-2 18"/></svg>',
    item: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/></svg>',
    action: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2L3 14h9l-1 8 10-12h-9z"/></svg>'
  };
  function headingText(node) {
    var c = node.cloneNode(true);
    $$('.anchor, .count', c).forEach(function (a) { a.remove(); });
    return c.textContent.trim();
  }
  function entry(type, page, title, group, hid, h, text) {
    text = (text || '').replace(/\s+/g, ' ').trim();
    return { type: type, page: page, title: title, group: group, hid: hid, h: h, text: text, lt: title.toLowerCase(), lh: (h || '').toLowerCase(),
      lc: (title + ' ' + group + ' ' + h + ' ' + text).toLowerCase() };
  }
  function buildIndex() {
    index = [];
    pages.forEach(function (p) {
      var id = p.getAttribute('data-page'), title = $('h1', p).textContent.trim();
      var group = ($('.crumb-g', p) || {}).textContent || '';
      var lede = ($('.lede', p) || {}).textContent || '';
      var pe = entry('page', id, title, group, '', '', lede);
      index.push(pe);
      var body = $('.page-body', p), cur = pe;
      Array.prototype.forEach.call(body.children, function (node) {
        if (/^H[23]$/.test(node.tagName)) {
          cur = entry('section', id, title, group, node.id.split('--')[1] || '', headingText(node), '');
          index.push(cur);
        } else if (node.tagName === 'DETAILS' && node.id) {
          var sm = $('summary', node);
          index.push(entry('section', id, title, group, node.id.split('--')[1], sm ? headingText(sm) : (node.getAttribute('data-title') || ''), node.textContent));
        } else {
          cur.text += ' ' + node.textContent;
        }
      });
      $$('.item[id]', body).forEach(function (it) {
        var hd = $('.item-head', it);
        index.push(entry('item', id, title, group, it.id.split('--')[1], hd ? hd.textContent.trim() : '', it.textContent));
      });
    });
    index.forEach(function (c) { c.lc = (c.title + ' ' + c.group + ' ' + c.h + ' ' + c.text).toLowerCase(); c.lh = c.h.toLowerCase(); });
    indexDirty = false;
  }
  function snippet(text, toks) {
    var low = text.toLowerCase(), pos = -1;
    for (var i = 0; i < toks.length; i++) { var p = low.indexOf(toks[i]); if (p >= 0 && (pos < 0 || p < pos)) pos = p; }
    if (pos < 0) return escHtml(text.slice(0, 150));
    var start = Math.max(0, pos - 50), piece = text.slice(start, start + 160), out = escHtml(piece);
    toks.forEach(function (t) {
      if (!t) return;
      out = out.replace(new RegExp('(' + escHtml(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig'), '<mark>$1</mark>');
    });
    return (start > 0 ? '... ' : '') + out + (start + 160 < text.length ? ' ...' : '');
  }
  function search(raw) {
    var toks = raw.toLowerCase().split(/\s+/).filter(Boolean), out = [];
    index.forEach(function (c) {
      var score = 0;
      for (var i = 0; i < toks.length; i++) {
        var t = toks[i];
        if (c.lc.indexOf(t) < 0) return;
        if (c.type === 'page' && c.lt.indexOf(t) >= 0) score += 14;
        if (c.lh && c.lh.indexOf(t) >= 0) score += 10;
        if (c.lt.indexOf(t) >= 0) score += 3;
        if (c.lh === t) score += 6;
        var n = 0, from = 0, at;
        while (n < 4 && (at = c.lc.indexOf(t, from)) >= 0) { n++; from = at + t.length; }
        score += n;
      }
      if (c.type === 'page') score += 4;
      if (c.group === 'Reference') score -= 3;
      out.push({ c: c, s: score, toks: toks });
    });
    out.sort(function (a, b) { return b.s - a.s; });
    return out.slice(0, 24);
  }
  function defaultList() {
    var list = [{ action: 'theme', title: 'Switch between light and dark', c: { type: 'action' } },
      { action: 'edit', title: 'Turn editing on or off', c: { type: 'action' } }];
    pages.forEach(function (p) {
      if (p.getAttribute('data-group') === 'reference' && p.getAttribute('data-page') !== 'reference') return;
      var id = p.getAttribute('data-page');
      list.push({ c: entry('page', id, $('h1', p).textContent.trim(), ($('.crumb-g', p) || {}).textContent || '', '', '', ($('.lede', p) || {}).textContent || ''), toks: [], plain: true });
    });
    return list;
  }
  var lastGroup = '';
  function renderResults() {
    var raw = q.value.trim();
    if (indexDirty) buildIndex();
    hits = raw ? search(raw) : defaultList();
    active = 0;
    lastGroup = '';
    if (!hits.length) { results.innerHTML = '<div class="none">Nothing found for "' + escHtml(raw) + '". Try a shorter word.</div>'; return; }
    results.innerHTML = hits.map(function (h, i) {
      var c = h.c, label = '', head = '', title = '';
      if (!raw) { label = h.action ? 'Actions' : 'Pages'; } else { label = c.type === 'page' ? 'Pages' : c.type === 'section' ? 'Sections' : 'Items'; }
      if (label !== lastGroup) { head = '<div class="r-group">' + label + '</div>'; lastGroup = label; }
      var href = h.action ? '#' : '#' + c.page + (c.hid ? '/' + c.hid : '');
      if (h.action) title = escHtml(h.title);
      else if (c.type === 'page') title = escHtml(c.title);
      else title = escHtml(c.h || c.title) + ' <small>in ' + escHtml(c.title) + '</small>';
      var sub = h.action ? '' : (raw ? snippet(c.text || c.group, h.toks) : escHtml(c.group + (c.text ? ' - ' + c.text.slice(0, 90) : '')));
      return head + '<a role="option" href="' + escHtml(href) + '" data-i="' + i + '" class="' + (i === 0 ? 'active' : '') + '"><span class="r-ico">' + ICONS[c.type] +
        '</span><span class="r-main"><div class="r-title">' + title + '</div>' + (sub ? '<div class="r-snip">' + sub + '</div>' : '') + '</span></a>';
    }).join('');
  }
  function openPalette() {
    palette.hidden = false;
    document.body.classList.remove('nav-open');
    q.value = '';
    renderResults();
    q.focus();
  }
  function closePalette() { palette.hidden = true; }
  function setActive(i) {
    var links = $$('a', results);
    if (!links.length) return;
    active = (i + links.length) % links.length;
    links.forEach(function (a, k) { a.classList.toggle('active', k === active); });
    links[active].scrollIntoView({ block: 'nearest' });
  }
  function choose(i) {
    var h = hits[i];
    if (!h) return;
    closePalette();
    if (h.action === 'theme') { toggleTheme(); return; }
    if (h.action === 'edit') { setEditing(!editing); return; }
    var c = h.c;
    location.hash = '#' + c.page + (c.hid ? '/' + c.hid : '');
  }
  $('#open-search').addEventListener('click', openPalette);
  q.addEventListener('input', renderResults);
  q.addEventListener('keydown', function (ev) {
    if (ev.key === 'ArrowDown') { ev.preventDefault(); setActive(active + 1); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); setActive(active - 1); }
    else if (ev.key === 'Enter') { ev.preventDefault(); choose(active); }
    else if (ev.key === 'Escape') { ev.preventDefault(); closePalette(); }
  });
  results.addEventListener('click', function (ev) {
    var a = ev.target.closest ? ev.target.closest('a[data-i]') : null;
    if (!a) return;
    ev.preventDefault();
    choose(+a.getAttribute('data-i'));
  });
  results.addEventListener('mousemove', function (ev) {
    var a = ev.target.closest ? ev.target.closest('a[data-i]') : null;
    if (a && +a.getAttribute('data-i') !== active) { $$('a', results).forEach(function (x) { x.classList.toggle('active', x === a); }); active = +a.getAttribute('data-i'); }
  });
  palette.addEventListener('click', function (ev) { if (ev.target.getAttribute && ev.target.getAttribute('data-close')) closePalette(); });
  document.addEventListener('keydown', function (ev) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((ev.target || {}).tagName || '') || (ev.target && ev.target.isContentEditable);
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k') { ev.preventDefault(); if (palette.hidden) openPalette(); else closePalette(); }
    else if (ev.key === '/' && !typing) { ev.preventDefault(); openPalette(); }
    else if (ev.key === 'Escape' && !palette.hidden) closePalette();
  });

  // ---- editing ------------------------------------------------------------------------ //
  var editing = false;
  var originals = {};      // page id -> body innerHTML as built (before any stored edits)
  var edits = {};          // page id -> edited body innerHTML
  var stale = null;        // edits found from an older build of the docs
  var openedForEdit = [];
  function bodyOf(id) { var p = pageEl(id); return p && $('.page-body[data-editable]', p); }
  $$('.page[data-kind="written"]').forEach(function (p) {
    var id = p.getAttribute('data-page'), b = bodyOf(id);
    if (!b) return;                                   // the status board page is not editable text
    originals[id] = b.innerHTML;
    if (b.getAttribute('data-edited')) edits[id] = b.innerHTML;     // a downloaded edited file
  });

  function saveEdits() {
    var ok = store.set(EDIT_KEY, JSON.stringify({ build: BUILD, pages: edits, at: Date.now() }));
    storageFailed = !ok;
    updateBanner();
  }
  function loadStored() {
    var raw = store.get(EDIT_KEY);
    if (!raw) return;
    var saved = null;
    try { saved = JSON.parse(raw); } catch (e) { return; }
    if (!saved || !saved.pages) return;
    if (saved.build === BUILD) { applyEdits(saved.pages); } else { stale = saved; }
  }
  function applyEdits(map) {
    Object.keys(map).forEach(function (id) {
      var b = bodyOf(id);
      if (!b) return;
      b.innerHTML = map[id];
      b.setAttribute('data-edited', '1');
      edits[id] = map[id];
    });
    indexDirty = true;
  }
  function editedIds() { return Object.keys(edits); }

  function setEditing(on) {
    editing = on;
    document.body.classList.toggle('editing', on);
    $$('[data-editable]').forEach(function (el) {
      if (on) { el.setAttribute('contenteditable', 'true'); el.setAttribute('spellcheck', 'true'); }
      else { el.removeAttribute('contenteditable'); el.removeAttribute('spellcheck'); }
    });
    var cur = $('.page:not([hidden])');
    if (on && cur) {
      openedForEdit = $$('details.sec', cur).filter(function (d) { return !d.open; });
      openedForEdit.forEach(function (d) { d.open = true; });
    } else {
      openedForEdit.forEach(function (d) { d.open = false; });
      openedForEdit = [];
    }
    var btn = $('#edit-toggle');
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.textContent = on ? 'Done' : 'Edit';
    if (on && cur && cur.getAttribute('data-kind') !== 'written') toast('Generated pages are read-only. Open a guide to edit it.');
    else if (on && cur && !bodyOf(cur.getAttribute('data-page'))) toast('The status board is edited on the page itself.');
    updateBanner();
  }
  $('#edit-toggle').addEventListener('click', function () { setEditing(!editing); });

  var saveTimer = null;
  document.addEventListener('input', function (ev) {
    var b = ev.target.closest ? ev.target.closest('.page-body[data-editable]') : null;
    if (!b) return;
    var id = b.closest('.page').getAttribute('data-page');
    b.setAttribute('data-edited', '1');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { edits[id] = b.innerHTML; indexDirty = true; saveEdits(); }, 250);
  });

  function updateBanner() {
    var banner = $('#edit-banner'), text = $('#banner-text');
    var n = editedIds().length;
    var restore = $('[data-act="restore"]');
    restore.hidden = !stale;
    if (!editing && !n && !stale) { banner.hidden = true; return; }
    var msg = [];
    if (editing) msg.push('<strong>Editing.</strong> Click in the text and type. Cards, steps and diagrams are changed in the .md file. Reference pages stay read-only.');
    if (n) msg.push(n + ' page' + (n === 1 ? '' : 's') + ' changed. Changes live in this browser only: use Copy as Markdown to paste them back into docs/site/src, or download the HTML.');
    if (stale) msg.push('Edits made on an older build of the docs are stored here (' + Object.keys(stale.pages).length + ' page(s)). They may overwrite newer text.');
    if (storageFailed) msg.push('<strong>This browser would not store the edits.</strong> Download the HTML before you close the page.');
    text.innerHTML = msg.join(' ');
    $('[data-act="discard"]').hidden = !(n || stale);
    $('[data-act="download"]').hidden = !n;
    $('[data-act="copy-section"]').hidden = !editing;
    banner.hidden = false;
  }

  // ---- HTML to Markdown (for pasting an edited section back) --------------------------- //
  function ws(s) { return s.replace(/\s+/g, ' '); }
  function badgeKey(n) {
    var m = /\b(done|running|planned|built)\b/.exec(n.className || '');
    return m ? m[1] : n.textContent.trim().toLowerCase().replace(/\s+/g, ' ');
  }
  function inlineMd(node) {
    var out = '';
    Array.prototype.forEach.call(node.childNodes, function (n) {
      if (n.nodeType === 3) { out += ws(n.nodeValue); return; }
      if (n.nodeType !== 1) return;
      var tag = n.tagName, cls = n.className || '';
      if (cls && /anchor/.test(cls)) return;
      if (tag === 'STRONG' || tag === 'B') out += '**' + inlineMd(n).trim() + '**';
      else if (tag === 'EM' || tag === 'I') out += '*' + inlineMd(n).trim() + '*';
      else if (tag === 'CODE') out += '`' + n.textContent + '`';
      else if (tag === 'A') out += '[' + inlineMd(n).trim() + '](' + (n.getAttribute('href') || '') + ')';
      else if (tag === 'BR') out += ' ';
      else if (tag === 'SPAN' && /badge/.test(cls)) out += '[[' + badgeKey(n) + ']]';
      else if (tag === 'UL' || tag === 'OL') { /* handled by list code */ }
      else out += inlineMd(n);
    });
    return out;
  }
  function listMd(el, depth) {
    var ordered = el.tagName === 'OL', n = 0, out = '', pad = new Array(depth * 2 + 1).join(' ');
    Array.prototype.forEach.call(el.children, function (li) {
      if (li.tagName !== 'LI') return;
      n++;
      var own = document.createElement('div');
      var nested = '';
      Array.prototype.forEach.call(li.childNodes, function (c) {
        if (c.nodeType === 1 && (c.tagName === 'UL' || c.tagName === 'OL')) nested += listMd(c, depth + 1);
        else own.appendChild(c.cloneNode(true));
      });
      out += pad + (ordered ? n + '. ' : '- ') + inlineMd(own).trim() + '\n' + nested;
    });
    return out;
  }
  function tableMd(t) {
    var rows = $$('tr', t).map(function (tr) {
      return '| ' + $$('th,td', tr).map(function (c) { return inlineMd(c).trim().replace(/\|/g, '\\|'); }).join(' | ') + ' |';
    });
    if (!rows.length) return '';
    var cols = $$('th,td', $('tr', t)).length;
    rows.splice(1, 0, '|' + new Array(cols + 1).join(' --- |'));
    return rows.join('\n') + '\n\n';
  }
  function blocksMd(parent) {
    var out = '';
    Array.prototype.forEach.call(parent.childNodes, function (n) {
      if (n.nodeType === 3) { if (n.nodeValue.trim()) out += ws(n.nodeValue).trim() + '\n\n'; return; }
      if (n.nodeType !== 1) return;
      var tag = n.tagName, m;
      if (n.getAttribute('data-md')) { out += n.getAttribute('data-md') + '\n\n'; return; }
      if ((m = /^H([2-4])$/.exec(tag))) out += new Array(+m[1] + 1).join('#') + ' ' + headingText(n) + '\n\n';
      else if (tag === 'P') out += inlineMd(n).trim() + '\n\n';
      else if (tag === 'UL' || tag === 'OL') out += listMd(n, 0) + '\n';
      else if (tag === 'PRE') {
        var c = $('code', n), lang = ((c && c.className.match(/lang-(\S+)/)) || [])[1] || '';
        out += '```' + lang + '\n' + n.textContent.replace(/\n$/, '') + '\n```\n\n';
      }
      else if (tag === 'TABLE') out += tableMd(n);
      else if (tag === 'BLOCKQUOTE') out += blocksMd(n).trim().split('\n').map(function (l) { return '> ' + l; }).join('\n').replace(/^> $/gm, '>') + '\n\n';
      else if (tag === 'HR') out += '---\n\n';
      else if (tag === 'ASIDE') {
        var kind = (n.className.match(/callout\s+(\S+)/) || [])[1] || 'note', clone = n.cloneNode(true);
        var title = $('.callout-title', clone); if (title) title.remove();
        out += ':::' + kind + '\n' + blocksMd(clone).trim() + '\n:::\n\n';
      }
      else if (tag === 'DETAILS') {
        var clone2 = n.cloneNode(true), sm = $('summary', clone2), head = sm ? inlineMd(sm).trim() : (n.getAttribute('data-title') || 'Details');
        if (sm) sm.remove();
        out += ':::details ' + (n.hasAttribute('data-open-default') ? 'open ' : '') + head + '\n' + blocksMd(clone2).trim() + '\n:::\n\n';
      }
      else if (tag === 'FIGURE' && n.getAttribute('data-svg')) {
        var cap = $('figcaption', n);
        out += '{{svg:' + n.getAttribute('data-svg') + (cap ? '|' + inlineMd(cap).trim() : '') + '}}\n\n';
      }
      else if (tag === 'DIV' || tag === 'SECTION' || tag === 'FIGURE') out += blocksMd(n);
      else out += inlineMd(n).trim() + '\n\n';
    });
    return out;
  }
  function frontmatter(id) {
    var m = (data[id] && data[id].meta) || {}, order = ['id', 'title', 'group', 'order', 'status', 'layout', 'summary'], out = '---\n';
    order.forEach(function (k) { if (m[k] !== undefined && m[k] !== '') out += k + ': ' + m[k] + '\n'; });
    return out + '---\n\n';
  }
  function pageMarkdown(id) {
    var b = bodyOf(id);
    if (!b) return '';
    if (!b.getAttribute('data-edited') && data[id]) return frontmatter(id) + data[id].md;
    return frontmatter(id) + blocksMd(b).replace(/\n{3,}/g, '\n\n').trim() + '\n';
  }
  function sectionMarkdown(id) {
    var b = bodyOf(id), sel = window.getSelection && window.getSelection();
    if (!b || !sel || !sel.anchorNode || !b.contains(sel.anchorNode)) return null;
    var n = sel.anchorNode;
    while (n && n.parentNode !== b) n = n.parentNode;
    if (!n) return null;
    var frag = document.createElement('div');
    if (n.nodeType === 1 && n.tagName === 'DETAILS') { frag.appendChild(n.cloneNode(true)); return blocksMd(frag).replace(/\n{3,}/g, '\n\n').trim() + '\n'; }
    var start = n;
    while (start && !(start.nodeType === 1 && start.tagName === 'H2')) start = start.previousSibling;
    if (!start) { frag.appendChild(n.cloneNode(true)); return blocksMd(frag).replace(/\n{3,}/g, '\n\n').trim() + '\n'; }
    var cur = start;
    do { frag.appendChild(cur.cloneNode(true)); cur = cur.nextSibling; } while (cur && !(cur.nodeType === 1 && cur.tagName === 'H2'));
    return blocksMd(frag).replace(/\n{3,}/g, '\n\n').trim() + '\n';
  }
  function copy(text, label) {
    function done() { toast(label + ' copied (' + text.length + ' characters).'); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
    } else { fallbackCopy(text); done(); }
  }
  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e) { /* ignore */ }
    ta.remove();
  }
  function currentId() { var el = $('.page:not([hidden])'); return el ? el.getAttribute('data-page') : ''; }

  // ---- download the page with its edits ---------------------------------------------- //
  function download() {
    var clone = root.cloneNode(true);
    $$('[data-editable]', clone).forEach(function (el) { el.removeAttribute('contenteditable'); el.removeAttribute('spellcheck'); });
    $$('.tbl-tools', clone).forEach(function (el) { el.remove(); });
    $$('[hidden]', clone).forEach(function (el) { if (el.tagName === 'TR' || el.classList.contains('item') || el.classList.contains('kitem')) el.removeAttribute('hidden'); });
    $('body', clone).classList.remove('nav-open'); $('body', clone).classList.remove('editing');
    $('#edit-banner', clone).hidden = true;
    var pal = $('#palette', clone); pal.hidden = true;
    var res = $('#results', clone); res.innerHTML = '';
    $('#q', clone).removeAttribute('value');
    var toastEl = $('#toast', clone); toastEl.hidden = true;
    var html = '<!doctype html>\n' + clone.outerHTML;
    var blobFile = new Blob([html], { type: 'text/html' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blobFile);
    a.download = 'ai-video-studio-docs-edited.html';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }

  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!btn) return;
    var act = btn.getAttribute('data-act'), id = currentId();
    if (act === 'copy-page') copy(pageMarkdown(id), 'Page Markdown');
    else if (act === 'copy-section') {
      var md = sectionMarkdown(id);
      if (md) copy(md, 'Section Markdown'); else toast('Click inside a section of a guide first.');
    }
    else if (act === 'expand-all') setAll(true);
    else if (act === 'collapse-all') setAll(false);
    else if (act === 'download') download();
    else if (act === 'reset-page') {
      if (!originals[id] || !confirm('Discard your edits to this page?')) return;
      var b = bodyOf(id); b.innerHTML = originals[id]; b.removeAttribute('data-edited');
      delete edits[id]; indexDirty = true; saveEdits();
    }
    else if (act === 'discard') {
      if (!confirm('Discard every edit stored in this browser?')) return;
      Object.keys(edits).forEach(function (pid) { var bb = bodyOf(pid); if (bb && originals[pid] !== undefined) { bb.innerHTML = originals[pid]; bb.removeAttribute('data-edited'); } });
      edits = {}; stale = null; store.del(EDIT_KEY); indexDirty = true; updateBanner();
    }
    else if (act === 'restore') {
      if (stale) { applyEdits(stale.pages); stale = null; saveEdits(); toast('Stored edits restored.'); }
    }
  });

  loadStored();
  show();
})();

/* :::levels — switch panels; every toggle on the page follows the last choice */
(function () {
  function show(level) {
    document.querySelectorAll(".levels").forEach(function (box) {
      var btns = box.querySelectorAll(".lv-btn"), panels = box.querySelectorAll(".lv-panel");
      var k = Math.min(level, btns.length - 1);
      btns.forEach(function (b, i) { b.classList.toggle("on", i === k); b.setAttribute("aria-selected", i === k ? "true" : "false"); });
      panels.forEach(function (p, i) { p.hidden = i !== k; });
    });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".lv-btn");
    if (!b) return;
    var level = parseInt(b.getAttribute("data-lv"), 10) || 0;
    show(level);
    try { localStorage.setItem("docs-level", String(level)); } catch (err) {}
  });
  var saved = 0;
  try { saved = parseInt(localStorage.getItem("docs-level") || "0", 10) || 0; } catch (err) {}
  if (saved) show(saved);
})();

/* Diagram export: SVG and PNG with the current theme's colours inlined */
(function () {
  var PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "font-family", "font-size",
               "font-weight", "letter-spacing", "text-transform", "text-anchor"];
  function standalone(svg) {
    var clone = svg.cloneNode(true), src = svg.querySelectorAll("*"), dst = clone.querySelectorAll("*");
    [].slice.call(clone.querySelectorAll(".pv-packet")).forEach(function (p) { p.remove(); });
    for (var i = 0; i < src.length; i++) {
      var cs = getComputedStyle(src[i]), style = "";
      PROPS.forEach(function (p) { var v = cs.getPropertyValue(p); if (v) style += p + ":" + v + ";"; });
      dst[i].setAttribute("style", style);
    }
    var vb = svg.viewBox.baseVal, bg = getComputedStyle(svg.closest("figure") || document.body).backgroundColor;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", vb.width); clone.setAttribute("height", vb.height);
    clone.removeAttribute("style");
    var rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", vb.x); rect.setAttribute("y", vb.y); rect.setAttribute("width", vb.width);
    rect.setAttribute("height", vb.height); rect.setAttribute("fill", bg || "#ffffff");
    clone.insertBefore(rect, clone.firstChild);
    return { text: new XMLSerializer().serializeToString(clone), w: vb.width, h: vb.height };
  }
  function save(blob, name) {
    var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  function exportFig(fig, kind) {
    var svg = fig.querySelector("svg"); if (!svg) return;
    var name = (fig.getAttribute("data-svg") || fig.getAttribute("data-name") || "diagram"), out = standalone(svg);
    var blob = new Blob([out.text], { type: "image/svg+xml;charset=utf-8" });
    if (kind === "svg") return save(blob, name + ".svg");
    var img = new Image(), scale = 2;
    img.onload = function () {
      var c = document.createElement("canvas"); c.width = out.w * scale; c.height = out.h * scale;
      var ctx = c.getContext("2d"); ctx.scale(scale, scale); ctx.drawImage(img, 0, 0);
      c.toBlob(function (b) { if (b) save(b, name + ".png"); }, "image/png");
      URL.revokeObjectURL(img.src);
    };
    img.src = URL.createObjectURL(blob);
  }
  document.querySelectorAll("figure.diagram").forEach(function (fig) {
    if (!fig.querySelector("svg") || fig.querySelector(".dg-export")) return;
    var bar = document.createElement("div");
    bar.className = "dg-export";
    bar.innerHTML = '<button type="button" data-kind="png">Export PNG</button>' +
                    '<button type="button" data-kind="svg">Export SVG</button>';
    bar.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (b) exportFig(fig, b.getAttribute("data-kind"));
    });
    fig.insertBefore(bar, fig.firstChild);
  });
})();

/* Diagram full screen: pan, wheel / pinch zoom, fit */
(function () {
  var ov = null, st = null;
  function apply() { st.svg.style.transform = "translate(" + st.x + "px," + st.y + "px) scale(" + st.k + ")"; st.lbl.textContent = Math.round(st.k * 100) + "%"; }
  function fit() {
    var r = st.stage.getBoundingClientRect(), pad = 24;
    st.k = Math.min((r.width - pad * 2) / st.w, (r.height - pad * 2) / st.h);
    st.x = (r.width - st.w * st.k) / 2; st.y = (r.height - st.h * st.k) / 2; apply();
  }
  function zoomAt(f, cx, cy) {
    var k = Math.max(0.05, Math.min(12, st.k * f)); f = k / st.k;
    st.x = cx - (cx - st.x) * f; st.y = cy - (cy - st.y) * f; st.k = k; apply();
  }
  function centre(f) { var r = st.stage.getBoundingClientRect(); zoomAt(f, r.width / 2, r.height / 2); }
  function close() {
    if (!ov) return;
    document.removeEventListener("keydown", onKey, true);
    ov.remove(); ov = st = null; document.documentElement.style.overflow = "";
  }
  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "+" || e.key === "=") centre(1.25);
    else if (e.key === "-") centre(0.8);
    else if (e.key === "0") fit();
  }
  function open(fig) {
    var src = fig.querySelector("svg"); if (!src || ov) return;
    var vb = src.viewBox.baseVal, svg = src.cloneNode(true);
    svg.removeAttribute("style"); svg.removeAttribute("data-wide");
    svg.setAttribute("width", vb.width); svg.setAttribute("height", vb.height);
    ov = document.createElement("div");
    ov.className = "dg-fs"; ov.setAttribute("role", "dialog"); ov.setAttribute("aria-modal", "true"); ov.setAttribute("aria-label", "Diagram, full screen");
    ov.innerHTML = '<div class="dg-fs-bar"><span class="dg-fs-hint">Drag to move, scroll or pinch to zoom</span><span class="dg-fs-sp"></span>' +
      '<button type="button" data-a="out" aria-label="Zoom out">&minus;</button><span class="dg-fs-pct" aria-live="polite"></span>' +
      '<button type="button" data-a="in" aria-label="Zoom in">+</button><button type="button" data-a="fit">Fit</button>' +
      '<button type="button" data-a="one">100%</button><button type="button" data-a="close">Close</button></div>' +
      '<div class="dg-fs-stage"><figure class="diagram dg-fs-fig"></figure></div>';
    var stage = ov.querySelector(".dg-fs-stage");
    stage.querySelector("figure").appendChild(svg);
    st = { svg: svg, stage: stage, lbl: ov.querySelector(".dg-fs-pct"), w: vb.width, h: vb.height, x: 0, y: 0, k: 1 };
    document.body.appendChild(ov); document.documentElement.style.overflow = "hidden";
    document.addEventListener("keydown", onKey, true);
    ov.querySelector(".dg-fs-bar").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      var a = b.getAttribute("data-a");
      if (a === "close") close(); else if (a === "fit") fit(); else if (a === "in") centre(1.25);
      else if (a === "out") centre(0.8);
      else if (a === "one") { var r = stage.getBoundingClientRect(); zoomAt(1 / st.k, r.width / 2, r.height / 2); }
    });
    var ptr = {}, last = 0;
    stage.addEventListener("wheel", function (e) {
      e.preventDefault(); var r = stage.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    stage.addEventListener("pointerdown", function (e) { stage.setPointerCapture(e.pointerId); ptr[e.pointerId] = { x: e.clientX, y: e.clientY }; last = 0; stage.classList.add("grab"); });
    stage.addEventListener("pointermove", function (e) {
      var p = ptr[e.pointerId]; if (!p) return;
      var ids = Object.keys(ptr);
      if (ids.length === 2) {
        var o = ptr[ids[0] === String(e.pointerId) ? ids[1] : ids[0]], d = Math.hypot(e.clientX - o.x, e.clientY - o.y), r = stage.getBoundingClientRect();
        if (last) zoomAt(d / last, (e.clientX + o.x) / 2 - r.left, (e.clientY + o.y) / 2 - r.top);
        last = d;
      } else { st.x += e.clientX - p.x; st.y += e.clientY - p.y; apply(); }
      p.x = e.clientX; p.y = e.clientY;
    });
    function up(e) { delete ptr[e.pointerId]; last = 0; if (!Object.keys(ptr).length) stage.classList.remove("grab"); }
    stage.addEventListener("pointerup", up); stage.addEventListener("pointercancel", up);
    stage.addEventListener("dblclick", fit);
    fit(); ov.querySelector('[data-a="close"]').focus();
  }
  window.addEventListener("resize", function () { if (ov) fit(); });
  document.querySelectorAll("figure.diagram").forEach(function (fig) {
    var bar = fig.querySelector(".dg-export"); if (!bar || bar.querySelector('[data-kind="full"]')) return;
    var b = document.createElement("button"); b.type = "button"; b.setAttribute("data-kind", "full"); b.textContent = "Full screen";
    bar.insertBefore(b, bar.firstChild);
    b.addEventListener("click", function (e) { e.stopPropagation(); open(fig); });
  });
})();
