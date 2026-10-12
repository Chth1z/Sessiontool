// 服务模式和导出的独立文件共用这一份脚本；独立文件里没有的控件都先判断再用
(function () {
  'use strict';

  /* ================= 小工具 ================= */

  var body = document.body, root = document.documentElement;
  var isIndex = body.classList.contains('index'), isSession = body.classList.contains('session');
  var live = !!body.dataset.state;          // 有本地服务可以问（导出的独立文件没有）
  var SVG = 'http://www.w3.org/2000/svg';

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return [].slice.call((r || document).querySelectorAll(s)); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function icon(name) {
    var s = document.createElementNS(SVG, 'svg'), u = document.createElementNS(SVG, 'use');
    s.setAttribute('class', 'ic');
    s.setAttribute('aria-hidden', 'true');
    u.setAttribute('href', '#i-' + name);
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
  function store(k, v) {                    // 长期记住的选择：主题、视图、自动刷新、读到哪了
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
    return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable;
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
  function bytes(n) { return n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GB' : (n / 1048576).toFixed(1) + ' MB'; }
  function span(a, b) {
    var ms = new Date(b) - new Date(a);
    if (!(ms >= 0)) return '';
    var m = Math.floor(ms / 60000), h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (d >= 1) return d + ' 天 ' + (h % 24) + ' 小时';
    if (h >= 1) return h + ' 小时 ' + (m % 60) + ' 分';
    return Math.max(m, 1) + ' 分钟';
  }
  function reveal(node) {
    for (var p = node; p; p = p.parentNode) if (p.tagName === 'DETAILS') p.open = true;
  }
  // 一次开合很多折叠块时关掉动画，否则几十个高度动画一起跑会卡
  function bulk(fn) {
    body.classList.add('bulk');
    fn();
    requestAnimationFrame(function () { requestAnimationFrame(function () { body.classList.remove('bulk'); }); });
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
  var PERMISSION = { 'default': '每次询问', acceptEdits: '自动接受编辑', plan: '计划模式', auto: '自动判断', bypassPermissions: '跳过权限确认' };
  var STATUS = { completed: '已完成', review_ready: '等你过目', blocked: '受阻', in_progress: '进行中', needs_input: '等你处理', failed: '失败' };

  function fillInfo(b, d) {
    var t = el('div', 'dtitle');
    t.appendChild(el('strong', null, d.title));
    var tags = el('div', 'dtags');
    var proj = el('span', 'badge', d.proj);
    tags.appendChild(proj);
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
    if (isIndex) {
      var go = el('a', 'go', '打开这个会话');
      go.href = '/s/' + d.page;
      b.appendChild(go);
    }

    var s = section(b, '标识');
    if (d.id) s.appendChild(field('应用会话 ID', d.id, { hint: '在 Claude 里提到这个会话时用它' }));
    s.appendChild(field('记录 ID', d.cli, { hint: '当前记录文件的编号，可以用来恢复会话' }));
    d.files.filter(function (f) { return !f.current; }).forEach(function (f) { s.appendChild(field('更早的记录 ID', f.id)); });
    s.appendChild(field('恢复命令', d.resume, { hint: '在终端里的项目文件夹下运行' }));
    if (d.link) s.appendChild(field('应用链接', d.link));

    s = section(b, '位置');
    s.appendChild(field('项目文件夹', d.cwd || '（未知）'));
    d.files.forEach(function (f) { s.appendChild(field(f.current ? '记录文件（当前）' : '记录文件', f.path, { note: bytes(f.size) })); });

    s = section(b, '时间');
    pairs(s, [['创建', stamp(d.created)], ['第一条消息', stamp(d.first)], ['最后活动', stamp(d.last)], ['前后跨度', span(d.first, d.last)]]);

    s = section(b, '模型与设置');
    var models = (d.models || []).map(function (m) { return m[0] + '（' + m[1] + ' 次回复）'; }).join('、') || d.model;
    pairs(s, [['模型', models], ['推理强度', d.effort], ['权限模式', PERMISSION[d.permission] || d.permission],
      ['完成的轮数', d.turns != null ? String(d.turns) : ''], ['写入过的分支', (d.branches || []).join('、')]]);

    s = section(b, '数量');
    var c = d.counts;
    tiles(s, [['提问', c.prompts], ['答复', c.replies], ['工具调用', c.tools], ['工具截图', c.shots, 1], ['你发的图片', c.images, 1],
      ['发给你的文件', c.sent, 1], ['修改的文件', c.changed, 1], ['上下文压缩', c.compact, 1], ['改写', c.branch, 1],
      ['记录文件', c.records], ['记录大小', bytes(d.size)]]);

    var k = d.tokens || {};
    if (k.output || k.input || k.cache_read) {
      s = section(b, 'Token 用量');
      tiles(s, [['输出', k.output], ['输入', k.input], ['读取缓存', k.cache_read], ['写入缓存', k.cache_write]]);
      s.appendChild(el('small', 'hint', '按回复去重后的合计。复刻的会话包含复刻点之前的部分。'));
    }

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
    var rows = [['/', '聚焦搜索框'], ['R', '刷新，读取最新记录'], ['?', '打开这张快捷键表'], ['Esc', '关闭浮层、清空搜索']];
    if (isIndex) rows = rows.concat([['J  K  ↓  ↑', '在会话和搜索结果之间移动'], ['Enter', '打开选中的会话'], ['I', '选中会话的详情'], ['C', '复制选中会话的 ID']]);
    if (isSession) rows = rows.concat([['J  K', '下一条 / 上一条你的提问'], ['1  2  3', '完整 / 对话 / 结果视图'], ['E', '折起或展开当前这一轮的过程'],
      ['I', '会话详情'], ['Enter  Shift+Enter', '搜索时跳到下一处 / 上一处'], ['←  →', '放大图片时切换上一张 / 下一张']]);
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
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (d.classList && d.classList.contains('tool') && d.open) fillTool(d);
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

  var marks = [], cur = -1, findBar = null, activeQ = '';
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
  // near：优先停在这个元素里的第一处；quiet：只更新标记，不滚动页面（刷新后用）
  function highlight(q, near, quiet) {
    var keep = quiet ? cur : -1;
    clearMarks();
    activeQ = q;
    var words = terms(q);
    if (!words.length) return;
    $$('main .msg .body, main .step > .body, main .sent, main details.fold > .body, main details.tool[open] > .tc').forEach(function (scope) {
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

  /* ================= 刷新：只换有变化的部分 ================= */

  var refreshing = false, pendingSig = null, hint = null;
  var auto = store('auto') === '1';
  var swap = null;                          // 各页面自己的替换逻辑，下面分别赋值

  function refresh(silent) {
    if (refreshing || !live || !swap) return;
    refreshing = true;
    var btn = $('[data-act="refresh"]'), t0 = Date.now();
    if (btn) btn.classList.add('spin');
    fetch(location.pathname + '?fresh=1').then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }).then(function (text) {
      var res = swap(new DOMParser().parseFromString(text, 'text/html'));
      pendingSig = null;
      if (hint) { hint.close(); hint = null; }
      if (!silent) toast(res.changed ? res.text : '已是最新 · ' + clock(new Date()), res.changed && res.action ? res.action : null);
    }).catch(function () {
      if (!silent) toast('刷新失败：本地服务没有响应，请确认 Sessiontool 的窗口还开着。', { ms: 5000 });
    }).then(function () {
      // 转圈至少转半秒，太快的话看不出按下去有没有反应
      setTimeout(function () { refreshing = false; if (btn) btn.classList.remove('spin'); }, Math.max(0, 500 - (Date.now() - t0)));
    });
  }

  function setAuto(on) {
    auto = on;
    store('auto', on ? '1' : '0');
    $$('[data-act="auto"]').forEach(function (b) { b.classList.toggle('on', on); b.setAttribute('aria-checked', on); });
    var box = $('#auto');
    if (box) box.checked = on;
    if (on && pendingSig) refresh(true);
  }

  // 每隔几秒问一下服务有没有新记录：开了自动刷新就直接更新，否则提示一下
  if (live) {
    var misses = 0;
    var poll = setInterval(function () {
      if (document.hidden || refreshing) return;
      fetch(body.dataset.state).then(function (r) { return r.json(); }).then(function (j) {
        misses = 0;
        if (j.sig === body.dataset.sig) return;
        if (auto) { refresh(true); return; }
        if (j.sig === pendingSig) return;
        pendingSig = j.sig;
        if (hint) hint.close();
        hint = toast('有新的记录', { action: '刷新', run: function () { refresh(false); }, sticky: true });
      }).catch(function () { if (++misses >= 3) clearInterval(poll); });       // 服务关掉了就不再问
    }, 5000);
  }

  /* ================= 点击与按键的统一入口 ================= */

  var ACTIONS = {
    refresh: function () { refresh(false); },
    keys: openKeys,
    auto: function (b) { setAuto(!auto); toast(auto ? '已开启：有新记录时自动刷新' : '已关闭自动刷新'); var m = b.closest('details'); if (m) m.open = false; }
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
    else if (e.key === 'r' && live) { e.preventDefault(); refresh(false); }
  }, true);

  /* ================= 会话页 ================= */

  if (isSession) {
    var flow = $('#flow'), page = body.dataset.page || '';

    // 三种视图：完整 / 对话（隐藏工具调用）/ 结果（折起每轮的中间过程，只留最终答复）
    var views = $$('#view button'), view = 'full';
    function setView(v, keep) {
      if (['full', 'chat', 'result'].indexOf(v) < 0) v = 'full';
      view = v;
      views.forEach(function (b) { b.classList.toggle('on', b.dataset.v === v); });
      bulk(function () {
        body.classList.toggle('chat', v === 'chat');
        $$('details.steps').forEach(function (d) { d.open = v !== 'result'; });
      });
      if (keep) store('view', v);
    }
    views.forEach(function (b) { b.onclick = function () { keepPlace(function () { setView(b.dataset.v, true); }); }; });

    // 改变页面高度的操作（切视图、折起过程）前后，让眼前这条消息留在原位
    function keepPlace(fn) {
      var blocks = [].slice.call(flow.children), ref = null, at = 0, top = 0;
      for (var i = 0; i < blocks.length; i++) {
        var r = blocks[i].getBoundingClientRect();
        if (r.bottom > 70) { ref = blocks[i]; at = i; top = r.top; break; }
      }
      fn();
      if (ref && !ref.isConnected) ref = flow.children[at];       // 这一块刚被换成了新的
      if (ref) window.scrollBy(0, ref.getBoundingClientRect().top - top);
    }

    ACTIONS.info = function () { openInfo(page); };
    ACTIONS.top = function () { window.scrollTo(0, 0); };
    ACTIONS.end = function () { window.scrollTo(0, root.scrollHeight); };
    ACTIONS.tools = function (b) {
      var all = $$('details.tools'), open = !all.some(function (x) { return x.open; });
      bulk(function () {
        if (open) $$('details.steps').forEach(function (d) { d.open = true; });
        all.forEach(function (x) { x.open = open; });
      });
      b.firstChild.textContent = open ? '收起全部工具调用' : '展开全部工具调用';
      b.closest('details').open = false;
    };
    // 过程很长时，读到底部也能把它折起来，并回到这一轮的开头
    ACTIONS.fold = function (b) {
      var d = b.closest('details.steps');
      bulk(function () { d.open = false; });        // 这里要立刻定位，所以不带收起动画
      d.scrollIntoView({ block: 'center' });
    };

    // 左侧目录跟随阅读位置；顺便记住读到哪一条，下次打开可以接着读
    var prompts = [], links = {}, active = null, totop = null;
    function collect() {
      prompts = $$('#flow > .turn > .msg.user[id]');
      links = {};
      $$('nav .toc a').forEach(function (a) { links[a.getAttribute('href').slice(1)] = a; });
      active = null;
    }
    function current() {
      var best = null;
      for (var i = 0; i < prompts.length; i++) {
        if (prompts[i].getBoundingClientRect().top <= window.innerHeight * 0.4) best = prompts[i]; else break;
      }
      return best;
    }
    // moved：是你滚动页面引起的。只有这时才更新“读到哪了”，刚打开页面时不能把上次的位置冲掉
    function spy(moved) {
      if (totop) totop.classList.toggle('on', window.scrollY > window.innerHeight * 1.5);
      var best = current(), a = best && links[best.id];
      if (a === active) return;
      if (active) active.classList.remove('on');
      active = a;
      if (a) {
        a.classList.add('on');
        a.scrollIntoView({ block: 'nearest' });
      }
      if (moved && page) store('pos:' + page, best && best !== prompts[0] ? best.id : null);
    }
    function step(dir) {
      var idx = -1;
      for (var i = 0; i < prompts.length; i++) if (prompts[i].getBoundingClientRect().top <= 90) idx = i;
      var next = prompts[Math.max(0, Math.min(prompts.length - 1, idx + dir))];
      if (next) next.scrollIntoView({ block: 'start' });
    }
    function turnInView() {
      var turns = $$('#flow > .turn'), y = window.innerHeight * 0.4, hit = null;
      turns.forEach(function (t) { var r = t.getBoundingClientRect(); if (r.top <= y && r.bottom >= y) hit = t; });
      return hit;
    }

    function jump() {
      var h = decodeURIComponent(location.hash.slice(1));
      if (!h) return null;
      var t = document.getElementById(h);
      if (!t && h.slice(0, 2) === 'r-') t = $('[data-r="' + h.slice(2).replace(/[^\w]/g, '') + '"]');
      if (!t) return null;
      reveal(t);
      t.scrollIntoView({ block: 'start' });
      $$('.flash').forEach(function (x) { x.classList.remove('flash'); });
      void t.offsetWidth;                   // 让同一个目标再次被点到时也重新闪一下
      t.classList.add('flash');
      return t;
    }

    // 刷新：标题区整个换；对话按块比较内容指纹，只换有变化的块和新增的块
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
    }
    swap = function (doc) {
      var nb = doc.body, nflow = $('#flow', doc);
      if (!nflow || nb.dataset.sig === body.dataset.sig) return { changed: false };
      var olds = [].slice.call(flow.children), news = [].slice.call(nflow.children), i = 0;
      while (i < olds.length && i < news.length && olds[i].dataset.k === news[i].dataset.k) i++;
      var atEnd = window.innerHeight + window.scrollY >= root.scrollHeight - 200;
      var turnsBefore = $$('#flow > .turn').length;
      keepPlace(function () {
        var head = $('main > .head'), nhead = document.adoptNode($('main > .head', doc)), filesOpen = !!$('.files[open]', head);
        head.replaceWith(nhead);
        if (filesOpen && $('.files', nhead)) $('.files', nhead).open = true;
        var fresh = [];
        for (var j = i; j < news.length; j++) {
          var n = document.adoptNode(news[j]);
          if (olds[j]) keepOpen(olds[j], n);
          else {
            n.classList.add('new');
            if (view === 'result') $$('details.steps', n).forEach(function (d) { d.open = false; });
          }
          fresh.push(n);
        }
        bulk(function () {
          olds.slice(i).forEach(function (o) { o.remove(); });
          fresh.forEach(function (n) { flow.appendChild(n); awaitImages(n); });
        });
      });
      $('nav .toc').innerHTML = $('nav .toc', doc).innerHTML;
      if ($('#info') && $('#info', doc)) $('#info').textContent = $('#info', doc).textContent;
      body.dataset.sig = nb.dataset.sig;
      document.title = doc.title;
      collect();
      spy();
      if (activeQ) highlight(activeQ, null, true);
      if (atEnd) window.scrollTo(0, root.scrollHeight);           // 本来就在看最新的，就继续跟着
      var more = $$('#flow > .turn').length - turnsBefore;
      return { changed: true, text: more > 0 ? '已更新 · 新增 ' + more + ' 轮对话' : '已更新到最新内容',
        action: atEnd ? null : { action: '跳到最新', run: ACTIONS.end } };
    };

    // 初始化
    setView(store('view') || 'full', false);
    collect();
    totop = ibtn('up', '回到开头');
    totop.className += ' totop';
    totop.dataset.act = 'top';
    body.appendChild(totop);
    setAuto(auto);
    window.addEventListener('scroll', debounce(function () { spy(true); }, 60), { passive: true });

    var fq = $('#fq'), target = jump(), q0 = '';
    if (fq) {
      q0 = new URLSearchParams(location.search).get('q') || '';
      if (q0) { fq.value = q0; highlight(q0, target); }
      fq.oninput = debounce(function () { highlight(fq.value.trim(), null); }, 250);
      fq.onkeydown = function (e) {
        if (e.key === 'Enter') go(e.shiftKey ? -1 : 1);
        if (e.key === 'Escape') { fq.value = ''; highlight('', null); fq.blur(); }
      };
    }
    window.addEventListener('hashchange', jump);

    // 上次读到的位置：不擅自跳过去，给一个入口
    if (page && !target && !q0) {
      var last = document.getElementById(store('pos:' + page) || '');
      if (last && last.getBoundingClientRect().top > window.innerHeight * 1.2) {
        var num = $('.num', last);
        toast('上次读到 ' + (num ? num.textContent : '这里'), { action: '接着读', run: function () { last.scrollIntoView({ block: 'start' }); } });
      }
    }
    spy();

    document.addEventListener('keydown', function (e) {
      if (box || layer || typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      var k = e.key;
      if (k === 'j') step(1);
      else if (k === 'k') step(-1);
      else if (k === '/' && fq) { e.preventDefault(); fq.focus(); fq.select(); }
      else if (k === 'i' && $('#info')) openInfo(page);
      else if (k === '1' || k === '2' || k === '3') keepPlace(function () { setView(['full', 'chat', 'result'][k - 1], true); });
      else if (k === 'e') {
        var t = turnInView(), d = t && $('details.steps', t);
        if (d) keepPlace(function () { bulk(function () { d.open = !d.open; }); });
      }
    });
  }

  /* ================= 索引页 ================= */

  if (isIndex) {
    var q = $('#q'), ar = $('#ar'), tl = $('#tl'), hits = $('#hits'), cnt = $('#cnt'), list = $('#list');
    var project = '', seq = 0;
    var WHO = { user: ['你', 'who-you'], asst: ['Claude', 'who-claude'], tool: ['工具', ''] };
    function rows() { return $$('#list .row'); }

    function remember() { tab('idx', { p: project, ar: ar.checked, tl: tl.checked, q: q.value }); }
    function pick(p) {
      var tabs = $$('#pj .tab');
      if (!tabs.some(function (x) { return x.dataset.p === p; })) p = '';
      project = p;
      tabs.forEach(function (x) { x.classList.toggle('on', x.dataset.p === p); });
    }

    // 有搜索词时列表只留标题命中的会话：内容命中的已经在上面的结果里
    function filter() {
      var words = terms(q.value), n = 0;
      rows().forEach(function (r) {
        var ok = (!project || r.dataset.p === project) && (ar.checked || !r.dataset.a);
        if (ok && words.length) ok = words.every(function (w) { return r.dataset.t.indexOf(w) >= 0; });
        r.hidden = !ok;
        if (ok) n++;
      });
      $$('#list .bucket').forEach(function (b) { b.hidden = !$('.row:not([hidden])', b); });
      cnt.textContent = n;
    }
    function allowed(pg) {
      var row = $('#list .row[data-page="' + pg + '"]');
      return !row || ((!project || row.dataset.p === project) && (ar.checked || !row.dataset.a));
    }
    function show(j) {
      hits.textContent = '';
      var shown = j.sessions.filter(function (s) { return allowed(s.page); });
      var total = shown.reduce(function (n, s) { return n + s.n; }, 0);
      hits.appendChild(el('div', 'meta', shown.length ? '对话内容：' + total + ' 处，分布在 ' + shown.length + ' 个会话'
        : '对话内容里没有找到“' + j.q + '”。'));
      shown.forEach(function (s) {
        var box = el('div', 'hs'), base = '/s/' + s.page + '?q=' + encodeURIComponent(j.q);
        var a = el('a', null, s.title);
        a.href = base;
        box.appendChild(a);
        box.appendChild(el('small', null, '　' + s.n + ' 处'));
        var ul = el('ul');
        s.hits.forEach(function (h) {
          var li = el('li'), link = el('a');
          link.href = base + '#' + h.anchor;
          link.appendChild(el('small', null, h.time + '　'));
          link.appendChild(el('small', WHO[h.who][1], WHO[h.who][0] + '　'));
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
      fetch('/api/search?q=' + encodeURIComponent(v) + '&tools=' + (tl.checked ? 1 : 0))
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

    swap = function (doc) {
      var nb = doc.body;
      $('#synced').textContent = $('#synced', doc).textContent;
      if (nb.dataset.sig === body.dataset.sig) return { changed: false };
      list.classList.add('still');          // 换进来的行不再播放入场动画
      list.innerHTML = $('#list', doc).innerHTML;
      $('#pj').innerHTML = $('#pj', doc).innerHTML;
      $('#totals').textContent = $('#totals', doc).textContent;
      body.dataset.sig = nb.dataset.sig;
      pick(project);
      run();
      return { changed: true, text: '会话列表已更新' };
    };

    document.addEventListener('click', function (e) {
      var t = e.target.closest('.tab');
      if (t) { pick(t.dataset.p); window.scrollTo(0, 0); run(); return; }
      // 点进会话时给标题起个过渡名字，新页面的大标题会从这里“长”出来
      var cover = e.target.closest('.cover');
      if (cover) {
        $$('#list .title').forEach(function (x) { x.style.viewTransitionName = ''; });      // 名字在页面里必须唯一
        $('.title', cover.parentNode).style.viewTransitionName = 'title';
      }
    });
    q.oninput = debounce(run, 200);
    ar.onchange = tl.onchange = run;
    $('#auto').onchange = function () { setAuto(this.checked); };
    setAuto(auto);

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
    pick(saved.p || '');
    var from = /\/s\/([0-9a-f]+)/.exec(document.referrer || '');
    if (from) {
      var back = $('#list .row[data-page="' + from[1] + '"] .title');
      if (back) back.style.viewTransitionName = 'title';
      list.classList.add('still');
    }
    if (q.value) run(); else filter();
    if (from) window.scrollTo(0, tab('idx-y') || 0);
    else q.focus({ preventScroll: true });      // 新打开时光标直接在搜索框里，可以马上输入
    window.addEventListener('pagehide', function () { tab('idx-y', window.scrollY); });
  }
})();
