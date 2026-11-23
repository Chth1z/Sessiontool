// 共享基础设施：DOM/格式工具、来源元数据、主题、图片放大、浮层、实时更新与全局交互分发
(function () {
  'use strict';

  var body = document.body, root = document.documentElement;
  var live = !!body.dataset.state;          // 有本地服务可以问（导出的独立文件没有）
  var SVG = 'http://www.w3.org/2000/svg';
  var WEEK = '一二三四五六日';
  var SRC = {
    claude: { name: 'Claude', attr: 'c', cls: '', badge: 'cl', who: 'who-claude', idLabel: '记录 ID',
      idHint: '当前记录文件的编号，可以用来恢复会话', verLabel: 'Claude Code 版本', permLabel: '权限模式' },
    codex: { name: 'Codex', attr: 'x', cls: 'cx', badge: 'cx', who: 'who-codex', idLabel: '线程 ID',
      idHint: 'Codex 用它找到这个会话', verLabel: 'Codex 版本', permLabel: '审批' },
    gemini: { name: 'Gemini', attr: 'g', cls: 'gm', badge: 'gm', who: 'who-gemini', idLabel: '会话 ID',
      idHint: 'Antigravity 用它标识这个会话', verLabel: 'Antigravity 版本', permLabel: '权限模式' }
  };

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return [].slice.call((r || document).querySelectorAll(s)); }
  var mainEl = $('main');
  function mainScroller() { return mainEl && getComputedStyle(mainEl).overflowY === 'auto' ? mainEl : window; }
  function scrollYOf() { var s = mainScroller(); return s === window ? window.scrollY : s.scrollTop; }
  function viewHOf() { var s = mainScroller(); return s === window ? window.innerHeight : s.clientHeight; }
  function scrollHOf() { var s = mainScroller(); return s === window ? root.scrollHeight : s.scrollHeight; }
  function scrollToY(y) { var s = mainScroller(); if (s === window) window.scrollTo(0, y); else s.scrollTop = y; }
  function scrollByY(dy) { var s = mainScroller(); if (s === window) window.scrollBy(0, dy); else s.scrollTop += dy; }
  function onMainScroll(fn) {
    window.addEventListener('scroll', fn, { passive: true });
    if (mainEl) mainEl.addEventListener('scroll', fn, { passive: true });
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function svg(tag, attrs, text) {
    var e = document.createElementNS(SVG, tag);
    for (var k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  }
  function icon(name) {
    var s = svg('svg', { 'class': 'ic', 'aria-hidden': 'true' });
    s.appendChild(svg('use', { href: '#i-' + name }));
    return s;
  }
  function ibtn(name, title, cls) {
    var b = el('button', 'ib' + (cls ? ' ' + cls : ''));
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.appendChild(icon(name));
    return b;
  }
  function debounce(fn, ms) {
    var t;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }
  function store(k, v) {                    // 长期记住的选择：主题、视图、来源、实时更新、读到哪了
    try {
      if (v === undefined) return localStorage.getItem(k);
      if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v);
    } catch (e) { return null; }
  }
  function tab(k, v) {                      // 只在这个标签页里记住的状态：列表的筛选和搜索词
    try {
      if (v === undefined) return JSON.parse(sessionStorage.getItem(k) || 'null');
      sessionStorage.setItem(k, JSON.stringify(v));
    } catch (e) { return null; }
  }
  function typing(e) {
    var t = e.target;
    return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable;
  }
  function terms(q) { return q.toLowerCase().split(/\s+/).filter(Boolean); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function clock(d) { return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); }
  function stamp(v) {
    if (!v) return '';
    var d = new Date(v);
    if (isNaN(d)) return '';
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function compact(n) {
    n = n || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2) + 'M';
    if (n >= 1e4) return (n / 1e3).toFixed(n >= 1e5 ? 0 : 1) + 'k';
    return String(n);
  }
  function money(x) {                       // 按 API 价格估算的美元数，和服务端的写法一致
    if (x == null) return '—';
    if (x > 0 && x < 0.01) return '$' + x.toFixed(3);
    return '$' + x.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function cost(u) { return u.cost ? money(u.cost) + (u.unpriced ? '+' : '') : u.unpriced ? '暂缺价格' : money(0); }
  function unpricedNote(u) {
    if (!u || !u.unpriced) return '';
    if (u.unpriced_models && u.unpriced_models.length) {
      return u.unpriced + ' 次回复暂缺价格（' + u.unpriced_models.join('、') + '），可在 prices.json 补充';
    }
    return u.unpriced + ' 次回复未记录模型，未计入';
  }
  function pct(x, digits) { return x == null ? '—' : (x * 100).toFixed(digits == null ? 1 : digits) + '%'; }
  function bytes(n) { return n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : (n / 1048576).toFixed(1) + ' MB'; }
  function span(a, b) {
    var ms = new Date(b) - new Date(a);
    if (!(ms >= 0)) return '';
    var m = Math.floor(ms / 60000), h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (d >= 1) return d + ' 天 ' + (h % 24) + ' 小时';
    if (h >= 1) return h + ' 小时 ' + (m % 60) + ' 分';
    return Math.max(m, 1) + ' 分钟';
  }
  function ago(ms) {
    var m = Math.round((Date.now() - ms) / 60000);
    if (m < 1) return '刚刚';
    if (m < 60) return m + ' 分钟前';
    if (m < 60 * 24) return Math.round(m / 60) + ' 小时前';
    return Math.round(m / 1440) + ' 天前';
  }
  function reveal(node) {
    for (var p = node; p; p = p.parentNode) if (p.tagName === 'DETAILS') p.open = true;
  }
  var bulkRaf1 = 0, bulkRaf2 = 0;
  function bulk(fn) {
    if (bulkRaf1) { cancelAnimationFrame(bulkRaf1); bulkRaf1 = 0; }
    if (bulkRaf2) { cancelAnimationFrame(bulkRaf2); bulkRaf2 = 0; }
    body.classList.add('bulk');
    fn();
    bulkRaf1 = requestAnimationFrame(function () {
      bulkRaf1 = 0;
      bulkRaf2 = requestAnimationFrame(function () {
        bulkRaf2 = 0;
        body.classList.remove('bulk');
      });
    });
  }
  var CRC = null;
  function hue(s) {                         // 和服务端的 zlib.crc32 一致
    if (!CRC) {
      CRC = [];
      for (var n = 0; n < 256; n++) {
        var c = n;
        for (var k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
        CRC[n] = c >>> 0;
      }
    }
    var b = new TextEncoder().encode(s || ''), x = 0xFFFFFFFF;
    for (var i = 0; i < b.length; i++) x = CRC[(x ^ b[i]) & 0xFF] ^ (x >>> 8);
    return ((x ^ 0xFFFFFFFF) >>> 0) % 360;
  }
  function acctChip(a) {
    var c = el('span', 'acct');
    c.style.setProperty('--h', hue(a.email || a.key));
    c.title = '账号：' + (a.email || a.name);
    c.appendChild(el('i'));
    c.appendChild(document.createTextNode(a.name));
    return c;
  }
  function parse(html) {                    // 服务端渲染好的片段 → 节点（template 里的脚本不会执行）
    var t = document.createElement('template');
    t.innerHTML = html;
    return [].slice.call(t.content.children);
  }
  function syncAcctSummary(menu, val, nameEl, dotEl, cntEl) {
    if (!menu) return;
    var chosen = null;
    $$('.tab', menu).forEach(function (x) {
      var on = (x.dataset.acct || '') === val;
      x.classList.toggle('on', on);
      if (on) chosen = x;
    });
    if (nameEl) {
      var sp = chosen && $('span', chosen);
      nameEl.textContent = sp ? sp.textContent : '全部账号';
    }
    if (dotEl) {
      var ic = chosen && $('i', chosen);
      if (ic && val) {
        dotEl.style.background = ic.style.background;
        dotEl.hidden = false;
      } else {
        dotEl.hidden = true;
      }
    }
    if (cntEl) {
      var sm = chosen && $('small', chosen);
      cntEl.textContent = sm ? sm.textContent : '';
    }
  }

  /* ================= 提示条 ================= */

  var toasts = null;
  function toast(text, opt) {
    opt = opt || {};
    if (!toasts) { toasts = el('div', 'toasts'); body.appendChild(toasts); }
    var t = el('div', 'toast');
    t.setAttribute('role', 'status');
    t.appendChild(el('span', null, text));
    function close() {
      if (!t.parentNode || t.classList.contains('out')) return;
      t.classList.add('out');
      setTimeout(function () { t.remove(); }, 220);
    }
    if (opt.action) {
      var b = el('button', null, opt.action);
      b.onclick = function () { close(); opt.run(); };
      t.appendChild(b);
    }
    if (opt.sticky) {
      var x = ibtn('x', '关闭', 'sm');
      x.onclick = close;
      t.appendChild(x);
    } else {
      setTimeout(close, opt.ms || (opt.action ? 7000 : 2400));
    }
    toasts.appendChild(t);
    t.close = close;
    return t;
  }

  /* ================= 复制 ================= */

  function copyText(text) {
    function legacy() {
      return new Promise(function (ok, fail) {
        var ta = el('textarea'), had = document.activeElement;
        ta.value = text;
        ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
        body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy') ? ok() : fail(); } catch (e) { fail(e); }
        ta.remove();
        if (had && had.focus) had.focus({ preventScroll: true });
      });
    }
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text).catch(legacy);
    return legacy();
  }
  function copied(btn, label) {
    var use = $('use', btn);
    if (use) {
      use.setAttribute('href', '#i-check');
      btn.classList.add('ok');
      setTimeout(function () { use.setAttribute('href', '#i-copy'); btn.classList.remove('ok'); }, 1400);
    } else {
      var old = btn.textContent;
      btn.textContent = '已复制';
      setTimeout(function () { btn.textContent = old; }, 1400);
    }
    if (label) toast('已复制' + label);
  }
  function copyFrom(btn, text, label) {
    copyText(text).then(function () { copied(btn, label); }, function () { toast('复制失败：浏览器没有给剪贴板权限'); });
  }

  /* ================= 主题 ================= */

  var themeBtn = $('#theme');
  var THEMES = [[null, 'auto', '跟随系统'], ['light', 'sun', '浅色'], ['dark', 'moon', '深色']];
  function themeIndex() {
    var cur = root.dataset.theme || null;
    for (var i = 0; i < THEMES.length; i++) if (THEMES[i][0] === cur) return i;
    return 0;
  }
  function paintTheme() {
    var t = THEMES[themeIndex()];
    themeBtn.textContent = '';
    themeBtn.appendChild(icon(t[1]));
    themeBtn.title = '主题：' + t[2] + '（点击切换）';
  }
  function nextTheme() {
    var next = THEMES[(themeIndex() + 1) % THEMES.length];
    root.classList.add('theming');
    if (next[0]) root.dataset.theme = next[0]; else delete root.dataset.theme;
    store('theme', next[0]);
    paintTheme();
    setTimeout(function () { root.classList.remove('theming'); }, 340);
  }
  if (themeBtn) { paintTheme(); themeBtn.onclick = nextTheme; }

  /* ================= 图片：淡入、放大浏览 ================= */

  function awaitImages(scope) {
    $$('img.pic', scope).forEach(function (i) { if (!(i.complete && i.naturalWidth)) i.classList.add('wait'); });
  }
  document.addEventListener('load', function (e) {
    var t = e.target;
    if (t.tagName === 'IMG' && t.classList.contains('pic')) t.classList.remove('wait');
  }, true);
  document.addEventListener('error', function (e) {
    var t = e.target;
    if (t.tagName === 'IMG' && t.classList.contains('pic')) t.remove();
  }, true);
  awaitImages(document);

  var box = null, boxList = [], boxAt = 0;
  function showBox(i) {
    boxAt = (i + boxList.length) % boxList.length;
    var im = $('img', box);
    im.classList.remove('in');
    im.onload = function () { im.classList.add('in'); };
    im.src = boxList[boxAt].currentSrc || boxList[boxAt].src;
    if (im.complete) im.classList.add('in');
    $('.box-n', box).textContent = (boxAt + 1) + ' / ' + boxList.length;
  }
  function openBox(img) {
    boxList = $$('main img.pic').filter(function (i) { return i.isConnected; });
    if (boxList.indexOf(img) < 0) boxList = [img];
    box = el('div', 'box');
    box.setAttribute('role', 'dialog');
    box.appendChild(el('img'));
    var bar = el('div', 'box-bar'), prev = ibtn('left', '上一张（←）'), next = ibtn('right', '下一张（→）'), x = ibtn('x', '关闭（Esc）');
    prev.onclick = function () { showBox(boxAt - 1); };
    next.onclick = function () { showBox(boxAt + 1); };
    x.onclick = closeBox;
    if (boxList.length > 1) bar.appendChild(prev);
    bar.appendChild(el('span', 'box-n'));
    if (boxList.length > 1) bar.appendChild(next);
    bar.appendChild(x);
    box.appendChild(bar);
    box.onclick = function (e) { if (e.target === box || e.target.tagName === 'IMG') closeBox(); };
    body.appendChild(box);
    showBox(boxList.indexOf(img));
  }
  function closeBox() {
    if (!box) return;
    var b = box;
    box = null;
    b.classList.add('out');
    setTimeout(function () { b.remove(); }, 180);
  }

  /* ================= 浮层与通用数据展示块 ================= */

  var layer = null;
  function closeLayer() {
    if (!layer) return;
    var l = layer;
    layer = null;
    l.nodes.forEach(function (n) { n.classList.remove('in'); });
    setTimeout(function () { l.nodes.forEach(function (n) { n.remove(); }); }, 260);
    if (l.focus && l.focus.focus && l.focus.isConnected) l.focus.focus();
  }
  function openLayer(cls, title) {
    closeLayer();
    var scrim = el('div', 'scrim'), panel = el('div', cls);
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', title);
    var h = el('header'), x = ibtn('x', '关闭（Esc）');
    h.appendChild(el('h2', null, title));
    x.onclick = closeLayer;
    h.appendChild(x);
    panel.appendChild(h);
    var content = el('div', 'dbody');
    panel.appendChild(content);
    scrim.onclick = closeLayer;
    body.appendChild(scrim);
    body.appendChild(panel);
    layer = { nodes: [scrim, panel], focus: document.activeElement };
    requestAnimationFrame(function () { scrim.classList.add('in'); panel.classList.add('in'); });
    x.focus();
    return content;
  }

  function field(label, value, opt) {
    opt = opt || {};
    var f = el('div', 'field'), v = el('div', 'val');
    f.appendChild(el('label', null, label));
    v.appendChild(el(opt.plain ? 'span' : 'code', null, value));
    if (opt.note) v.appendChild(el('small', null, opt.note));
    if (opt.copy !== false) {
      var b = ibtn('copy', '复制', 'sm');
      b.dataset.copy = value;
      v.appendChild(b);
    }
    f.appendChild(v);
    if (opt.hint) f.appendChild(el('small', 'hint', opt.hint));
    return f;
  }
  function section(parent, title) {
    var s = el('section');
    s.appendChild(el('h3', null, title));
    parent.appendChild(s);
    return s;
  }
  function pairs(parent, list) {
    var boxEl = el('div', 'rows');
    list.forEach(function (p) {
      if (!p[1]) return;
      var r = el('div');
      r.appendChild(el('span', null, p[0]));
      r.appendChild(el('span', null, p[1]));
      boxEl.appendChild(r);
    });
    parent.appendChild(boxEl);
  }
  function tiles(parent, list) {
    var boxEl = el('div', 'tiles');
    list.forEach(function (p) {
      if (p[2] && !p[1]) return;
      var t = el('div', 'tile');
      t.appendChild(el('b', null, typeof p[1] === 'number' ? compact(p[1]) : p[1]));
      t.appendChild(el('span', null, p[0]));
      if (typeof p[1] === 'number' && p[1] >= 1e4) t.title = p[1].toLocaleString();
      boxEl.appendChild(t);
    });
    parent.appendChild(boxEl);
  }
  function grid(heads, rows, opt) {
    opt = opt || {};
    var t = el('table', 'grid'), tr = el('tr');
    heads.forEach(function (h, i) { tr.appendChild(el('th', i ? 'n' : null, h)); });
    if (opt.share) tr.appendChild(el('th', 'share', '占比'));
    var thead = el('thead');
    thead.appendChild(tr);
    t.appendChild(thead);
    var tb = el('tbody');
    rows.forEach(function (r, k) {
      var row = el('tr');
      r.forEach(function (v, i) {
        var td = el('td', i ? 'n' : null);
        if (v && v.nodeType) td.appendChild(v); else td.textContent = v;
        row.appendChild(td);
      });
      if (opt.share) {
        var td = el('td', 'share'), track = el('span', 'track'), fill = el('i');
        var x = opt.share[k];
        fill.style.width = Math.max(x > 0 ? 1.5 : 0, Math.round(x * 1000) / 10) + '%';
        if (opt.colors) fill.style.background = opt.colors[k];
        track.appendChild(fill);
        td.appendChild(track);
        td.title = pct(x);
        row.appendChild(td);
      }
      tb.appendChild(row);
    });
    t.appendChild(tb);
    var w = el('div', 'tw');
    w.appendChild(t);
    return w;
  }
  function swatch(cls, text) {
    var s = el('span', 'sw');
    s.appendChild(el('i', cls));
    s.appendChild(document.createTextNode(text));
    return s;
  }
  var PARTS = ['输入', '输出', '读缓存', '写缓存', '网页搜索'];
  function costBar(parent, parts) {
    var total = parts.reduce(function (a, b) { return a + b; }, 0);
    if (!total) return;
    var bar = el('div', 'stack'), legend = el('div', 'legend');
    parts.forEach(function (x, i) {
      if (!x) return;
      var seg = el('i', 'c' + (i + 1));
      seg.style.flexGrow = x / total;
      seg.title = PARTS[i] + '：' + money(x) + '（' + pct(x / total) + '）';
      bar.appendChild(seg);
      var item = swatch('c' + (i + 1), PARTS[i] + ' ');
      item.appendChild(el('b', null, money(x)));
      legend.appendChild(item);
    });
    parent.appendChild(bar);
    parent.appendChild(legend);
  }

  /* ================= 实时更新（SSE） ================= */

  var pull = null, pulling = false, again = false, lastPull = 0, hint = null;
  var liveOn = store('live') !== '0', es = null, failures = 0;
  var GAP = body.classList.contains('stats') ? 4000 : body.classList.contains('index') ? 1500 : 800;

  function refresh(manual) {
    if (!live || !pull) return;
    if (pulling) { again = again || !manual; return; }
    pulling = true;
    lastPull = Date.now();
    var btn = manual && $('[data-act="refresh"]'), t0 = Date.now();
    if (btn) btn.classList.add('spin');
    if (hint) { hint.close(); hint = null; }
    pull(manual).then(function (res) {
      if (manual) toast(res && res.changed ? res.text : '已是最新 · ' + clock(new Date()), res && res.changed && res.action ? res.action : null);
    }).catch(function () {
      if (manual) toast('刷新失败：本地服务没有响应，请确认 Sessiontool 的窗口还开着。', { ms: 5000 });
    }).then(function () {
      setTimeout(function () {
        pulling = false;
        if (btn) btn.classList.remove('spin');
        if (again) { again = false; later(); }
      }, btn ? Math.max(0, 500 - (Date.now() - t0)) : 0);
    });
  }
  var timer = null;
  function later() {
    if (timer) return;
    timer = setTimeout(function () { timer = null; refresh(false); }, Math.max(0, GAP - (Date.now() - lastPull)));
  }
  function paintLive(state) {
    $$('[data-act="live"]').forEach(function (b) {
      b.classList.toggle('on', state === 'on');
      b.classList.toggle('off', state === 'off');
      b.classList.toggle('err', state === 'err');
      b.setAttribute('aria-pressed', state !== 'off');
      $('span', b).textContent = state === 'off' ? '已暂停' : state === 'err' ? '未连接' : '实时';
    });
  }
  function changed(e) {
    var j = JSON.parse(e.data);
    failures = 0;
    paintLive(liveOn ? 'on' : 'off');
    if (j.sig === body.dataset.sig) return;
    if (body.classList.contains('stats')) body.dataset.sig = j.sig;
    if (liveOn) { later(); return; }
    if (!hint) hint = toast('有新的记录', { action: '更新', run: function () { hint = null; refresh(true); }, sticky: true });
  }
  function connect() {
    if (!live || es || document.hidden || !window.EventSource) return;
    var pg = body.classList.contains('session') ? '?page=' + encodeURIComponent(body.dataset.page) : '';
    es = new EventSource('/api/live' + pg);
    es.addEventListener('hello', changed);
    es.addEventListener('change', changed);
    es.onerror = function () {
      paintLive('err');
      if (++failures > 20) disconnect();
    };
  }
  function disconnect() { if (es) { es.close(); es = null; } }
  function setLive(on) {
    liveOn = on;
    store('live', on ? '1' : '0');
    paintLive(on ? 'on' : 'off');
    if (on && es && hint) refresh(false);
  }
  if (live) {
    paintLive(liveOn ? 'on' : 'off');
    document.addEventListener('visibilitychange', function () { if (document.hidden) disconnect(); else connect(); });
    window.addEventListener('pagehide', disconnect);
    setTimeout(connect, 300);
  }

  /* ================= 来源切换（Claude / Codex / Gemini / 全部） ================= */

  var srcSeg = $('#src'), curSource = 'all';
  function srcOrder() {
    return srcSeg ? $$('button', srcSeg).map(function (b) { return b.dataset.s; }) : ['all'];
  }
  function pickSource(v, user) {
    if (!srcSeg) return;
    var order = srcOrder();
    if (order.indexOf(v) < 0) v = order[0] || 'all';
    curSource = v;
    body.dataset.src = v;
    $$('button', srcSeg).forEach(function (b) { b.classList.toggle('on', b.dataset.s === v); });
    if (user) {
      store('src', v);
      if (ST.onSource) ST.onSource(v);
    }
  }
  function bindSrcSeg(elSeg) {
    srcSeg = elSeg;
    if (!elSeg || elSeg.dataset.bound) return;
    elSeg.dataset.bound = '1';
    elSeg.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (b) pickSource(b.dataset.s, true);
    });
  }
  bindSrcSeg(srcSeg);
  function srcParam() { return curSource === 'all' ? '' : curSource; }
  function srcHint() {
    return srcSeg ? '切换 ' + srcOrder().map(function (k) { return k === 'all' ? '全部' : (SRC[k] ? SRC[k].name : k); }).join(' / ')
      : '切换 Claude / Codex / Gemini / 全部';
  }

  /* ================= 快捷键说明与统一点击/按键入口 ================= */

  function openKeys() {
    var rows = [['/', '聚焦搜索框'], ['R', '立刻重读磁盘'], ['L', '暂停或继续实时更新'], ['?', '打开这张快捷键表'], ['Esc', '关闭浮层、清空搜索']];
    if (ST.keys) rows = rows.concat(typeof ST.keys === 'function' ? ST.keys() : ST.keys);
    var b = openLayer('modal', '键盘快捷键'), list = el('div', 'keys');
    rows.forEach(function (r) {
      var d = el('div');
      d.appendChild(el('span', null, r[1]));
      var k = el('span');
      r[0].split('  ').forEach(function (key) { k.appendChild(el('kbd', null, key)); });
      d.appendChild(k);
      list.appendChild(d);
    });
    b.appendChild(list);
  }

  var actions = {
    refresh: function () { refresh(true); },
    keys: openKeys,
    live: function () { setLive(!liveOn); toast(liveOn ? '已开启实时更新：有新记录时自动显示' : '已暂停实时更新'); }
  };

  document.addEventListener('click', function (e) {
    var t = e.target;
    $$('details.menu[open]').forEach(function (m) { if (!m.contains(t)) m.open = false; });
    var c = t.closest('[data-copy]');
    if (c) { e.preventDefault(); copyFrom(c, c.dataset.copy, c.dataset.copied); return; }
    var a = t.closest('[data-act]');
    if (a && actions[a.dataset.act]) { e.preventDefault(); actions[a.dataset.act](a, e); return; }
    if (t.classList.contains('pic')) { openBox(t); return; }
    if (t.classList.contains('copy')) {
      var src = $('.body', t.closest('.msg'));
      copyFrom(t, src ? src.innerText : '');
      return;
    }
    var cc = t.closest('.cc');
    if (cc) copyFrom(cc, $('pre', cc.parentNode).textContent);
  });

  document.addEventListener('keydown', function (e) {
    if (box) {
      if (e.key === 'Escape') closeBox();
      else if (e.key === 'ArrowLeft') showBox(boxAt - 1);
      else if (e.key === 'ArrowRight') showBox(boxAt + 1);
      else return;
      e.preventDefault();
      e.stopImmediatePropagation();
      return;
    }
    if (e.key === 'Escape') {
      if (layer) { closeLayer(); e.stopImmediatePropagation(); return; }
      $$('details.menu[open]').forEach(function (m) { m.open = false; });
      return;
    }
    if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === '?') { e.preventDefault(); openKeys(); }
    else if (layer) return;
    else if (e.key === 'r' && live) { e.preventDefault(); refresh(true); }
    else if (e.key === 'l' && live) { e.preventDefault(); actions.live(); }
    else if (e.key === 's' && srcSeg) {
      e.preventDefault();
      var order = srcOrder();
      pickSource(order[(order.indexOf(curSource) + 1) % order.length], true);
    }
  }, true);

  var ST = window.ST = {
    body: body, root: root, mainEl: mainEl, live: live, SVG: SVG, WEEK: WEEK, SRC: SRC,
    $: $, $$: $$, mainScroller: mainScroller, scrollYOf: scrollYOf, viewHOf: viewHOf, scrollHOf: scrollHOf,
    scrollToY: scrollToY, scrollByY: scrollByY, onMainScroll: onMainScroll,
    el: el, svg: svg, icon: icon, ibtn: ibtn, debounce: debounce, store: store, tab: tab, typing: typing, terms: terms,
    pad: pad, clock: clock, stamp: stamp, compact: compact, money: money, cost: cost, unpricedNote: unpricedNote,
    pct: pct, bytes: bytes, span: span, ago: ago, reveal: reveal, bulk: bulk, hue: hue, acctChip: acctChip, parse: parse,
    syncAcctSummary: syncAcctSummary, toast: toast, copyFrom: copyFrom, awaitImages: awaitImages,
    openLayer: openLayer, closeLayer: closeLayer, hasModal: function () { return !!(box || layer); },
    field: field, section: section, pairs: pairs, tiles: tiles, grid: grid, swatch: swatch, costBar: costBar,
    refresh: refresh, setPull: function (fn) { pull = fn; },
    srcSeg: function () { return srcSeg; }, bindSrcSeg: bindSrcSeg, source: function () { return curSource; },
    srcOrder: srcOrder, pickSource: pickSource, srcParam: srcParam, srcHint: srcHint, onSource: null,
    actions: actions, keys: null, onToolLoaded: null
  };
})();
