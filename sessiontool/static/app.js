// 服务模式和导出的独立文件共用这一份脚本；独立文件里没有的控件都先判断再用
(function () {
  'use strict';
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return [].slice.call((r || document).querySelectorAll(s)); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function debounce(fn, ms) {
    var t;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }
  function store(k, v) {
    try {
      if (v === undefined) return localStorage.getItem(k);
      if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v);
    } catch (e) { return null; }
  }
  function typing(e) {
    var t = e.target;
    return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable;
  }
  function terms(q) { return q.toLowerCase().split(/\s+/).filter(Boolean); }

  /* ---------- 主题：跟随系统 → 浅色 → 深色 ---------- */

  var themeBtn = $('#theme');
  var THEMES = [[null, '◐ 自动'], ['light', '☀ 浅色'], ['dark', '☾ 深色']];
  function themeIndex() {
    var cur = document.documentElement.dataset.theme || null;
    for (var i = 0; i < THEMES.length; i++) if (THEMES[i][0] === cur) return i;
    return 0;
  }
  if (themeBtn) {
    themeBtn.textContent = THEMES[themeIndex()][1];
    themeBtn.onclick = function () {
      var next = THEMES[(themeIndex() + 1) % THEMES.length];
      if (next[0]) document.documentElement.dataset.theme = next[0];
      else delete document.documentElement.dataset.theme;
      store('theme', next[0]);
      themeBtn.textContent = next[1];
    };
  }

  /* ---------- 有新记录时提示刷新 ---------- */

  var body = document.body;
  if (body.dataset.state) {
    var told = false, misses = 0;       // 服务关掉后连续几次连不上就不再问了
    var poll = setInterval(function () {
      if (told || document.hidden) return;
      fetch(body.dataset.state).then(function (r) { return r.json(); }).then(function (j) {
        misses = 0;
        if (told || j.sig === body.dataset.sig) return;
        told = true;
        var toast = el('div', 'toast');
        toast.appendChild(el('span', null, '有新的记录'));
        var b = el('button', null, '刷新');
        b.onclick = function () { location.reload(); };
        toast.appendChild(b);
        body.appendChild(toast);
      }).catch(function () { if (++misses >= 3) clearInterval(poll); });
    }, 8000);
  }

  /* ---------- 会话页 ---------- */

  function reveal(node) {
    for (var p = node; p; p = p.parentNode) if (p.tagName === 'DETAILS') p.open = true;
  }

  // 工具详情在展开时才向本地服务要，页面本身只带一行摘要
  function fillTool(d) {
    if (d.dataset.done || !d.dataset.u) return;
    d.dataset.done = '1';
    var box = $('.tc', d);
    box.textContent = '加载中…';
    fetch(d.dataset.u).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (j) {
      box.textContent = '';
      var inp = j.input;
      if (inp && typeof inp === 'object' && !Array.isArray(inp)) {
        Object.keys(inp).forEach(function (k) {
          var v = inp[k], s = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
          if (s.length < 90 && s.indexOf('\n') < 0) {
            var row = el('div', 'kv');
            row.appendChild(el('span', 'k', k));
            row.appendChild(el('span', 'v', s));
            box.appendChild(row);
          } else {
            box.appendChild(el('div', 'k', k));
            box.appendChild(el('pre', null, s));
          }
        });
      } else if (inp != null) {
        box.appendChild(el('pre', null, JSON.stringify(inp, null, 2)));
      }
      if (j.result == null) {
        box.appendChild(el('div', 'k', '（没有记录到输出）'));
      } else if (j.result || !j.images.length) {
        box.appendChild(el('div', 'k', j.error ? '输出（失败）' : '输出'));
        box.appendChild(el('pre', j.error ? 'err' : null, j.result || '（空）'));
      }
      if (j.full) {
        box.appendChild(el('div', 'k', '完整输出（保存在 tool-results 里的文件）'));
        box.appendChild(el('pre', null, j.full));
      }
      if (j.images.length) {
        var pics = el('div', 'pics');
        j.images.forEach(function (src) {
          var im = el('img', 'pic');
          im.loading = 'lazy'; im.alt = '截图'; im.src = src;
          pics.appendChild(im);
        });
        box.appendChild(pics);
      }
      if (activeQ) highlight(activeQ, d);     // 从搜索结果跳到这次工具调用时，把命中的地方标出来
    }).catch(function () {
      d.dataset.done = '';
      box.textContent = '加载失败，收起后再展开可重试。';
    });
  }
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (d.classList && d.classList.contains('tool') && d.open) fillTool(d);
  }, true);

  // 原文件已经不在的图片直接去掉，不留破图
  document.addEventListener('error', function (e) {
    var t = e.target;
    if (t.tagName === 'IMG' && t.classList.contains('pic')) t.remove();
  }, true);

  // 点图片放大，再点或按 Esc 关闭
  document.addEventListener('click', function (e) {
    var t = e.target;
    $$('details.menu[open]').forEach(function (m) { if (!m.contains(t)) m.open = false; });
    if (t.classList && t.classList.contains('pic')) {
      var box = el('div', 'box'), im = el('img');
      im.src = t.src;
      box.appendChild(im);
      box.onclick = function () { box.remove(); };
      body.appendChild(box);
    } else if (t.classList && t.classList.contains('copy')) {
      var src = $('.body', t.closest('.msg')), text = src ? src.innerText : '';
      var done = function () {
        t.textContent = '已复制';
        setTimeout(function () { t.textContent = '复制'; }, 1200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done);
      else {
        var ta = el('textarea');
        ta.value = text; body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); done(); } catch (err) {}
        ta.remove();
      }
    }
  });

  // 会话内搜索：把命中的文字包进 <mark>，右下角切换
  var marks = [], cur = -1, bar = null, activeQ = '';
  function clearMarks() {
    marks.forEach(function (m) {
      var p = m.parentNode;
      if (!p) return;
      p.replaceChild(document.createTextNode(m.textContent), m);
      p.normalize();
    });
    marks = []; cur = -1;
    if (bar) { bar.remove(); bar = null; }
  }
  function go(step) {
    if (!marks.length) return;
    if (cur >= 0) marks[cur].classList.remove('cur');
    cur = (cur + step + marks.length) % marks.length;
    var m = marks[cur];
    m.classList.add('cur');
    reveal(m);
    m.scrollIntoView({ block: 'center', behavior: 'auto' });
    bar.firstChild.textContent = (cur + 1) + ' / ' + marks.length;
  }
  function markAll(root, word) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes = [], n;
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
  function highlight(q, near) {
    clearMarks();
    activeQ = q;
    var words = terms(q);
    if (!words.length) return;
    $$('main .msg .body, main .step > .body, main .sent, main details.fold > .body, main details.tool[open] > .tc').forEach(function (root) {
      words.forEach(function (w) { markAll(root, w); });
    });
    marks.sort(function (a, b) { return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1; });
    bar = el('div', 'find');
    bar.appendChild(el('span', null, marks.length ? '' : '对话文字里没有找到（工具调用展开后才会被搜索）'));
    if (marks.length) {
      var up = el('button', null, '↑'), down = el('button', null, '↓');
      up.title = '上一处（Shift+Enter）'; down.title = '下一处（Enter）';
      up.onclick = function () { go(-1); };
      down.onclick = function () { go(1); };
      bar.appendChild(up); bar.appendChild(down);
    }
    body.appendChild(bar);
    if (!marks.length) return;
    var start = 0;
    if (near) {
      for (var k = 0; k < marks.length; k++) if (near.contains(marks[k])) { start = k; break; }
    }
    cur = start - 1;
    go(1);
  }

  function jump() {
    var h = decodeURIComponent(location.hash.slice(1));
    if (!h) return null;
    var t = document.getElementById(h);
    if (!t && h.slice(0, 2) === 'r-') t = $('[data-r="' + h.slice(2).replace(/[^\w]/g, '') + '"]');
    if (!t) return null;
    reveal(t);
    t.scrollIntoView({ block: 'start', behavior: 'auto' });
    $$('.flash').forEach(function (x) { x.classList.remove('flash'); });
    t.classList.add('flash');
    return t;
  }

  if (body.classList.contains('session')) {
    // 三种视图：完整 / 对话（隐藏工具调用）/ 结果（折起每轮的中间过程，只留最终答复）
    var views = $$('#view button');
    function setView(v, keep) {
      if (['full', 'chat', 'result'].indexOf(v) < 0) v = 'full';
      views.forEach(function (b) { b.classList.toggle('on', b.dataset.v === v); });
      body.classList.toggle('chat', v === 'chat');
      $$('details.steps').forEach(function (d) { d.open = v !== 'result'; });
      if (keep) store('view', v);
    }
    views.forEach(function (b) { b.onclick = function () { setView(b.dataset.v, true); }; });
    setView(store('view') || 'full', false);
    var toolsBtn = $('[data-act="tools"]');
    toolsBtn.onclick = function () {
      var all = $$('details.tools'), open = !all.some(function (x) { return x.open; });
      if (open) $$('details.steps').forEach(function (d) { d.open = true; });
      all.forEach(function (x) { x.open = open; });
      toolsBtn.textContent = open ? '收起全部工具调用' : '展开全部工具调用';
      toolsBtn.closest('details').open = false;
    };
    $('[data-act="top"]').onclick = function () { window.scrollTo({ top: 0, behavior: 'auto' }); };
    $('[data-act="end"]').onclick = function () { window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'auto' }); };

    // 左侧目录跟随阅读位置
    var prompts = $$('main > .turn > .msg.user[id]'), links = {};
    $$('nav a[href^="#m-"]').forEach(function (a) { links[a.getAttribute('href').slice(1)] = a; });
    var active = null;
    function spy() {
      var best = null;
      for (var i = 0; i < prompts.length; i++) {
        if (prompts[i].getBoundingClientRect().top <= window.innerHeight * 0.4) best = prompts[i]; else break;
      }
      var a = best && links[best.id];
      if (a === active) return;
      if (active) active.classList.remove('on');
      active = a;
      if (a) {
        a.classList.add('on');
        a.scrollIntoView({ block: 'nearest', behavior: 'auto' });
      }
    }
    window.addEventListener('scroll', debounce(spy, 60), { passive: true });

    function step(dir) {
      var idx = -1;
      for (var i = 0; i < prompts.length; i++) if (prompts[i].getBoundingClientRect().top <= 80) idx = i;
      var next = prompts[Math.max(0, Math.min(prompts.length - 1, idx + dir))];
      if (next) next.scrollIntoView({ block: 'start', behavior: 'auto' });
    }

    var fq = $('#fq'), target = jump();
    if (fq) {
      var q0 = new URLSearchParams(location.search).get('q') || '';
      if (q0) { fq.value = q0; highlight(q0, target); }
      fq.oninput = debounce(function () { highlight(fq.value.trim(), null); }, 250);
      fq.onkeydown = function (e) {
        if (e.key === 'Enter') go(e.shiftKey ? -1 : 1);
        if (e.key === 'Escape') { fq.value = ''; highlight('', null); fq.blur(); }
      };
    }
    window.addEventListener('hashchange', jump);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { var box = $('.box'); if (box) box.remove(); }
      if (e.key === 'Escape') $$('details.menu[open]').forEach(function (m) { m.open = false; });
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'j') step(1);
      else if (e.key === 'k') step(-1);
      else if (e.key === '/' && fq) { e.preventDefault(); fq.focus(); fq.select(); }
    });
    spy();
  }

  /* ---------- 索引页 ---------- */

  if (body.classList.contains('index')) {
    var q = $('#q'), ar = $('#ar'), tl = $('#tl'), hits = $('#hits'), cnt = $('#cnt');
    var rows = $$('#list .row'), chips = $$('#pj .tab'), project = '', seq = 0;
    var WHO = { user: ['你', 'who-you'], asst: ['Claude', 'who-claude'], tool: ['工具', ''] };

    // 有搜索词时列表只留标题命中的会话：内容命中的已经在上面的结果里
    function filter() {
      var words = terms(q.value), n = 0;
      rows.forEach(function (r) {
        var ok = (!project || r.dataset.p === project) && (ar.checked || !r.dataset.a);
        if (ok && words.length) ok = words.every(function (w) { return r.dataset.t.indexOf(w) >= 0; });
        r.hidden = !ok;
        if (ok) n++;
      });
      $$('#list .bucket').forEach(function (b) { b.hidden = !$('.row:not([hidden])', b); });
      cnt.textContent = n;
    }
    function allowed(page) {
      var row = rows.filter(function (r) { return r.dataset.page === page; })[0];
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
      if (!v) { hits.textContent = ''; filter(); return; }
      fetch('/api/search?q=' + encodeURIComponent(v) + '&tools=' + (tl.checked ? 1 : 0))
        .then(function (r) { return r.json(); })
        .then(function (j) { if (mine === seq) show(j); })
        .catch(function () { if (mine === seq) hits.textContent = '搜索失败：本地服务没有响应，请确认 Sessiontool 的窗口还开着。'; });
    }
    chips.forEach(function (c) {
      c.onclick = function () {
        chips.forEach(function (x) { x.classList.toggle('on', x === c); });
        project = c.dataset.p;
        run();
      };
    });
    q.oninput = debounce(run, 200);
    ar.onchange = tl.onchange = run;
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && e.target === q) { q.value = ''; run(); }
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === '/') { e.preventDefault(); q.focus(); q.select(); }
    });
    if (q.value) run(); else filter();
  }
})();
