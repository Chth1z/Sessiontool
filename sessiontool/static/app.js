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
      localStorage.setItem(k, v);
    } catch (e) { return null; }
  }

  /* ---------- 会话页 ---------- */

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
      j.images.forEach(function (src) {
        var a = el('a'), im = el('img', 'pic');
        a.href = src; a.target = '_blank';
        im.loading = 'lazy'; im.alt = '截图'; im.src = src;
        a.appendChild(im);
        box.appendChild(a);
      });
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

  function reveal(node) {
    for (var p = node; p; p = p.parentNode) if (p.tagName === 'DETAILS') p.open = true;
  }

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
    m.scrollIntoView({ block: 'center' });
    bar.firstChild.textContent = (cur + 1) + ' / ' + marks.length;
  }
  function highlight(q, near) {
    clearMarks();
    activeQ = q;
    if (!q) return;
    var lq = q.toLowerCase();
    $$('main .msg .body, main details.fold > .body, main details.tool[open] > .tc').forEach(function (root) {
      var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes = [], n;
      while ((n = walker.nextNode())) if (n.nodeValue.toLowerCase().indexOf(lq) >= 0) nodes.push(n);
      nodes.forEach(function (node) {
        var i;
        while ((i = node.nodeValue.toLowerCase().indexOf(lq)) >= 0) {
          var hit = node.splitText(i);
          node = hit.splitText(q.length);
          var mk = el('mark', null, hit.nodeValue);
          hit.parentNode.replaceChild(mk, hit);
          marks.push(mk);
        }
      });
    });
    bar = el('div', 'find');
    bar.appendChild(el('span', null, marks.length ? '' : '对话文字里没有找到（工具调用展开后才会被搜索）'));
    if (marks.length) {
      var up = el('button', null, '↑'), down = el('button', null, '↓');
      up.onclick = function () { go(-1); };
      down.onclick = function () { go(1); };
      bar.appendChild(up); bar.appendChild(down);
    }
    document.body.appendChild(bar);
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
    t.scrollIntoView({ block: 'start' });
    $$('.flash').forEach(function (x) { x.classList.remove('flash'); });
    t.classList.add('flash');
    return t;
  }

  if (document.body.classList.contains('session')) {
    var only = $('#onlychat');
    only.checked = store('onlychat') === '1';
    document.body.classList.toggle('chat', only.checked);
    only.onchange = function () {
      store('onlychat', only.checked ? '1' : '0');
      document.body.classList.toggle('chat', only.checked);
    };
    $('[data-act="tools"]').onclick = function () {
      var all = $$('details.tools'), open = !all.some(function (x) { return x.open; });
      all.forEach(function (x) { x.open = open; });
    };
    var fq = $('#fq'), target = jump();
    var q0 = new URLSearchParams(location.search).get('q') || '';
    if (q0) { fq.value = q0; highlight(q0, target); }
    fq.oninput = debounce(function () { highlight(fq.value.trim(), null); }, 250);
    fq.onkeydown = function (e) { if (e.key === 'Enter') go(e.shiftKey ? -1 : 1); };
    window.addEventListener('hashchange', jump);
  }

  /* ---------- 索引页 ---------- */

  if (document.body.classList.contains('index')) {
    var q = $('#q'), pj = $('#pj'), ar = $('#ar'), tl = $('#tl'), hits = $('#hits'), cnt = $('#cnt');
    var rows = $$('tbody tr'), seq = 0;
    var WHO = { user: '你', asst: 'Claude', tool: '工具' };

    function filter(pages) {
      var v = q.value.trim().toLowerCase(), p = pj.value, n = 0;
      rows.forEach(function (r) {
        var ok = (!p || r.dataset.p === p) && (ar.checked || !r.dataset.a);
        if (ok && v) ok = r.dataset.t.indexOf(v) >= 0 || (pages && pages[r.dataset.page]);
        r.hidden = !ok;
        if (ok) n++;
      });
      cnt.textContent = n;
    }
    function show(j) {
      hits.textContent = '';
      var pages = {};
      j.sessions.forEach(function (s) {
        pages[s.page] = 1;
        var row = rows.filter(function (r) { return r.dataset.page === s.page; })[0];
        if (row && ((pj.value && row.dataset.p !== pj.value) || (!ar.checked && row.dataset.a))) return;
        var box = el('div', 'hs'), base = '/s/' + s.page + '?q=' + encodeURIComponent(j.q);
        var a = el('a', null, s.title);
        a.href = base;
        box.appendChild(a);
        box.appendChild(el('small', null, '　' + s.n + ' 处'));
        var ul = el('ul');
        s.hits.forEach(function (h) {
          var li = el('li'), link = el('a');
          link.href = base + '#' + h.anchor;
          link.appendChild(el('small', null, h.time + ' · ' + WHO[h.who] + '　'));
          link.appendChild(document.createTextNode('…' + h.pre));
          link.appendChild(el('mark', null, h.hit));
          link.appendChild(document.createTextNode(h.post + '…'));
          li.appendChild(link);
          ul.appendChild(li);
        });
        if (s.n > s.hits.length) ul.appendChild(el('li', null, '')).appendChild(el('small', null, '　还有 ' + (s.n - s.hits.length) + ' 处，点标题进入会话查看'));
        box.appendChild(ul);
        hits.appendChild(box);
      });
      if (!j.sessions.length) hits.appendChild(el('div', 'meta', '对话内容里没有找到“' + j.q + '”。'));
      filter(pages);
    }
    function run() {
      var v = q.value.trim(), mine = ++seq;
      if (!v) { hits.textContent = ''; filter(null); return; }
      fetch('/api/search?q=' + encodeURIComponent(v) + '&tools=' + (tl.checked ? 1 : 0))
        .then(function (r) { return r.json(); })
        .then(function (j) { if (mine === seq) show(j); })
        .catch(function () { if (mine === seq) hits.textContent = '搜索失败：本地服务没有响应。'; });
    }
    q.oninput = debounce(run, 200);
    pj.onchange = ar.onchange = tl.onchange = run;
    filter(null);
  }
})();
