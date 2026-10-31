// 服务模式和导出的独立文件共用这一份脚本；独立文件里没有的控件都先判断再用
(function () {
  'use strict';

  /* ================= 小工具 ================= */

  var body = document.body, root = document.documentElement;
  var isIndex = body.classList.contains('index'), isSession = body.classList.contains('session');
  var isStats = body.classList.contains('stats');
  var live = !!body.dataset.state;          // 有本地服务可以问（导出的独立文件没有）
  var SVG = 'http://www.w3.org/2000/svg';
  var WEEK = '一二三四五六日';

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return [].slice.call((r || document).querySelectorAll(s)); }
  var mainEl = $('main');
  function mainScroller() {
    return mainEl && getComputedStyle(mainEl).overflowY === 'auto' ? mainEl : window;
  }
  function scrollYOf() {
    var s = mainScroller();
    return s === window ? window.scrollY : s.scrollTop;
  }
  function viewHOf() {
    var s = mainScroller();
    return s === window ? window.innerHeight : s.clientHeight;
  }
  function scrollHOf() {
    var s = mainScroller();
    return s === window ? root.scrollHeight : s.scrollHeight;
  }
  function scrollToY(y) {
    var s = mainScroller();
    if (s === window) window.scrollTo(0, y); else s.scrollTop = y;
  }
  function scrollByY(dy) {
    var s = mainScroller();
    if (s === window) window.scrollBy(0, dy); else s.scrollTop += dy;
  }
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
    var s = svg('svg', { 'class': 'ic', 'aria-hidden': 'true' }), u = svg('use', { href: '#i-' + name });
    s.appendChild(u);
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
    if (x >= 1000) return '$' + Math.round(x).toLocaleString('en-US');
    return '$' + (x >= 0.01 || !x ? x.toFixed(2) : x.toFixed(3));
  }
  function cost(u) { return u.cost ? money(u.cost) + (u.unpriced ? '+' : '') : u.unpriced ? '价格未知' : money(0); }
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
  // 一次开合很多折叠块时关掉动画；取消上一次尚未跑完的帧回调，避免连续快速操作时提前撤掉 .bulk
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
  // 和服务端的 zlib.crc32 一致：账号、项目的颜色由名字决定，页面脚本画出来的和服务端画的一样
  var CRC = null;
  function hue(s) {
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
    // 老办法：借一个看不见的输入框。新接口不可用或被拒绝时用它兜底
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
  // 复制成功后的反馈：图标按钮变成对勾，文字按钮改字；带名字的再弹一条提示
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

  /* ================= 主题：跟随系统 → 浅色 → 深色 ================= */

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
    root.classList.add('theming');          // 换色的一瞬间让颜色过渡一下，平时不带这个过渡
    if (next[0]) root.dataset.theme = next[0]; else delete root.dataset.theme;
    store('theme', next[0]);
    paintTheme();
    setTimeout(function () { root.classList.remove('theming'); }, 340);
  }
  if (themeBtn) { paintTheme(); themeBtn.onclick = nextTheme; }

  /* ================= 图片：淡入、放大浏览 ================= */

  // 还没读到的图先隐藏，读到再淡入；原文件已经不在的直接去掉，不留破图
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

  /* ================= 浮层：详情抽屉、快捷键说明 ================= */

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
    var box = el('div', 'rows');
    list.forEach(function (p) {
      if (!p[1]) return;
      var r = el('div');
      r.appendChild(el('span', null, p[0]));
      r.appendChild(el('span', null, p[1]));
      box.appendChild(r);
    });
    parent.appendChild(box);
  }
  function tiles(parent, list) {
    var box = el('div', 'tiles');
    list.forEach(function (p) {
      if (p[2] && !p[1]) return;            // 第三项为真：数量是 0 就不占位置
      var t = el('div', 'tile');
      t.appendChild(el('b', null, typeof p[1] === 'number' ? compact(p[1]) : p[1]));
      t.appendChild(el('span', null, p[0]));
      if (typeof p[1] === 'number' && p[1] >= 1e4) t.title = p[1].toLocaleString();
      box.appendChild(t);
    });
    parent.appendChild(box);
  }
  // 一张数字表：第一列是名字，其余靠右对齐；share 给出时最后加一列占比条
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
  // 名字前面一小块颜色：图上的系列在表里的对应
  function swatch(cls, text) {
    var s = el('span', 'sw');
    var i = el('i', cls);
    s.appendChild(i);
    s.appendChild(document.createTextNode(text));
    return s;
  }
  // 费用分项：一条横向的堆叠条，下面是图例
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

  var PERMISSION = { 'default': '每次询问', acceptEdits: '自动接受编辑', plan: '计划模式', auto: '自动判断', bypassPermissions: '跳过权限确认',
    never: '从不询问', 'on-request': '需要时询问', 'on-failure': '失败时询问', untrusted: '不受信任的命令要询问' };
  var STATUS = { completed: '已完成', review_ready: '等你过目', blocked: '受阻', in_progress: '进行中', needs_input: '等你处理', failed: '失败' };
  var ORIGIN = { codex_exec: '命令行（codex exec）', 'codex-tui': '终端界面', codex_cli_rs: '命令行', vscode: 'VS Code 扩展', codex_vscode: 'VS Code 扩展',
    cli: '命令行（Claude Code）', 'sdk-cli': '命令行（SDK）', 'claude-vscode': 'VS Code 扩展',
    'claude-desktop': 'Claude 桌面应用', 'claude-desktop-3p': 'Claude 桌面应用', 'local-agent': 'Claude 桌面应用', local_agent: 'Claude 桌面应用' };

  function usageSection(b, u, agents) {
    var s = section(b, '费用与用量');
    var hero = el('div', 'hero');
    hero.appendChild(el('b', null, cost(u)));
    hero.appendChild(el('span', null, '按 API 价格估算 · ' + u.n + ' 次回复' + (agents ? '（含 ' + agents + ' 个子代理的）' : '')));
    s.appendChild(hero);
    costBar(s, u.parts);
    tiles(s, [['缓存命中率', pct(u.rate)], ['输出', u.output], ['未缓存的输入', u.input], ['读缓存', u.cache_read],
      ['写缓存', u.cache_write], ['其中思考', u.thinking, 1], ['网页搜索', u.web, 1]]);
    s.appendChild(el('small', 'hint', '订阅不按 token 计费，这是同样的用量按 API 计价的金额。缓存命中率是读缓存占全部输入的比例。'
      + (u.unpriced ? u.unpriced + ' 次回复的模型没有价格，没有计入。' : '')));
    if (u.models.length) {
      s = section(b, '按模型');
      s.appendChild(grid(['模型', '回复', '输出', '命中率', '费用'], u.models.map(function (m) {
        return [m.name || '（未知）', m.n, compact(m.output), pct(m.rate, 0), m.priced ? money(m.cost) : '—'];
      }), { share: u.models.map(function (m) { return u.cost ? m.cost / u.cost : 0; }) }));
    }
    if (u.efforts.length) {
      s = section(b, '按推理强度');
      s.appendChild(grid(['推理强度', '回复', '输出', '费用'], u.efforts.map(function (e) {
        return [e.effort || '（未记录）', e.n, compact(e.output), money(e.cost)];
      }), { share: u.efforts.map(function (e) { return u.cost ? e.cost / u.cost : 0; }) }));
    }
  }

  function fillInfo(b, d) {
    var codex = d.src === 'codex';
    var t = el('div', 'dtitle');
    t.appendChild(el('strong', null, d.title));
    var tags = el('div', 'dtags');
    tags.appendChild(el('span', 'badge', d.proj));
    if (d.account) tags.appendChild(acctChip(d.account));
    if (codex) tags.appendChild(el('span', 'badge cx', 'Codex'));
    if (d.parent) tags.appendChild(el('span', 'badge', '复刻'));
    if (d.archived) tags.appendChild(el('span', 'badge', '已归档'));
    if (d.orphan) tags.appendChild(el('span', 'badge', '不在应用列表中'));
    t.appendChild(tags);
    b.appendChild(t);
    if (d.status) {
      var sb = el('div', 'statusbox');
      sb.appendChild(el('b', null, '应用记下的最近状态：' + (STATUS[d.status.status_category] || d.status.status_category || '')));
      if (d.status.status_detail) sb.appendChild(el('p', null, d.status.status_detail));
      if (d.status.needs_action) sb.appendChild(el('p', 'err', '需要处理：' + d.status.needs_action));
      b.appendChild(sb);
    }
    if (!isSession) {
      var go = el('a', 'go', '打开这个会话');
      go.href = '/s/' + d.page;
      b.appendChild(go);
    }

    var s = section(b, '标识');
    if (d.id) s.appendChild(field('应用会话 ID', d.id, { hint: '在 Claude 里提到这个会话时用它' }));
    s.appendChild(field(codex ? '线程 ID' : '记录 ID', d.cli, { hint: codex ? 'Codex 用它找到这个会话' : '当前记录文件的编号，可以用来恢复会话' }));
    d.files.filter(function (f) { return !f.current; }).forEach(function (f) { s.appendChild(field('更早的记录 ID', f.id)); });
    s.appendChild(field('恢复命令', d.resume, { hint: '在终端里的项目文件夹下运行' }));
    if (d.link) s.appendChild(field('应用链接', d.link));

    if (d.account || d.org || d.store) {
      s = section(b, '账号');
      if (d.account && d.account.email) s.appendChild(field('邮箱', d.account.email));
      if (d.account && d.account.id) s.appendChild(field('账号 ID', d.account.id));
      if (d.org) s.appendChild(field('组织 ID', d.org));
      pairs(s, [['multi-claude 配置', d.store], [codex ? 'Codex 版本' : 'Claude Code 版本', d.version], ['从哪里开始的', ORIGIN[d.origin] || d.origin]]);
    }

    s = section(b, '位置');
    s.appendChild(field('项目文件夹', d.cwd || '（未知）'));
    d.files.forEach(function (f) { s.appendChild(field(f.current ? '记录文件（当前）' : '记录文件', f.path, { note: bytes(f.size) })); });

    s = section(b, '时间');
    pairs(s, [['创建', stamp(d.created)], ['第一条消息', stamp(d.first)], ['最后活动', stamp(d.last)], ['前后跨度', span(d.first, d.last)]]);

    if (d.usage && d.usage.n) usageSection(b, d.usage, d.agents);

    s = section(b, '模型与设置');
    pairs(s, [['当前模型', d.model], ['推理强度', d.effort], [codex ? '审批' : '权限模式', PERMISSION[d.permission] || d.permission],
      ['完成的轮数', d.turns != null ? String(d.turns) : ''], ['写入过的分支', (d.branches || []).join('、')]]);

    s = section(b, '数量');
    var c = d.counts;
    tiles(s, [['提问', c.prompts], ['答复', c.replies], ['工具调用', c.tools], ['工具截图', c.shots, 1], ['你发的图片', c.images, 1],
      ['发给你的文件', c.sent, 1], ['修改的文件', c.changed, 1], ['上下文压缩', c.compact, 1], ['改写', c.branch, 1],
      ['记录文件', c.records], ['记录大小', bytes(d.size)]]);

    if (d.tools && d.tools.length) {
      s = section(b, '用得最多的工具');
      var bars = el('div', 'bars'), max = d.tools[0][1];
      d.tools.forEach(function (x) {
        var r = el('div'), track = el('span', 'track'), fill = el('i');
        var name = el('code', null, x[0]);
        name.title = x[0];
        fill.style.width = Math.max(2, Math.round(x[1] / max * 100)) + '%';
        track.appendChild(fill);
        r.appendChild(name);
        r.appendChild(track);
        r.appendChild(el('span', null, String(x[1])));
        bars.appendChild(r);
      });
      s.appendChild(bars);
    }

    if (d.first_prompt) {
      s = section(b, '提问');
      s.appendChild(field('第一条', d.first_prompt, { plain: true, copy: false }));
      if (d.last_prompt && d.last_prompt !== d.first_prompt) s.appendChild(field('最近一条', d.last_prompt, { plain: true, copy: false }));
    }

    var rel = (d.parent ? [['复刻自', d.parent]] : []).concat((d.children || []).map(function (x) { return ['它的复刻', x]; }));
    if (rel.length) {
      s = section(b, '相关会话');
      rel.forEach(function (p) {
        var a = el('a', 'rel');
        a.href = '/s/' + p[1].page;
        a.appendChild(el('small', null, p[0]));
        a.appendChild(el('span', null, p[1].title));
        if (live) s.appendChild(a); else s.appendChild(el('div', 'rel', p[0] + '：' + p[1].title));
      });
    }
  }
  function openInfo(page) {
    var b = openLayer('drawer', '会话详情');
    var own = $('#info');
    if (own && (!page || page === body.dataset.page)) { fillInfo(b, JSON.parse(own.textContent)); return; }
    b.appendChild(el('div', 'shimmer'));
    fetch('/api/info?page=' + encodeURIComponent(page)).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (d) {
      if (!b.isConnected) return;
      b.textContent = '';
      fillInfo(b, d);
    }).catch(function () { b.textContent = '读取失败：本地服务没有响应。'; });
  }

  function openKeys() {
    var rows = [['/', '聚焦搜索框'], ['R', '立刻重读磁盘'], ['L', '暂停或继续实时更新'], ['?', '打开这张快捷键表'], ['Esc', '关闭浮层、清空搜索']];
    if (isIndex) rows = rows.concat([['J  K  ↓  ↑', '在会话和搜索结果之间移动'], ['Enter', '打开选中的会话'], ['I', '选中会话的详情'],
      ['C', '复制选中会话的 ID'], ['S', '切换 Claude / Codex / 全部']]);
    if (isSession) rows = rows.concat([['J  K', '下一条 / 上一条你的提问'], ['1  2  3', '完整 / 对话 / 结果视图'],
      ['E', '折起或展开当前这一轮的过程'], ['I', '会话详情'], ['Enter  Shift+Enter', '搜索时跳到下一处 / 上一处'],
      ['←  →', '放大图片时切换上一张 / 下一张']]);
    if (isStats) rows = rows.concat([['S', '切换 Claude / Codex / 全部']]);
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

  /* ================= 工具调用：展开时再向本地服务要 ================= */

  function codeBox(text, cls) {
    var w = el('div', 'code');
    w.appendChild(el('pre', cls, text));
    return w;
  }
  function fillTool(d) {
    if (d.dataset.done || !d.dataset.u) return;
    d.dataset.done = '1';
    var tc = $('.tc', d);
    tc.textContent = '';
    tc.appendChild(el('div', 'shimmer'));
    fetch(d.dataset.u).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (j) {
      tc.textContent = '';
      var inp = j.input;
      if (inp && typeof inp === 'object' && !Array.isArray(inp)) {
        Object.keys(inp).forEach(function (k) {
          var v = inp[k], s = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
          if (v == null) return;
          if (s.length < 90 && s.indexOf('\n') < 0) {
            var row = el('div', 'kv');
            row.appendChild(el('span', 'k', k));
            row.appendChild(el('span', 'v', s));
            tc.appendChild(row);
          } else {
            tc.appendChild(el('div', 'k', k));
            tc.appendChild(codeBox(s));
          }
        });
      } else if (inp != null) {
        tc.appendChild(codeBox(JSON.stringify(inp, null, 2)));
      }
      if (j.result == null) {
        tc.appendChild(el('div', 'k', '（没有记录到输出）'));
      } else if (j.result || !j.images.length) {
        tc.appendChild(el('div', 'k', j.error ? '输出（失败）' : '输出'));
        tc.appendChild(codeBox(j.result || '（空）', j.error ? 'err' : null));
      }
      if (j.full) {
        tc.appendChild(el('div', 'k', '完整输出（保存在 tool-results 里的文件）'));
        tc.appendChild(codeBox(j.full));
      }
      if (j.images.length) {
        var pics = el('div', 'pics');
        j.images.forEach(function (src) {
          var im = el('img', 'pic wait');
          im.loading = 'lazy'; im.alt = '截图'; im.src = src;
          pics.appendChild(im);
        });
        tc.appendChild(pics);
      }
      if (activeQ) highlight(activeQ, d);       // 从搜索结果跳到这次工具调用时，把命中的地方标出来
    }).catch(function () {
      d.dataset.done = '';
      tc.textContent = '加载失败，收起后再展开可重试。';
    });
  }
  // 只有手动点击单个折叠块摘要时才临时挂上 .anim 做高度过渡，避免数千个折叠块常驻伪元素过渡拖慢切视图
  function armDetailsAnim(e) {
    if (e.target.closest && e.target.closest('a, button')) return;
    var s = e.target.closest && e.target.closest('summary');
    var d = s && s.parentNode;
    if (!d || d.tagName !== 'DETAILS' || d.classList.contains('menu')) return;
    d.classList.add('anim');
    void d.offsetHeight;
    clearTimeout(d._at);
    d._at = setTimeout(function () { d.classList.remove('anim'); }, 1200);
  }
  document.addEventListener('pointerdown', armDetailsAnim, true);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') armDetailsAnim(e);
  }, true);
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (!d.classList) return;
    if (d.classList.contains('anim')) {
      clearTimeout(d._at);
      d._at = setTimeout(function () { d.classList.remove('anim'); }, 280);
    }
    if (d.classList.contains('tool') && d.open) fillTool(d);
  }, true);

  // 代码块右上角的“复制”：鼠标移上去时才放按钮，页面上可能有几百个代码块
  document.addEventListener('mouseover', function (e) {
    var c = e.target.closest && e.target.closest('.code');
    if (c && !c.dataset.cc) {
      c.dataset.cc = '1';
      c.appendChild(ibtn('copy', '复制', 'sm cc'));
    }
  });

  /* ================= 会话内搜索 ================= */

  var marks = [], cur = -1, findBar = null, activeQ = '', view = 'full';
  function clearMarks() {
    marks.forEach(function (m) {
      var p = m.parentNode;
      if (!p) return;
      p.replaceChild(document.createTextNode(m.textContent), m);
      p.normalize();
    });
    marks = []; cur = -1;
    if (findBar) { findBar.remove(); findBar = null; }
  }
  function go(step, quiet) {
    if (!marks.length) return;
    if (cur >= 0 && marks[cur]) marks[cur].classList.remove('cur');
    cur = (cur + step + marks.length) % marks.length;
    var m = marks[cur];
    m.classList.add('cur');
    if (!quiet) {
      reveal(m);
      m.scrollIntoView({ block: 'center' });
    }
    findBar.firstChild.textContent = (cur + 1) + ' / ' + marks.length;
  }
  function markAll(scope, word) {
    var walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT), nodes = [], n;
    while ((n = walker.nextNode())) {
      if (n.parentNode.tagName !== 'MARK' && n.nodeValue.toLowerCase().indexOf(word) >= 0) nodes.push(n);
    }
    nodes.forEach(function (node) {
      var i;
      while ((i = node.nodeValue.toLowerCase().indexOf(word)) >= 0) {
        var hit = node.splitText(i);
        node = hit.splitText(word.length);
        var mk = el('mark', null, hit.nodeValue);
        hit.parentNode.replaceChild(mk, hit);
        marks.push(mk);
      }
    });
  }
  // near：优先停在这个元素里的第一处；quiet：只更新标记，不滚动页面（更新内容后用）
  function highlight(q, near, quiet) {
    var keep = quiet ? cur : -1;
    clearMarks();
    activeQ = q;
    var words = terms(q);
    if (!words.length) return;
    $$('main .msg .body, main .step > .body, main .sent, main details.fold > .body, main details.tool[open] > .tc').forEach(function (scope) {
      if (isSession && view !== 'full' && scope.closest(view === 'result'
        ? 'details.steps, .step, details.tools, details.think, details.sys'
        : 'details.tools, details.think, details.sys')) return;
      words.forEach(function (w) { markAll(scope, w); });
    });
    marks.sort(function (a, b) { return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1; });
    findBar = el('div', 'find');
    findBar.appendChild(el('span', null, marks.length ? '' : '对话文字里没有找到（工具调用展开后才会被搜索）'));
    if (marks.length) {
      var up = ibtn('up', '上一处（Shift+Enter）', 'sm'), down = ibtn('down', '下一处（Enter）', 'sm');
      up.onclick = function () { go(-1); };
      down.onclick = function () { go(1); };
      findBar.appendChild(up);
      findBar.appendChild(down);
    }
    body.appendChild(findBar);
    if (!marks.length) return;
    var start = 0;
    if (keep >= 0) start = Math.min(keep, marks.length - 1);
    else if (near) for (var k = 0; k < marks.length; k++) if (near.contains(marks[k])) { start = k; break; }
    cur = start - 1;
    go(1, quiet);
  }

  /* ================= 实时更新：服务推送变化，页面只换有变化的部分 ================= */

  // 各页面自己的“取最新内容”：pull(fresh) → Promise<{changed, text, action}>。fresh 让服务跳过节流立刻重读磁盘
  var pull = null, pulling = false, again = false, lastPull = 0, hint = null;
  var liveOn = store('live') !== '0', es = null, failures = 0;
  var GAP = isStats ? 4000 : isIndex ? 1500 : 800;      // 两次自动更新至少隔这么久：会话正在跑时变化每秒都有

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
      // 转圈至少转半秒，太快的话看不出按下去有没有反应
      setTimeout(function () {
        pulling = false;
        if (btn) btn.classList.remove('spin');
        if (again) { again = false; later(); }
      }, btn ? Math.max(0, 500 - (Date.now() - t0)) : 0);
    });
  }
  var timer = null;
  function later() {                        // 离上次更新太近就等一等再取，期间的变化合成一次
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
    if (isStats) body.dataset.sig = j.sig;
    if (liveOn) { later(); return; }
    if (!hint) hint = toast('有新的记录', { action: '更新', run: function () { hint = null; refresh(true); }, sticky: true });
  }
  // 只有看得见的页面才连着：浏览器对同一个地址最多开六条连接，开很多标签页时不能让后台的页面占满
  function connect() {
    if (!live || es || document.hidden || !window.EventSource) return;
    es = new EventSource('/api/live' + (isSession ? '?page=' + encodeURIComponent(body.dataset.page) : ''));
    es.addEventListener('hello', changed);
    es.addEventListener('change', changed);
    es.onerror = function () {
      paintLive('err');
      if (++failures > 20) disconnect();    // 服务关掉了：重试一阵就不再连
    };
  }
  function disconnect() {
    if (es) { es.close(); es = null; }
  }
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
    setTimeout(connect, 300);               // 等页面先画完再连
  }

  /* ================= 来源：Claude / Codex / 全部 ================= */

  var srcSeg = $('#src'), source = 'all', onSource = null;
  // user：是你点的（记住选择，并让页面重新筛选）；打开页面时恢复上次的选择不算
  function pickSource(v, user) {
    if (!srcSeg) return;
    if (['claude', 'codex', 'all'].indexOf(v) < 0) v = 'claude';
    source = v;
    body.dataset.src = v;
    $$('button', srcSeg).forEach(function (b) { b.classList.toggle('on', b.dataset.s === v); });
    if (user) {
      store('src', v);
      if (onSource) onSource(v);
    }
  }
  if (srcSeg) {
    srcSeg.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (b) pickSource(b.dataset.s, true);
    });
  }
  function srcParam() { return source === 'all' ? '' : source; }

  /* ================= 点击与按键的统一入口 ================= */

  var ACTIONS = {
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
    if (a && ACTIONS[a.dataset.act]) { e.preventDefault(); ACTIONS[a.dataset.act](a, e); return; }
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
    if (box) {                              // 放大图片时，按键只管图片
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
    else if (layer) return;                 // 浮层开着时别的快捷键不起作用
    else if (e.key === 'r' && live) { e.preventDefault(); refresh(true); }
    else if (e.key === 'l' && live) { e.preventDefault(); ACTIONS.live(); }
    else if (e.key === 's' && srcSeg) {
      e.preventDefault();
      var order = ['claude', 'codex', 'all'];
      pickSource(order[(order.indexOf(source) + 1) % order.length], true);
    }
  }, true);

  /* ================= 会话页 ================= */

  if (isSession) {
    var flow = $('#flow'), page = body.dataset.page || '';
    var posKey = 'pos:' + (page || location.pathname);

    // 三种视图全走纯 CSS 切换，不遍历改写任何 <details> 的 open：完整 / 对话（隐藏工具与思考）/ 结果（隐藏整个中间过程）
    var VIEWS = ['full', 'chat', 'result'];
    var views = $$('#view button');
    function setView(v, keep) {
      if (VIEWS.indexOf(v) < 0) v = 'full';
      view = v;
      views.forEach(function (b) { b.classList.toggle('on', b.dataset.v === v); });
      body.classList.toggle('chat', v === 'chat');
      body.classList.toggle('result', v === 'result');
      if (keep) {
        store('view', v);
        if (activeQ) highlight(activeQ, null, true);
      }
    }
    function switchView(v) {
      if (VIEWS.indexOf(v) < 0) v = 'full';
      if (v === view) return;
      keepPlace(function () { setView(v, true); });
    }
    views.forEach(function (b) { b.onclick = function () { switchView(b.dataset.v); }; });

    // 顶部进度条、平滑滚动与右下角浮动的“回到开头 / 滑到底部”按钮
    var progEl = $('.progress'), floats = el('div', 'floats');
    var totop = ibtn('up', '回到开头'), toend = ibtn('down', '滑到底部');
    totop.dataset.act = 'top';
    toend.dataset.act = 'end';
    floats.appendChild(totop);
    floats.appendChild(toend);
    body.appendChild(floats);

    var scrollAnim = 0;
    function stopSmoothScroll() {
      if (scrollAnim) { cancelAnimationFrame(scrollAnim); scrollAnim = 0; }
    }
    function barClearance() {
      var b = $('.bar');
      return (b ? b.offsetHeight : 56) + 20;
    }
    function smoothScrollTo(destY, animate) {
      stopSmoothScroll();
      var maxY = Math.max(0, scrollHOf() - viewHOf());
      var targetY = Math.max(0, Math.min(maxY, destY));
      var startY = scrollYOf(), diff = targetY - startY, dist = Math.abs(diff);
      var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (!animate || reduced || dist < 4) {
        scrollToY(targetY);
        syncProgress();
        return;
      }
      var dur = Math.min(420, Math.max(220, 180 + Math.sqrt(dist) * 2.2)), t0 = performance.now();
      function frame(now) {
        var p = Math.min(1, (now - t0) / dur);
        var eased = 1 - Math.pow(1 - p, 3);
        scrollToY(startY + diff * eased);
        syncProgress();
        if (p < 1) scrollAnim = requestAnimationFrame(frame);
        else scrollAnim = 0;
      }
      scrollAnim = requestAnimationFrame(frame);
    }
    function scrollNodeIntoView(node, animate) {
      var s = mainScroller(), baseTop = s === window ? 0 : s.getBoundingClientRect().top;
      var destY = scrollYOf() + (node.getBoundingClientRect().top - baseTop) - barClearance();
      smoothScrollTo(destY, animate);
    }
    if (mainEl) {
      mainEl.addEventListener('wheel', stopSmoothScroll, { passive: true });
      mainEl.addEventListener('touchstart', stopSmoothScroll, { passive: true });
      mainEl.addEventListener('pointerdown', function (e) { if (e.target === mainEl) stopSmoothScroll(); });
    }
    window.addEventListener('wheel', stopSmoothScroll, { passive: true });
    window.addEventListener('touchstart', stopSmoothScroll, { passive: true });

    var progRaf = 0;
    function syncProgress() {
      var y = scrollYOf(), vh = viewHOf(), sh = scrollHOf(), max = Math.max(0, sh - vh);
      if (progEl) progEl.style.transform = 'scaleX(' + (max > 0 ? Math.min(1, Math.max(0, y / max)) : 0) + ')';
      totop.classList.toggle('on', y > 120);
      toend.classList.toggle('on', sh - (y + vh) > 120);
    }
    function syncProgressSoon() {
      if (progRaf) return;
      progRaf = requestAnimationFrame(function () { progRaf = 0; syncProgress(); });
    }

    function firstBlockAt(clear) {
      var ch = flow.children, lo = 0, hi = ch.length - 1, hit = -1;
      while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (ch[mid].getBoundingClientRect().bottom > clear) { hit = mid; hi = mid - 1; }
        else lo = mid + 1;
      }
      return hit;
    }

    // 改变页面高度的操作（切视图、折起过程、换上新内容）前后，让眼前这条消息留在原位
    function keepPlace(fn) {
      stopSmoothScroll();
      var clear = barClearance(), at = firstBlockAt(clear);
      var blk = at >= 0 ? flow.children[at] : null, ref = blk, childIdx = -1, top = 0;
      if (blk) {
        if (blk.classList.contains('turn')) {
          for (var i = 0; i < blk.children.length; i++) {
            var cr = blk.children[i].getBoundingClientRect();
            if (cr.height > 0 && cr.bottom > clear) {
              ref = blk.children[i];
              childIdx = i;
              top = cr.top;
              break;
            }
          }
        }
        if (ref === blk) top = blk.getBoundingClientRect().top;
      }
      fn();
      if (!blk) { syncProgress(); return; }
      if (!blk.isConnected) {
        blk = flow.children[at];
        ref = blk && childIdx >= 0 && blk.children[childIdx] ? blk.children[childIdx] : blk;
      }
      if (ref) {
        var nr = ref.getBoundingClientRect();
        if (nr.height > 0 || nr.width > 0) {
          scrollByY(nr.top - top);
        } else if (blk) {
          // 刚在看的那段中间过程被当前视图隐藏了：就近停在同一轮的最终答复或提问上
          var fb = null;
          for (var j = Math.max(0, childIdx); j < blk.children.length; j++) {
            if (blk.children[j].getBoundingClientRect().height > 0) { fb = blk.children[j]; break; }
          }
          if (!fb) {
            for (var k = childIdx - 1; k >= 0; k--) {
              if (blk.children[k].getBoundingClientRect().height > 0) { fb = blk.children[k]; break; }
            }
          }
          scrollByY((fb || blk).getBoundingClientRect().top - clear);
        }
      }
      syncProgress();
    }

    // 左侧提问目录：支持正序 / 倒序切换，并与右侧滚动彻底解耦
    var navEl = $('.layout > nav'), tocEl = $('nav .toc'), sortBtn = $('.toc-sort');
    var rawToc = tocEl ? tocEl.innerHTML : '', tocSort = store('toc-sort') === 'desc' ? 'desc' : 'asc';

    function buildDescToc(html) {
      var nodes = parse(html), groups = [], curDay = null, curGroup = null;
      nodes.forEach(function (n) {
        if (n.classList.contains('fk')) {
          groups.push({ fk: n });
          curGroup = null;
        } else if (n.classList.contains('d')) {
          curDay = n;
          curGroup = { day: n, items: [] };
          groups.push(curGroup);
        } else {
          if (!curGroup) {
            curGroup = { day: curDay ? curDay.cloneNode(true) : null, items: [] };
            groups.push(curGroup);
          }
          curGroup.items.push(n);
        }
      });
      var frag = document.createDocumentFragment();
      groups.reverse().forEach(function (g) {
        if (g.fk) {
          frag.appendChild(g.fk);
        } else if (g.items.length) {
          if (g.day) frag.appendChild(g.day);
          g.items.reverse().forEach(function (a) { frag.appendChild(a); });
        }
      });
      return frag;
    }

    function renderToc() {
      if (!tocEl) return;
      if (tocSort === 'desc') {
        tocEl.textContent = '';
        tocEl.appendChild(buildDescToc(rawToc));
      } else {
        tocEl.innerHTML = rawToc;
      }
      if (sortBtn) {
        var lbl = $('span', sortBtn);
        if (lbl) lbl.textContent = tocSort === 'desc' ? '倒序' : '正序';
        sortBtn.classList.toggle('desc', tocSort === 'desc');
        sortBtn.title = tocSort === 'desc' ? '当前倒序（最新提问在上），点击切为正序' : '当前正序（最早提问在上），点击切为倒序';
      }
    }

    function scrollTocTo(a) {
      if (!tocEl || !a) return;
      var tr = tocEl.getBoundingClientRect(), ar = a.getBoundingClientRect();
      if (ar.top < tr.top + 28) tocEl.scrollTop += ar.top - (tr.top + 28);
      else if (ar.bottom > tr.bottom - 28) tocEl.scrollTop += ar.bottom - (tr.bottom - 28);
    }

    ACTIONS.info = function () { openInfo(page); };
    ACTIONS.top = function () { smoothScrollTo(0, true); };
    ACTIONS.end = function () { smoothScrollTo(scrollHOf(), true); };
    ACTIONS.tocsort = function () {
      tocSort = tocSort === 'desc' ? 'asc' : 'desc';
      store('toc-sort', tocSort);
      renderToc();
      collect();
      spy(false, false);
      if (tocEl) tocEl.scrollTop = 0;
    };
    ACTIONS.tools = function (b) {
      var all = $$('details.tools'), open = !all.some(function (x) { return x.open; });
      if (open && view !== 'full') setView('full', true);
      bulk(function () {
        if (open) $$('details.steps').forEach(function (d) { d.open = true; });
        all.forEach(function (x) { x.open = open; });
      });
      b.firstChild.textContent = open ? '收起全部工具调用' : '展开全部工具调用';
      b.closest('details').open = false;
      syncProgress();
    };
    // 过程很长时，读到底部也能把它折起来，并回到这一轮的开头
    ACTIONS.fold = function (b) {
      var d = b.closest('details.steps');
      bulk(function () { d.open = false; });        // 这里要立刻定位，所以不带收起动画
      d.scrollIntoView({ block: 'center' });
      syncProgress();
    };

    // 左侧目录跟随阅读位置；顺便记住精确阅读位置，下次打开直接从上次读到的地方进入
    var prompts = [], links = {}, active = null;
    function collect() {
      prompts = $$('#flow > .turn > .msg.user[id]');
      links = {};
      $$('nav .toc a').forEach(function (a) { links[a.getAttribute('href').slice(1)] = a; });
      active = null;
    }
    function current() {
      var best = null, line = viewHOf() * 0.4, lo = 0, hi = prompts.length - 1;
      while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (prompts[mid].getBoundingClientRect().top <= line) { best = prompts[mid]; lo = mid + 1; }
        else hi = mid - 1;
      }
      return best;
    }
    function atEnd() { return viewHOf() + scrollYOf() >= scrollHOf() - 200; }

    function spy(moved, syncToc) {
      syncProgress();
      if (pill && atEnd()) pill.classList.remove('on');
      var best = current(), a = best && links[best.id];
      if (a === active) return;
      if (active) active.classList.remove('on');
      active = a;
      if (a) {
        a.classList.add('on');
        // 仅在你主动滚动主视图（且鼠标不在左侧栏浏览目录）或恢复阅读位置时，才在目录容器内部跟随，后台刷新绝不抢滚左栏
        if ((moved || syncToc) && (!navEl || !navEl.matches(':hover'))) scrollTocTo(a);
      }
    }

    function savePos() {
      var sy = Math.round(scrollYOf());
      if (sy < 80) { store(posKey, null); return; }
      var clear = barClearance(), at = firstBlockAt(clear), anchor = null, anchorTop = 0;
      for (var idx = at; idx >= 0 && idx < flow.children.length && !anchor; idx++) {
        var blk = flow.children[idx];
        var candidates = blk.id ? [blk] : [];
        candidates = candidates.concat($$('.msg[id], .step[id], .sent[id], details.fold[id], .line[id], details.tools[open] details.tool[id]', blk));
        for (var i = 0; i < candidates.length; i++) {
          var r = candidates[i].getBoundingClientRect();
          if (r.height > 0 && r.bottom > clear) { anchor = candidates[i]; anchorTop = r.top; break; }
        }
      }
      if (anchor) {
        store(posKey, JSON.stringify({ id: anchor.id, y: Math.round(anchorTop), sy: sy }));
      } else {
        store(posKey, JSON.stringify({ id: '', y: 0, sy: sy }));
      }
    }

    function restorePos() {
      var raw = store(posKey);
      if (!raw) return false;
      var rec = null;
      if (raw.charAt(0) === '{') {
        try { rec = JSON.parse(raw); } catch (e) { return false; }
      } else {
        rec = { id: raw, y: 76, sy: 0 };            // 兼容旧版只存了锚点 ID 的格式
      }
      if (!rec) return false;
      var anchor = rec.id ? document.getElementById(rec.id) : null;
      if (anchor) {
        if (!anchor.offsetHeight) bulk(function () { reveal(anchor); });
        if (!anchor.offsetHeight) {
          var host = anchor.closest('.turn');
          anchor = (host && ($('.msg.asst', host) || $('.msg.user', host))) || null;
          rec.y = barClearance();
        }
        if (anchor && anchor.offsetHeight) {
          scrollByY(anchor.getBoundingClientRect().top - rec.y);
          requestAnimationFrame(function () {
            if (!userMoved && anchor.isConnected && anchor.offsetHeight) {
              scrollByY(anchor.getBoundingClientRect().top - rec.y);
              spy(false, true);
            }
          });
          return true;
        }
      }
      if (rec.sy > 0) {
        scrollToY(rec.sy);
        return true;
      }
      return false;
    }

    function step(dir) {
      if (!prompts.length) return;
      var clear = barClearance() + 10, idx = -1, lo = 0, hi = prompts.length - 1;
      while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (prompts[mid].getBoundingClientRect().top <= clear) { idx = mid; lo = mid + 1; }
        else hi = mid - 1;
      }
      var nextIdx = dir > 0 ? idx + 1 : (idx >= 0 && prompts[idx].getBoundingClientRect().top < clear - 28 ? idx : idx - 1);
      var next = prompts[Math.max(0, Math.min(prompts.length - 1, nextIdx))];
      if (next) scrollNodeIntoView(next, true);
    }
    function turnInView() {
      var y = viewHOf() * 0.4, at = firstBlockAt(y);
      if (at < 0) return null;
      var blk = flow.children[at];
      if (blk.classList.contains('turn') && blk.getBoundingClientRect().top <= y) return blk;
      return null;
    }

    function findAnchorTarget(h) {
      if (!h) return null;
      var t = document.getElementById(h);
      if (!t && h.slice(0, 2) === 'r-') t = $('[data-r="' + h.slice(2).replace(/[^\w]/g, '') + '"]');
      return t;
    }

    function jump(animate) {
      var h = decodeURIComponent(location.hash.slice(1));
      var t = findAnchorTarget(h);
      if (!t) return null;
      bulk(function () { reveal(t); });
      if (!t.offsetHeight && view !== 'full') {
        if (view === 'result' && t.closest('.step')) setView('chat', false);
        else setView('full', false);
      }
      scrollNodeIntoView(t, !!animate);
      $$('.flash').forEach(function (x) { x.classList.remove('flash'); });
      void t.offsetWidth;                   // 让同一个目标再次被点到时也重新亮起边缘光晕
      t.classList.add('flash');
      return t;
    }

    document.addEventListener('click', function (e) {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      var a = e.target.closest('a[href^="#"]');
      if (!a) return;
      var href = a.getAttribute('href');
      if (!href || href === '#') return;
      if (!findAnchorTarget(decodeURIComponent(href.slice(1)))) return;
      e.preventDefault();
      if (location.hash !== href) history.pushState(null, '', href);
      jump(true);
    });

    // 不在最底下时来了新内容：底部浮出一个入口，不擅自滚动
    var pill = null;
    function showPill() {
      if (!pill) {
        pill = el('button', 'newpill');
        pill.type = 'button';
        pill.appendChild(el('span', null, '有新内容'));
        pill.appendChild(icon('down'));
        pill.onclick = function () { pill.classList.remove('on'); ACTIONS.end(); };
        body.appendChild(pill);
      }
      requestAnimationFrame(function () { pill.classList.add('on'); });
    }

    // 更新：标题区整个换；对话按块比较内容指纹，服务只发回从第一个不同的块起的部分
    function keepOpen(o, n) {
      var os = $('details.steps', o), ns = $('details.steps', n);
      if (os && ns) ns.open = os.open;
      $$('details.tools[open] > details.tool:first-of-type, details.tool[open]', o).forEach(function (t) {
        if (!t.dataset.u) return;
        var m = $('details.tool[data-u="' + t.dataset.u.replace(/"/g, '') + '"]', n);
        if (!m) return;
        m.parentNode.open = true;
        if (t.open) m.open = true;
      });
      var thinks = $$('details.think', o), nthinks = $$('details.think', n);
      thinks.forEach(function (t, i) { if (nthinks[i]) nthinks[i].open = t.open; });
    }
    function apply(j, manual) {
      var olds = [].slice.call(flow.children);
      if (j.sig === body.dataset.sig && j.start === olds.length && !j.blocks.length) return { changed: false };
      var news = parse(j.blocks.join('\n')), end = atEnd(), turnsBefore = $$('#flow > .turn').length;
      keepPlace(function () {
        var head = $('main .head'), filesOpen = !!$('.files[open]', head), nhead = parse(j.head)[0];
        head.replaceWith(nhead);
        if (filesOpen && $('.files', nhead)) $('.files', nhead).open = true;
        news.forEach(function (n, k) {
          var o = olds[j.start + k];
          if (o) keepOpen(o, n); else n.classList.add('new');
        });
        bulk(function () {
          olds.slice(j.start).forEach(function (o) { o.remove(); });
          news.forEach(function (n) { flow.appendChild(n); awaitImages(n); });
        });
      });
      if (tocEl && j.toc !== rawToc) {
        var tst = tocEl.scrollTop;
        rawToc = j.toc;
        renderToc();
        tocEl.scrollTop = tst;
      }
      if ($('#info') && j.info) $('#info').textContent = JSON.stringify(j.info);
      body.dataset.sig = j.sig;
      document.title = j.title;
      collect();
      spy(false, false);
      if (activeQ) highlight(activeQ, null, true);
      if (end) scrollToY(scrollHOf());              // 本来就在看最新的，就继续跟着
      else if (!manual && news.length) showPill();
      syncProgress();
      var more = $$('#flow > .turn').length - turnsBefore;
      return { changed: true, text: more > 0 ? '已更新 · 新增 ' + more + ' 轮对话' : '已更新到最新内容',
        action: end ? null : { action: '跳到最新', run: ACTIONS.end } };
    }
    pull = function (fresh) {
      return fetch('/api/blocks' + (fresh ? '?fresh=1' : ''), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ page: page, keys: [].map.call(flow.children, function (n) { return n.dataset.k || ''; }) })
      }).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      }).then(function (j) { return apply(j, fresh); });
    };

    // 初始化
    var ready = false, userMoved = false;
    var savePosLater = debounce(savePos, 140), spyLater = debounce(function () { spy(true); }, 50);
    setView(store('view') || 'full', false);
    renderToc();
    collect();

    var fq = $('#fq'), target = jump(false), q0 = '';
    if (fq) {
      q0 = new URLSearchParams(location.search).get('q') || '';
      if (q0) { fq.value = q0; highlight(q0, target); }
      fq.oninput = debounce(function () { highlight(fq.value.trim(), null); }, 250);
      fq.onkeydown = function (e) {
        if (e.key === 'Enter') go(e.shiftKey ? -1 : 1);
        if (e.key === 'Escape') { fq.value = ''; highlight('', null); fq.blur(); }
      };
    }
    window.addEventListener('hashchange', function () { jump(true); });

    // 直接恢复到上次阅读的位置（除非本次带了锚点或搜索词）
    var restored = !target && !q0 && restorePos();
    spy(false, restored || !!target);
    requestAnimationFrame(function () { ready = true; syncProgress(); });

    onMainScroll(function () {
      syncProgressSoon();
      if (!ready) return;
      userMoved = true;
      spyLater();
      savePosLater();
    });
    window.addEventListener('resize', debounce(syncProgress, 120));
    window.addEventListener('pagehide', function () { if (userMoved) savePos(); });
    document.addEventListener('visibilitychange', function () { if (document.hidden && userMoved) savePos(); });

    document.addEventListener('keydown', function (e) {
      if (box || layer || typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      var k = e.key;
      if (k === 'j') step(1);
      else if (k === 'k') step(-1);
      else if (k === '/' && fq) { e.preventDefault(); fq.focus(); fq.select(); }
      else if (k === 'i' && $('#info')) openInfo(page);
      else if (k >= '1' && k <= '3') switchView(VIEWS[k - 1]);
      else if (k === 'e' && view !== 'result') {
        var t = turnInView(), d = t && $('details.steps', t);
        if (d) keepPlace(function () { bulk(function () { d.open = !d.open; }); });
      }
    });
  }

  /* ================= 索引页 ================= */

  if (isIndex) {
    var q = $('#q'), ar = $('#ar'), tl = $('#tl'), hits = $('#hits'), cnt = $('#cnt'), list = $('#list');
    var project = '', account = '', seq = 0;
    var WHO = { user: ['你', 'who-you'], asst: ['Claude', 'who-claude'], tool: ['工具', ''] };
    function rows() { return $$('#list .row'); }
    function remember() { tab('idx', { p: project, a: account, ar: ar.checked, tl: tl.checked, q: q.value }); }

    // 项目、账号两组标签各自计数：只数当前来源的会话，没有的就不显示
    function count(t) {
      var c = +t.dataset.c || 0, x = +t.dataset.x || 0;
      return source === 'claude' ? c : source === 'codex' ? x : c + x;
    }
    function paintTabs() {
      $$('#pj .tab, #ac .tab').forEach(function (t) {
        var n = count(t), small = $('small', t), all = t.dataset.p === '' || t.dataset.acct === '';
        if (small) small.textContent = n;
        t.hidden = !all && !n;
      });
      pick(project);
      pickAcct(account);
    }
    function pick(p) {
      var tabs = $$('#pj .tab');
      if (!tabs.some(function (x) { return x.dataset.p === p && !x.hidden; })) p = '';
      project = p;
      tabs.forEach(function (x) { x.classList.toggle('on', x.dataset.p === p); });
    }
    function pickAcct(a) {
      var tabs = $$('#ac .tab');
      if (!tabs.some(function (x) { return x.dataset.acct === a && !x.hidden; })) a = '';
      account = a;
      var chosen = null;
      tabs.forEach(function (x) {
        var on = x.dataset.acct === a;
        x.classList.toggle('on', on);
        if (on) chosen = x;
      });
      var nameEl = $('#ac-name'), dotEl = $('#ac-dot'), cntEl = $('#ac-cnt');
      if (nameEl && chosen) {
        var sp = $('span', chosen), ic = $('i', chosen), sm = $('small', chosen);
        nameEl.textContent = sp ? sp.textContent : '全部账号';
        if (dotEl) {
          if (ic && a) {
            dotEl.style.background = ic.style.background;
            dotEl.hidden = false;
          } else {
            dotEl.hidden = true;
          }
        }
        if (cntEl) cntEl.textContent = sm ? sm.textContent : '';
      }
    }

    function shown(r) {
      return (source === 'all' || r.dataset.src === source) && (!project || r.dataset.p === project)
        && (!account || r.dataset.acct === account) && (ar.checked || !r.dataset.a);
    }
    // 有搜索词时列表只留标题命中的会话：内容命中的已经在上面的结果里
    function filter() {
      var words = terms(q.value), n = 0;
      rows().forEach(function (r) {
        var ok = shown(r);
        if (ok && words.length) ok = words.every(function (w) { return r.dataset.t.indexOf(w) >= 0; });
        r.hidden = !ok;
        if (ok) n++;
      });
      $$('#list .bucket').forEach(function (b) { b.hidden = !$('.row:not([hidden])', b); });
      cnt.textContent = n;
    }
    function allowed(pg) {
      var row = $('#list .row[data-page="' + pg + '"]');
      return !row || shown(row);
    }
    function show(j) {
      hits.textContent = '';
      var found = j.sessions.filter(function (s) { return allowed(s.page); });
      var total = found.reduce(function (n, s) { return n + s.n; }, 0);
      hits.appendChild(el('div', 'meta', found.length ? '对话内容：' + total + ' 处，分布在 ' + found.length + ' 个会话'
        : '对话内容里没有找到“' + j.q + '”。'));
      found.forEach(function (s) {
        var box = el('div', 'hs'), base = '/s/' + s.page + '?q=' + encodeURIComponent(j.q);
        var a = el('a', null, s.title);
        a.href = base;
        box.appendChild(a);
        box.appendChild(el('small', null, '　' + s.n + ' 处'));
        var ul = el('ul');
        s.hits.forEach(function (h) {
          var li = el('li'), link = el('a'), who = WHO[h.who];
          link.href = base + '#' + h.anchor;
          link.appendChild(el('small', null, h.time + '　'));
          link.appendChild(el('small', who[1], (h.who === 'asst' && s.src === 'codex' ? 'Codex' : who[0]) + '　'));
          link.appendChild(document.createTextNode('…' + h.pre));
          link.appendChild(el('mark', null, h.hit));
          link.appendChild(document.createTextNode(h.post + '…'));
          li.appendChild(link);
          ul.appendChild(li);
        });
        if (s.n > s.hits.length) {
          var more = el('li'), ml = el('a', null, '还有 ' + (s.n - s.hits.length) + ' 处，进入会话查看 →');
          ml.href = base;
          more.appendChild(ml);
          ul.appendChild(more);
        }
        box.appendChild(ul);
        hits.appendChild(box);
      });
      filter();
      if ($('#list .row:not([hidden])')) hits.appendChild(el('div', 'meta', '标题匹配的会话：'));
    }
    function run() {
      var v = q.value.trim(), mine = ++seq;
      remember();
      if (!v) { hits.textContent = ''; filter(); return; }
      fetch('/api/search?q=' + encodeURIComponent(v) + '&tools=' + (tl.checked ? 1 : 0) + '&src=' + srcParam())
        .then(function (r) { return r.json(); })
        .then(function (j) { if (mine === seq) show(j); })
        .catch(function () { if (mine === seq) hits.textContent = '搜索失败：本地服务没有响应，请确认 Sessiontool 的窗口还开着。'; });
    }

    // 键盘在搜索结果和会话之间移动：用真正的焦点，Enter 就是浏览器自己的“打开链接”
    function stops() {
      return $$('#hits .hs a, #list .row .cover').filter(function (a) { return a.offsetParent !== null; });
    }
    function move(dir) {
      var items = stops(), i = items.indexOf(document.activeElement);
      var next = i < 0 ? items[dir > 0 ? 0 : items.length - 1] : items[Math.max(0, Math.min(items.length - 1, i + dir))];
      if (next) { next.focus(); next.scrollIntoView({ block: 'nearest' }); }
    }
    function focusedRow() {
      var a = document.activeElement;
      return a && a.closest ? a.closest('.row') : null;
    }

    ACTIONS.info = function (b) { openInfo(b.closest('.row').dataset.page); };

    function swap(doc) {
      var nb = doc.body;
      $('#synced').textContent = $('#synced', doc).textContent;
      if (nb.dataset.sig === body.dataset.sig) return { changed: false };
      var f = focusedRow(), fp = f && f.dataset.page;
      var sideScroll = $('#side-scroll'), sst = sideScroll ? sideScroll.scrollTop : 0, mst = scrollYOf();
      list.classList.add('still');          // 换进来的行不再播放入场动画
      list.innerHTML = $('#list', doc).innerHTML;
      var npj = $('#pj', doc);
      if (npj && $('#pj').innerHTML !== npj.innerHTML) $('#pj').innerHTML = npj.innerHTML;
      var ac = $('#ac'), nac = $('#ac', doc);
      if (ac && nac) {
        var odiv = $('div', ac), ndiv = $('div', nac);
        if (odiv && ndiv && odiv.innerHTML !== ndiv.innerHTML) odiv.innerHTML = ndiv.innerHTML;
      } else if (!ac && $('.side-acct', doc) && $('.side-head')) {
        $('.side-head').appendChild($('.side-acct', doc));
      }
      if (srcSeg && $('#src', doc)) {
        var nsmall = $$('#src small', doc);
        $$('small', srcSeg).forEach(function (s, i) { if (nsmall[i]) s.textContent = nsmall[i].textContent; });
      }
      $('#totals').textContent = $('#totals', doc).textContent;
      body.dataset.sig = nb.dataset.sig;
      paintTabs();
      run();
      if (sideScroll) sideScroll.scrollTop = sst;
      scrollToY(mst);
      var back = fp && $('#list .row[data-page="' + fp + '"] .cover');
      if (back) back.focus({ preventScroll: true });
      return { changed: true, text: '会话列表已更新' };
    }
    pull = function (fresh) {
      return fetch('/' + (fresh ? '?fresh=1' : '')).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.text();
      }).then(function (text) { return swap(new DOMParser().parseFromString(text, 'text/html')); });
    };

    document.addEventListener('click', function (e) {
      var t = e.target.closest('#pj .tab');
      if (t) { pick(t.dataset.p); scrollToY(0); run(); return; }
      t = e.target.closest('#ac .tab');
      if (t) {
        pickAcct(t.dataset.acct);
        if ($('#ac')) $('#ac').open = false;
        scrollToY(0);
        run();
        return;
      }
      // 点进会话时给标题起个过渡名字，新页面的大标题会从这里“长”出来
      var cover = e.target.closest('.cover');
      if (cover) {
        $$('#list .title').forEach(function (x) { x.style.viewTransitionName = ''; });      // 名字在页面里必须唯一
        $('.title', cover.parentNode).style.viewTransitionName = 'title';
      }
    });
    q.oninput = debounce(run, 200);
    ar.onchange = tl.onchange = run;
    onSource = function () { paintTabs(); run(); };

    document.addEventListener('keydown', function (e) {
      if (box || layer || e.ctrlKey || e.metaKey || e.altKey) return;
      var k = e.key;
      if (e.target === q) {
        if (k === 'Escape') { q.value = ''; run(); }
        else if (k === 'ArrowDown') { e.preventDefault(); move(1); }
        return;
      }
      if (typing(e)) return;
      if (k === '/') { e.preventDefault(); q.focus(); q.select(); }
      else if (k === 'j' || k === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (k === 'k' || k === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (k === 'i' && focusedRow()) openInfo(focusedRow().dataset.page);
      else if (k === 'c' && focusedRow()) { var b = $('[data-copy]', focusedRow()); copyFrom(b, b.dataset.copy, b.dataset.copied); }
    });

    // 回到列表时恢复刚才的筛选和搜索；从会话页回来的，连滚动位置和来处的标题一起恢复
    var saved = tab('idx') || {};
    if (saved.ar === false) ar.checked = false;
    if (saved.tl) tl.checked = true;
    if (saved.q && !q.value) q.value = saved.q;
    project = saved.p || '';
    account = saved.a || '';
    pickSource(store('src') || 'claude');
    paintTabs();
    var from = /\/s\/([0-9a-f]+)/.exec(document.referrer || '');
    if (from) {
      var back = $('#list .row[data-page="' + from[1] + '"] .title');
      if (back) back.style.viewTransitionName = 'title';
      list.classList.add('still');
    }
    if (q.value) run(); else filter();
    if (from) scrollToY(tab('idx-y') || 0);
    else q.focus({ preventScroll: true });      // 新打开时光标直接在搜索框里，可以马上输入
    window.addEventListener('pagehide', function () { tab('idx-y', scrollYOf()); });
  }

  /* ================= 统计页 ================= */

  if (isStats) {
    var st = $('#st'), rangeSeg = $('#range'), spanEl = $('#span'), digestEl = $('#digest');
    var acctMenu = $('#acct'), acctName = $('#acct-name'), acctDot = $('#acct-dot');
    var range = +(store('st-range') || 30), acct = store('st-acct') || '', data = null, ask = 0;
    var metric = store('st-metric') || 'cost', quipStep = 0;
    var tip = el('div', 'tip');
    tip.setAttribute('role', 'tooltip');
    body.appendChild(tip);

    function paintRange() {
      $$('button', rangeSeg).forEach(function (b) { b.classList.toggle('on', +b.dataset.d === range); });
    }
    rangeSeg.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      range = +b.dataset.d;
      store('st-range', range);
      paintRange();
      load();
    });
    if (acctMenu) {
      acctMenu.addEventListener('click', function (e) {
        var b = e.target.closest('.tab');
        if (!b) return;
        var next = b.dataset.acct || '';
        acctMenu.open = false;
        if (next === acct) return;
        acct = next;
        store('st-acct', acct);
        syncAcctMenu();
        load();
      });
    }

    // quiet：实时更新时悄悄换上新数字；换筛选条件时旧图半透明地留着，等新数据到了再换，不闪白
    function load(fresh, quiet) {
      var mine = ++ask;
      if (!quiet) st.classList.add('loading');
      return fetch('/api/stats?days=' + range + '&account=' + encodeURIComponent(acct) + '&src=' + srcParam() + (fresh ? '&fresh=1' : ''))
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        }).then(function (j) {
          if (mine !== ask) return { changed: false };
          data = j;
          draw();
          return { changed: true, text: '统计已更新' };
        }).finally(function () { if (mine === ask) st.classList.remove('loading'); });
    }
    pull = function (manual) { return load(manual, !manual); };
    onSource = function () {
      if (acct && data && data.accounts && !data.accounts.some(function (a) {
        return (source === 'all' || a.src === source) && a.key === acct;
      })) {
        acct = '';
        store('st-acct', '');
      }
      load();
    };

    // ----- 提示框：数值在前、名字在后；内容一律用 textContent -----
    function showTip(e, rows, head) {
      tip.textContent = '';
      if (head) tip.appendChild(el('div', 'th', head));
      rows.forEach(function (r) {
        var line = el('div', 'tr');
        if (r[2]) { var k = el('i', 'key ' + r[2]); line.appendChild(k); }
        line.appendChild(el('b', null, r[0]));
        line.appendChild(el('span', null, r[1]));
        tip.appendChild(line);
      });
      tip.classList.add('on');
      var w = tip.offsetWidth, h = tip.offsetHeight, x = e.clientX + 14, y = e.clientY + 14;
      if (x + w > window.innerWidth - 8) x = e.clientX - w - 14;
      if (y + h > window.innerHeight - 8) y = e.clientY - h - 14;
      tip.style.transform = 'translate(' + Math.max(8, x) + 'px,' + Math.max(8, y) + 'px)';
    }
    function hideTip() { tip.classList.remove('on'); }
    function hover(node, fn) {
      node.addEventListener('pointermove', function (e) { fn(e); node.classList.add('hot'); });
      node.addEventListener('pointerleave', function () { hideTip(); node.classList.remove('hot'); });
    }

    // ----- 卡片：标题、右上角的切换，以及“表格”视图 -----
    function card(title, sub, cls) {
      var c = el('section', 'card' + (cls ? ' ' + cls : '')), h = el('header');
      var t = el('div', 'ct');
      t.appendChild(el('h2', null, title));
      if (sub) t.appendChild(el('small', null, sub));
      h.appendChild(t);
      c.appendChild(h);
      st.appendChild(c);
      return { box: c, head: h, body: c.appendChild(el('div', 'cb')) };
    }
    function toggle(head, options, value, fn) {
      var seg = el('div', 'seg sm');
      options.forEach(function (o) {
        var b = el('button', o[0] === value ? 'on' : null, o[1]);
        b.type = 'button';
        b.onclick = function () {
          $$('button', seg).forEach(function (x) { x.classList.toggle('on', x === b); });
          fn(o[0]);
        };
        seg.appendChild(b);
      });
      head.appendChild(seg);
    }
    // 每张图都能换成同样数据的表格；返回“重画”，别的切换（比如费用 / Tokens）用它。
    // 选了表格的，实时更新重画时还是表格
    var asTable = {};
    function tableToggle(c, name, drawChart, drawTable) {
      var b = ibtn('table', '切换图表 / 表格', 'sm tt');
      function redraw() {
        b.classList.toggle('on', !!asTable[name]);
        b.setAttribute('aria-pressed', !!asTable[name]);
        c.body.textContent = '';
        (asTable[name] ? drawTable : drawChart)(c.body);
      }
      b.onclick = function () {
        asTable[name] = !asTable[name];
        redraw();
      };
      c.head.appendChild(b);
      redraw();
      return redraw;
    }

    // 刻度：取 1、2、5 乘 10 的幂
    function ticks(max, n) {
      if (!(max > 0)) return [0, 1];
      var raw = max / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), r = raw / mag;
      var stepv = (r >= 5 ? 10 : r >= 2 ? 5 : r >= 1 ? 2 : 1) * mag;
      if (r <= 1) stepv = mag;
      var out = [];
      for (var v = 0; v < max + stepv * 0.999; v += stepv) out.push(+v.toPrecision(12));
      if (out.length < 2) out.push(stepv);
      return out;
    }
    function fmtMetric(v, m) { return m === 'cost' ? money(v) : m === 'n' ? compact(v) + ' 次' : compact(v); }
    function shortDate(d) { var p = d.split('-'); return (+p[1]) + '/' + (+p[2]); }
    function dayName(d) { var t = new Date(d + 'T00:00:00'); return d + ' 周' + WEEK[(t.getDay() + 6) % 7]; }
    function slotClass(i) { return i < 6 ? 's' + (i + 1) : 's0'; }
    function slotName(i) { return i < data.slots.length ? data.slots[i] : '其他'; }

    // ----- 每天：按模型堆起来的柱子 -----
    function drawDaily(host) {
      var days = data.days, idx = metric === 'cost' ? 1 : 2;
      var W = Math.max(300, host.clientWidth), H = 236, L = 52, R = 8, T = 10, B = 26;
      var pw = W - L - R, ph = H - T - B;
      var totals = days.map(function (d) { return d.models.reduce(function (a, m) { return a + m[idx]; }, 0); });
      var tk = ticks(Math.max.apply(null, totals.concat([0])), 4), top = tk[tk.length - 1];
      var band = pw / days.length, bw = Math.max(1.5, Math.min(24, band * 0.7));
      var s = svg('svg', { 'class': 'chart', width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'img',
        'aria-label': '每天的' + (metric === 'cost' ? '费用' : 'token 用量') + '，按模型分开' });
      tk.forEach(function (v) {
        var y = T + ph - v / top * ph;
        s.appendChild(svg('line', { x1: L, x2: W - R, y1: y, y2: y, 'class': v ? 'grid' : 'axis' }));
        s.appendChild(svg('text', { x: L - 8, y: y + 4, 'class': 'tick', 'text-anchor': 'end' }, fmtMetric(v, metric)));
      });
      var every = Math.max(1, Math.ceil(days.length / Math.max(2, Math.floor(pw / 56))));
      days.forEach(function (d, i) {
        var x = L + i * band + (band - bw) / 2, base = T + ph, segs = d.models.filter(function (m) { return m[idx] > 0; });
        var g = svg('g', { 'class': 'col' });
        segs.forEach(function (m, j) {
          var h = m[idx] / top * ph, y = base - h, gap = j ? 2 : 0;
          if (h - gap > 0.5) {
            var r = j === segs.length - 1 ? Math.min(4, bw / 2, h - gap) : 0;
            var hh = h - gap;
            g.appendChild(svg('path', { 'class': 'seg ' + slotClass(m[0]),
              d: 'M' + x + ',' + (y + hh) + 'V' + (y + r) + (r ? 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y : '') + 'H' + (x + bw - r)
                + (r ? 'Q' + (x + bw) + ',' + y + ' ' + (x + bw) + ',' + (y + r) : '') + 'V' + (y + hh) + 'Z' }));
          }
          base = y;
        });
        var hit = svg('rect', { x: L + i * band, y: T, width: band, height: ph, 'class': 'hit' });
        g.appendChild(hit);
        hover(g, function (e) {
          var rows = segs.slice().reverse().map(function (m) { return [fmtMetric(m[idx], metric), slotName(m[0]), slotClass(m[0])]; });
          rows.push([fmtMetric(totals[i], metric), '合计']);
          if (d.n) rows.push([d.n + ' 次', '回复']);
          showTip(e, rows, dayName(d.d));
        });
        s.appendChild(g);
        if (i % every === 0 || i === days.length - 1) {
          s.appendChild(svg('text', { x: L + i * band + band / 2, y: H - 8, 'class': 'tick', 'text-anchor': 'middle' }, shortDate(d.d)));
        }
      });
      host.appendChild(s);
      var used = {};
      days.forEach(function (d) { d.models.forEach(function (m) { if (m[idx] > 0) used[m[0]] = 1; }); });
      var legend = el('div', 'legend');
      Object.keys(used).map(Number).sort().forEach(function (i) { legend.appendChild(swatch(slotClass(i), slotName(i))); });
      host.appendChild(legend);
    }
    function dailyTable(host) {
      var used = {};
      data.days.forEach(function (d) { d.models.forEach(function (m) { if (m[1] || m[2]) used[m[0]] = 1; }); });
      var slots = Object.keys(used).map(Number).sort();
      var rows = data.days.slice().reverse().filter(function (d) { return d.n || d.prompts; }).map(function (d) {
        var by = {};
        d.models.forEach(function (m) { by[m[0]] = m; });
        return [dayName(d.d), d.prompts, d.n, compact(d.tokens), pct(d.rate, 0), money(d.cost)].concat(slots.map(function (i) {
          return by[i] ? money(by[i][1]) : '';
        }));
      });
      host.appendChild(grid(['日期', '提问', '回复', 'Tokens', '命中率', '费用'].concat(slots.map(slotName)), rows));
    }

    // ----- 日历：一格一天，颜色是当天回复的次数，和旁边的时段图量的是同一样东西 -----
    function levels(values) {
      var nz = values.filter(function (v) { return v > 0; }).sort(function (a, b) { return a - b; });
      var q = function (p) { return nz.length ? nz[Math.min(nz.length - 1, Math.floor(p * nz.length))] : 0; };
      var cut = [q(0.25), q(0.5), q(0.75)];
      return function (v) { return !(v > 0) ? 0 : v <= cut[0] ? 1 : v <= cut[1] ? 2 : v <= cut[2] ? 3 : 4; };
    }
    function drawHeat(host) {
      var by = {};
      data.days.forEach(function (d) { by[d.d] = d; });
      var end = new Date(data.range.to + 'T00:00:00'), from = new Date(data.range.from + 'T00:00:00');
      // 至少画半年，日历的形状才看得出来；范围以外的格子留空
      var start = new Date(Math.min(from, new Date(end.getFullYear(), end.getMonth(), end.getDate() - 181)));
      start.setDate(start.getDate() - (start.getDay() + 6) % 7);           // 从周一开始
      var weeks = Math.ceil((Math.round((end - start) / 864e5) + 1) / 7);
      var W = Math.max(300, host.clientWidth), L = 26, T = 18;
      var stepc = Math.max(9, Math.min(17, Math.floor((W - L) / weeks))), cell = stepc - 3;
      var level = levels(data.days.map(function (d) { return d.n; }));
      var s = svg('svg', { 'class': 'chart heat', width: L + weeks * stepc, height: T + 7 * stepc, role: 'img',
        'aria-label': '每天的回复次数' });
      [0, 2, 4].forEach(function (w) {
        s.appendChild(svg('text', { x: 0, y: T + w * stepc + cell - 1, 'class': 'tick' }, '周' + WEEK[w]));
      });
      var lastMonth = -1, lastLabel = -9;
      for (var w = 0; w < weeks; w++) {
        for (var dw = 0; dw < 7; dw++) {
          var t = new Date(start.getFullYear(), start.getMonth(), start.getDate() + w * 7 + dw);
          if (t > end) continue;
          var iso = t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate()), d = by[iso];
          if (dw === 0 && t.getMonth() !== lastMonth) {
            lastMonth = t.getMonth();
            if (w < weeks - 2 && w - lastLabel >= 3) {          // 挨得太近的月份名不写，免得叠在一起
              s.appendChild(svg('text', { x: L + w * stepc, y: 11, 'class': 'tick' }, (t.getMonth() + 1) + '月'));
              lastLabel = w;
            }
          }
          var rect = svg('rect', { x: L + w * stepc, y: T + dw * stepc, width: cell, height: cell, rx: 2.5,
            'class': 'cell ' + (d ? 'h' + level(d.n) : 'out') });
          if (d) {
            (function (d) {
              hover(rect, function (e) {
                showTip(e, [[d.n + ' 次', '回复'], [d.prompts + ' 次', '提问'], [money(d.cost), '费用'], [compact(d.tokens), 'tokens']],
                  dayName(d.d));
              });
            })(d);
          }
          s.appendChild(rect);
        }
      }
      var wrap = el('div', 'heatwrap');
      wrap.appendChild(s);
      host.appendChild(wrap);
      var legend = el('div', 'legend scale');
      legend.appendChild(el('span', null, '少'));
      for (var i = 0; i <= 4; i++) legend.appendChild(el('i', 'cell h' + i));
      legend.appendChild(el('span', null, '多'));
      host.appendChild(legend);
    }

    // ----- 时段：一周七天 × 二十四小时，颜色是回复的次数 -----
    function drawHours(host) {
      var hrs = data.hours, flat = [].concat.apply([], hrs), level = levels(flat);
      var W = Math.max(300, host.clientWidth), L = 30, T = 4, B = 18;
      var stepc = Math.max(10, Math.min(30, Math.floor((W - L) / 24))), cell = stepc - 3;
      var s = svg('svg', { 'class': 'chart', width: L + 24 * stepc, height: T + 7 * stepc + B, role: 'img', 'aria-label': '一周里各个时段的回复次数' });
      for (var d = 0; d < 7; d++) {
        s.appendChild(svg('text', { x: 0, y: T + d * stepc + cell - 1, 'class': 'tick' }, '周' + WEEK[d]));
        for (var h = 0; h < 24; h++) {
          var rect = svg('rect', { x: L + h * stepc, y: T + d * stepc, width: cell, height: cell, rx: 2.5, 'class': 'cell h' + level(hrs[d][h]) });
          (function (d, h) {
            hover(rect, function (e) { showTip(e, [[hrs[d][h] + ' 次', '回复']], '周' + WEEK[d] + ' ' + pad(h) + ':00–' + pad((h + 1) % 24) + ':00'); });
          })(d, h);
          s.appendChild(rect);
        }
      }
      for (h = 0; h < 24; h += 3) s.appendChild(svg('text', { x: L + h * stepc, y: T + 7 * stepc + 12, 'class': 'tick' }, pad(h)));
      host.appendChild(s);
    }

    // ----- 额度：应用隔一会儿记一次的 5 小时、7 天窗口用量 -----
    function meter(label, v) {
      var m = el('div', 'meter'), track = el('span', 'track'), fill = el('i');
      var x = typeof v === 'number' ? v : null;
      fill.style.width = Math.max(0, Math.min(100, x || 0)) + '%';
      if (x >= 95) m.classList.add('crit'); else if (x >= 80) m.classList.add('warn');
      track.appendChild(fill);
      m.appendChild(el('span', 'ml', label));
      m.appendChild(track);
      m.appendChild(el('b', null, x == null ? '—' : x + '%' + (x >= 95 ? ' · 将满' : x >= 80 ? ' · 偏高' : '')));
      return m;
    }
    function spark(points) {
      var W = 160, H = 34;
      var s = svg('svg', { 'class': 'spark', width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, 'aria-hidden': 'true' });
      if (points.length < 2) return s;
      var t0 = points[0][0], t1 = points[points.length - 1][0] || t0 + 1;
      var path = points.map(function (p, i) {
        return (i ? 'L' : 'M') + ((p[0] - t0) / Math.max(1, t1 - t0) * (W - 4) + 2).toFixed(1) + ',' + (H - 3 - p[1] / 100 * (H - 6)).toFixed(1);
      }).join('');
      s.appendChild(svg('line', { x1: 0, x2: W, y1: H - 3, y2: H - 3, 'class': 'axis' }));
      s.appendChild(svg('path', { d: path, 'class': 'line' }));
      return s;
    }

    function syncAcctMenu() {
      if (!acctMenu) return;
      var chosen = null;
      $$('.tab', acctMenu).forEach(function (x) {
        var on = (x.dataset.acct || '') === acct;
        x.classList.toggle('on', on);
        if (on) chosen = x;
      });
      if (acctName) {
        var sp = chosen && $('span', chosen);
        acctName.textContent = sp ? sp.textContent : '全部账号';
      }
      if (acctDot) {
        var ic = chosen && $('i', chosen);
        if (ic && acct) {
          acctDot.style.background = ic.style.background;
          acctDot.hidden = false;
        } else {
          acctDot.hidden = true;
        }
      }
    }

    function fillAccounts(list) {
      if (!acctMenu) return false;
      var visible = (list || []).filter(function (a) { return source === 'all' || a.src === source; });
      if (acct && !visible.some(function (a) { return a.key === acct; })) {
        acct = '';
        store('st-acct', '');
        load();
        return true;
      }
      var box = $('div', acctMenu);
      if (!box) return false;
      box.textContent = '';
      var allBtn = el('button', 'tab' + (!acct ? ' on' : ''));
      allBtn.type = 'button';
      allBtn.dataset.acct = '';
      allBtn.appendChild(el('span', null, '全部账号'));
      box.appendChild(allBtn);
      visible.forEach(function (a) {
        var b = el('button', 'tab' + (acct === a.key ? ' on' : ''));
        b.type = 'button';
        b.dataset.acct = a.key;
        b.title = a.email || a.name;
        var dot = el('i');
        dot.style.background = 'hsl(' + hue(a.email || a.key) + ' 55% 55%)';
        b.appendChild(dot);
        b.appendChild(el('span', null, a.name));
        if (a.email && a.email !== a.name) b.appendChild(el('small', null, a.email));
        box.appendChild(b);
      });
      syncAcctMenu();
      return false;
    }

    function fmtRatio(x) {
      if (x >= 100) return Math.round(x).toLocaleString('en-US');
      if (x >= 10) return x.toFixed(1).replace(/\.0$/, '');
      return x.toFixed(2).replace(/(\.\d)0$/, '$1').replace(/\.0$/, '');
    }
    function quipLine(segs) {
      var p = el('p');
      segs.forEach(function (s) {
        if (!s) return;
        p.appendChild(Array.isArray(s) ? el('b', null, s[0]) : document.createTextNode(s));
      });
      return p;
    }
    function buildQuips(d) {
      var t = d.total, tok = t.tokens || 0, out = t.output || 0, scales = [], tangibles = [], habits = [];
      if (tok > 0) {
        // 默认首条：《万叶集》（4,516 首和歌，连题词左注约 45 万 tokens）
        if (tok >= 450000) {
          var r0 = fmtRatio(tok / 450000);
          scales.push(['Token 用量是整部', ['《万叶集》'], '的 ', [r0 + ' 倍'], '——相当于把 4,516 首和歌来回吞吐了 ', [r0 + ' 遍'], '。']);
        } else {
          scales.push(['Token 用量约为', ['《万叶集》'], '的 ', [pct(tok / 450000, 0)], '，折合差不多 ', [Math.max(1, Math.round(tok / 450000 * 4516)).toLocaleString() + ' 首'], ' 和歌的篇幅。']);
        }
        if (tok >= 1100000) scales.push(['总吞吐量相当于百二十回本', ['《红楼梦》'], '的 ', [fmtRatio(tok / 1100000) + ' 倍'], '。']);
        else scales.push(['总吞吐量相当于', ['《红楼梦》'], '前 ', [Math.max(1, Math.round(tok / 1100000 * 120)) + ' 回'], ' 的体量。']);
        if (tok >= 1300000) scales.push(['流经模型的上下文是', ['《三体》三部曲'], '全集的 ', [fmtRatio(tok / 1300000) + ' 倍'], '。']);
        else scales.push(['流经模型的上下文约为', ['《三体》三部曲'], '的 ', [pct(tok / 1300000, 0)], '。']);
        if (tok >= 750000) scales.push(['总 Token 量是托尔斯泰', ['《战争与和平》'], '的 ', [fmtRatio(tok / 750000) + ' 倍'], '。']);
        else scales.push(['总 Token 量约为一部', ['《战争与和平》'], '的 ', [pct(tok / 750000, 0)], '。']);
        if (tok >= 1200000) scales.push(['Token 总量是', ['《莎士比亚全集》'], '（37 部戏剧与十四行诗）的 ', [fmtRatio(tok / 1200000) + ' 倍'], '。']);
        else scales.push(['Token 总量约合 ', [Math.max(1, Math.round(tok / 1200000 * 37)) + ' 部'], ' 莎士比亚戏剧。']);
        if (tok >= 880000) scales.push(['这些 Token 够把', ['《西游记》'], '九九八十一难从头重走 ', [fmtRatio(tok / 880000) + ' 趟'], '。']);
        if (tok >= 4500000) scales.push(['上下文总吞吐已是整部', ['《资治通鉴》'], '（294 卷）的 ', [fmtRatio(tok / 4500000) + ' 倍'], '。']);
        if (tok >= 360000) scales.push(['吞吐的上下文体量是阿波罗 11 号登月计算机全部汇编源码的 ', [fmtRatio(tok / 360000) + ' 倍'], '。']);
        if (tok >= 85000) scales.push(['总 Token 量相当于 Linux 0.01 初版内核源码的 ', [fmtRatio(tok / 85000) + ' 倍'], '。']);
      } else {
        scales.push(['已有 ', [d.prompts.toLocaleString() + ' 次'], ' 提问，暂时还没有计入模型的 token 用量。']);
      }

      if (out > 0) {
        var mins = out / 240;
        var dur = mins >= 60 ? fmtRatio(mins / 60) + ' 小时' : Math.max(1, Math.round(mins)) + ' 分钟';
        tangibles.push(['模型净输出的文字与代码，若按每分钟 60 字不眠不休手敲，得连续敲上 ', [dur], '。']);
        var pages = Math.max(1, Math.round(out / 500));
        tangibles.push(['把模型生成的净输出印在 A4 纸上，能叠出约 ', [pages.toLocaleString() + ' 页'],
          pages >= 1000 ? ' 文稿（足足 ' : ' 文稿。', pages >= 1000 ? [fmtRatio(pages / 500) + ' 包'] : '', pages >= 1000 ? ' 打印纸的厚度）。' : '']);
      }
      if (t.cache_read >= 450000) {
        tangibles.push(['提示词缓存免去了 ', [compact(t.cache_read) + ' tokens'], ' 的重复预读，相当于替模型少翻了 ', [fmtRatio(t.cache_read / 450000) + ' 部《万叶集》'], '。']);
      }
      if (t.thinking > 0 && out > 0) {
        tangibles.push(['模型在正式作答前悄悄推演了 ', [compact(t.thinking) + ' tokens'], ' 的思考链，占全部输出的 ', [pct(t.thinking / out, 0)], '。']);
      }

      if (d.tools > 0 && d.prompts > 0) {
        habits.push(['平均你每提 1 个问题，Agent 就在后台自动执行 ', [(d.tools / d.prompts).toFixed(1) + ' 次'], ' 工具调用（累计 ', [d.tools.toLocaleString() + ' 次'], '）。']);
      }
      if (d.hours && t.n >= 5) {
        var win = [0, 0, 0, 0];
        for (var wd = 0; wd < 7; wd++) for (var hr = 0; hr < 24; hr++) win[Math.floor(hr / 6)] += d.hours[wd][hr];
        var night = win[0] / t.n;
        if (night >= 0.22) {
          habits.push(['有 ', [pct(night, 0)], ' 的回复诞生在凌晨 0–6 点——妥妥的深夜炼丹师作息。']);
        } else {
          var names = ['凌晨（0–6 点）', '上午（6–12 点）', '下午（12–18 点）', '夜间（18–24 点）'], bi = 0;
          for (var wi = 1; wi < 4; wi++) if (win[wi] > win[bi]) bi = wi;
          habits.push(['你最常在', [names[bi]], '与模型并肩推进，贡献了 ', [pct(win[bi] / t.n, 0)], ' 的回复。']);
        }
      }
      if (d.best_streak >= 2) {
        habits.push(['最长曾连续 ', [d.best_streak + ' 天'], ' 每天都在和 Agent 切磋代码' + (d.streak >= 2 ? '，目前正连更 ' : '。'),
          d.streak >= 2 ? [d.streak + ' 天'] : '', d.streak >= 2 ? '。' : '']);
      }
      if (d.top && d.top.length && d.top[0].n >= 10) {
        var tt = d.top[0].title || '未命名会话';
        if (tt.length > 18) tt = tt.slice(0, 17) + '…';
        habits.push(['最重度的一场对话', ['「' + tt + '」'], '单场就往返了 ', [d.top[0].n.toLocaleString() + ' 次'], ' 回复（折合 ', [cost(d.top[0])], '）。']);
      }
      var insights = tangibles.concat(habits), list = [];
      var maxLen = Math.max(scales.length, insights.length);
      for (var qi = 0; qi < maxLen; qi++) {
        if (qi < scales.length) list.push(scales[qi]);
        if (qi < insights.length) list.push(insights[qi]);
      }
      return list;
    }

    function paintDigest(d) {
      if (!digestEl) return;
      digestEl.textContent = '';
      var t = d.total;
      var scopeLbl = d.range.days ? '最近 ' + d.range.days + ' 天' : '全部时间';
      var headRow = el('div', 'side-h');
      headRow.appendChild(el('span', null, '摘要'));
      headRow.appendChild(el('small', null, scopeLbl));
      digestEl.appendChild(headRow);
      if (!t.n && !d.prompts) {
        var emptyBox = el('div', 'quip-card');
        emptyBox.appendChild(el('p', null, '当前筛选范围内还没有用量记录。'));
        digestEl.appendChild(emptyBox);
        return;
      }
      var box = el('div', 'digest-box'), rows = el('div', 'digest-rows');
      var perDay = d.active_days ? (t.cost ? money(t.cost / d.active_days) + ' / 天' : Math.round(t.n / d.active_days) + ' 答 / 天') : '—';
      var dayText = d.active_days + ' 天' + (d.streak >= 2 ? ' · 连更 ' + d.streak + ' 天'
        : d.best_streak >= 2 ? ' · 最长 ' + d.best_streak + ' 天' : '');
      var items = [
        ['估算花费', cost(t)],
        ['活跃日均', perDay],
        ['活跃天数', dayText],
        ['总吞吐量', compact(t.tokens) + ' tokens'],
        ['模型净输出', compact(t.output) + ' tokens']
      ];
      if (t.thinking > 0) items.push(['思考推演', compact(t.thinking) + ' tokens']);
      if (t.rate != null) items.push(['缓存命中', pct(t.rate) + ' · ' + compact(t.cache_read)]);
      items.push(['对话规模', d.sessions + ' 场 · ' + d.prompts + ' 问 · ' + compact(t.n) + ' 答']);
      if (d.tools > 0) items.push(['工具调用', d.tools.toLocaleString() + ' 次' + (d.prompts ? '（' + (d.tools / d.prompts).toFixed(1) + '/问）' : '')]);
      items.push(['主力模型', d.favorite ? d.favorite.name + ' · ' + pct(d.favorite.share, 0) : '—']);
      if (d.projects && d.projects.length) items.push(['头号项目', d.projects[0].proj]);
      items.forEach(function (r) {
        var line = el('div');
        line.appendChild(el('span', null, r[0]));
        var val = el('b', null, r[1]);
        val.title = r[1];
        line.appendChild(val);
        rows.appendChild(line);
      });
      box.appendChild(rows);
      digestEl.appendChild(box);

      var quips = buildQuips(d);
      if (!quips.length) return;
      var qhead = el('div', 'quips-head');
      qhead.appendChild(el('div', 'side-h', '顺便一提'));
      var qcard = el('div', 'quip-card');
      function fillQuips() {
        qcard.textContent = '';
        qcard.appendChild(quipLine(quips[quipStep % quips.length]));
      }
      if (quips.length > 1) {
        var nextBtn = ibtn('refresh', '换一条说法', 'sm');
        nextBtn.onclick = function () { quipStep++; fillQuips(); };
        qhead.appendChild(nextBtn);
      }
      fillQuips();
      digestEl.appendChild(qhead);
      digestEl.appendChild(qcard);
    }

    function draw() {
      // 重画期间页面先撑着原来的高度：画图时要量宽度，量的那一刻内容还没画完，页面变矮会把滚动位置挤回去
      st.style.minHeight = st.offsetHeight + 'px';
      paint();
      st.style.minHeight = '';
    }
    function paint() {
      var d = data, t = d.total;
      hideTip();                            // 指着的那一格马上要被换掉，它的提示框也收起
      if (fillAccounts(d.accounts)) return;
      paintDigest(d);
      spanEl.textContent = d.range.from + ' → ' + d.range.to;
      st.textContent = '';
      if (!t.n && !d.prompts) { st.appendChild(el('p', 'empty', '这段时间里没有用量记录。')); return; }

      // 开头：一个最主要的数字，再加一排小卡片
      var top = el('section', 'st-hero'), big = el('div', 'big');
      big.appendChild(el('b', null, cost(t)));
      big.appendChild(el('span', null, '按 API 价格估算 · ' + (d.range.days ? '最近 ' + d.range.days + ' 天' : '全部时间')
        + (t.unpriced ? ' · ' + t.unpriced + ' 次回复没有价格' : '')));
      top.appendChild(big);
      var kpis = el('div', 'kpis');
      [['Tokens', compact(t.tokens), '其中输出 ' + compact(t.output)],
        ['缓存命中率', pct(t.rate), '读缓存 ' + compact(t.cache_read)],
        ['回复', compact(t.n), d.tools + ' 次工具调用'],
        ['会话', d.sessions, d.prompts + ' 次提问'],
        ['活跃天数', d.active_days, '最长连续 ' + d.best_streak + ' 天 · 当前 ' + d.streak + ' 天'],
        ['最常用的模型', d.favorite ? d.favorite.name : '—', d.favorite ? pct(d.favorite.share, 0) + ' 的回复' : ''],
        ['最忙的时段', d.peak ? '周' + WEEK[d.peak.weekday] + ' ' + pad(d.peak.hour) + ':00' : '—', d.peak ? d.peak.n + ' 次回复' : '']
      ].forEach(function (k) {
        var tile = el('div', 'kpi');
        tile.appendChild(el('span', null, k[0]));
        tile.appendChild(el('b', null, String(k[1])));
        tile.appendChild(el('small', null, k[2]));
        kpis.appendChild(tile);
      });
      top.appendChild(kpis);
      st.appendChild(top);

      var c = card('每天', '按模型分开'), redraw = null;
      toggle(c.head, [['cost', '费用'], ['tokens', 'Tokens']], metric, function (v) {
        metric = v;
        store('st-metric', v);
        redraw();
      });
      redraw = tableToggle(c, 'daily', drawDaily, dailyTable);

      var two = el('div', 'two');
      st.appendChild(two);
      c = card('日历', '每天回复的次数');
      two.appendChild(c.box);
      drawHeat(c.body);
      c = card('时段', '一周里什么时候在用');
      two.appendChild(c.box);
      drawHours(c.body);

      c = card('模型', '颜色和上面每天的图一致');
      c.body.appendChild(grid(['模型', '回复', '未缓存的输入', '输出', '其中思考', '读缓存', '写缓存', '命中率', '费用'], d.models.map(function (m) {
        return [swatch(slotClass(m.slot), m.name), compact(m.n), compact(m.input), compact(m.output), compact(m.thinking),
          compact(m.cache_read), compact(m.cache_write), pct(m.rate, 0), m.priced ? money(m.cost) : '—'];
      }), { share: d.models.map(function (m) { return t.cost ? m.cost / t.cost : 0; }) }));

      if (d.by_account.length || d.quota.length) {
        c = card('账号', d.quota.length ? '额度是应用自己记下的最近一次：5 小时窗口和 7 天窗口用了多少' : '');
        c.body.appendChild(grid(['账号', '会话', '回复', 'Tokens', '命中率', '费用'], d.by_account.map(function (a) {
          return [a.key ? acctChip(a) : '（未知账号）', a.sessions, compact(a.n), compact(a.tokens), pct(a.rate, 0), cost(a)];
        }), { share: d.by_account.map(function (a) { return t.cost ? a.cost / t.cost : 0; }) }));
        if (d.quota.length) {
          var qs = el('div', 'quota');
          d.quota.forEach(function (q) {
            var b = el('div', 'qcard'), h = el('div', 'qh');
            h.appendChild(acctChip({ key: q.org, name: q.account, email: q.email }));
            h.appendChild(el('small', null, '记于 ' + ago(q.t)));
            b.appendChild(h);
            b.appendChild(meter('5 小时', q.five_hour));
            b.appendChild(meter('7 天', q.seven_day));
            var sp = el('div', 'qs');
            sp.appendChild(spark(q.trend));
            sp.appendChild(el('small', null, '最近 7 天里 7 天窗口的变化'));
            b.appendChild(sp);
            qs.appendChild(b);
          });
          c.body.appendChild(qs);
        }
      }

      two = el('div', 'two');
      st.appendChild(two);
      c = card('推理强度', '');
      two.appendChild(c.box);
      c.body.appendChild(grid(['推理强度', '回复', '输出', '其中思考', '费用'], d.efforts.map(function (e) {
        return [e.effort || '（未记录）', compact(e.n), compact(e.output), compact(e.thinking), money(e.cost)];
      }), { share: d.efforts.map(function (e) { return t.cost ? e.cost / t.cost : 0; }) }));
      c = card('项目', '前 20 个');
      two.appendChild(c.box);
      c.body.appendChild(grid(['项目', '会话', '回复', 'Tokens', '费用'], d.projects.map(function (p) {
        return [p.proj + (source === 'all' && p.src === 'codex' ? '（Codex）' : ''), p.sessions, compact(p.n), compact(p.tokens), cost(p)];
      }), { share: d.projects.map(function (p) { return t.cost ? p.cost / t.cost : 0; }) }));
      c = card('花得最多的会话', '');
      var ol = el('ol', 'toplist');
      d.top.forEach(function (x) {
        var li = el('li'), a = el('a', null, x.title);
        a.href = '/s/' + x.page;
        li.appendChild(a);
        var meta = el('small', null, x.proj + (x.account ? ' · ' + x.account : '') + ' · ' + compact(x.n) + ' 次回复');
        li.appendChild(meta);
        li.appendChild(el('b', null, cost(x)));
        ol.appendChild(li);
      });
      c.body.appendChild(ol);
    }

    window.addEventListener('resize', debounce(function () { if (data) draw(); }, 200));
    paintRange();
    pickSource(store('src') || 'claude');
    load();
  }
})();
