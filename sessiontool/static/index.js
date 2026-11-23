// 索引页交互：项目/账号/来源筛选、全文搜索、键盘导航、视图过渡与实时热替换
(function () {
  'use strict';
  var ST = window.ST;
  var body = ST.body, $ = ST.$, $$ = ST.$$, el = ST.el;
  var q = $('#q'), ar = $('#ar'), tl = $('#tl'), hits = $('#hits'), cnt = $('#cnt'), list = $('#list');
  var project = '', account = '', seq = 0;
  var WHO = { user: ['你', 'who-you'], asst: ['Claude', 'who-claude'], tool: ['工具', ''] };

  function rows() { return $$('#list .row'); }
  function remember() { ST.tab('idx', { p: project, a: account, ar: ar.checked, tl: tl.checked, q: q.value }); }

  // 项目、账号两组标签各自计数：只数当前来源的会话，没有的就不显示
  function count(t) {
    var src = ST.source();
    if (src !== 'all') return ST.SRC[src] ? (+t.dataset[ST.SRC[src].attr] || 0) : 0;
    var sum = 0;
    Object.keys(ST.SRC).forEach(function (k) { sum += +t.dataset[ST.SRC[k].attr] || 0; });
    return sum;
  }
  function paintTabs() {
    $$('#pj .tab, #ac .tab').forEach(function (t) {
      var n = count(t), small = $('small', t), all = t.dataset.p === '' || t.dataset.acct === '';
      if (small) small.textContent = n;
      t.hidden = !all && !n;
    });
    var acctWrap = $('.side-acct');
    if (acctWrap) acctWrap.hidden = !$$('#ac .tab').some(function (t) { return t.dataset.acct !== '' && !t.hidden; });
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
    ST.syncAcctSummary($('#ac'), account, $('#ac-name'), $('#ac-dot'), $('#ac-cnt'));
  }

  function shown(r) {
    var src = ST.source();
    return (src === 'all' || r.dataset.src === src) && (!project || r.dataset.p === project)
      && (!account || r.dataset.acct === account) && (ar.checked || !r.dataset.a);
  }
  // 有搜索词时列表只留标题命中的会话：内容命中的已经在上面的结果里
  function filter() {
    var words = ST.terms(q.value), n = 0;
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
      var ul = el('ul'), p = ST.SRC[s.src];
      s.hits.forEach(function (h) {
        var li = el('li'), link = el('a'), who = WHO[h.who];
        var wname = h.who === 'asst' && p ? p.name : who[0];
        var wcls = h.who === 'asst' && p ? p.who : who[1];
        link.href = base + '#' + h.anchor;
        link.appendChild(el('small', null, h.time + '　'));
        link.appendChild(el('small', wcls, wname + '　'));
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
    fetch('/api/search?q=' + encodeURIComponent(v) + '&tools=' + (tl.checked ? 1 : 0) + '&src=' + ST.srcParam())
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

  ST.actions.info = function (b) { ST.openInfo(b.closest('.row').dataset.page); };

  function swap(doc) {
    var nb = doc.body;
    $('#synced').textContent = $('#synced', doc).textContent;
    if (nb.dataset.sig === body.dataset.sig) return { changed: false };
    var f = focusedRow(), fp = f && f.dataset.page;
    var sideScroll = $('#side-scroll'), sst = sideScroll ? sideScroll.scrollTop : 0, mst = ST.scrollYOf();
    list.classList.add('still');            // 换进来的行不再播放入场动画
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
    var curSeg = ST.srcSeg(), nsrc = $('#src', doc);
    if (curSeg && nsrc) {
      if (curSeg.innerHTML !== nsrc.innerHTML) {
        curSeg.innerHTML = nsrc.innerHTML;
        ST.pickSource(ST.source());
      }
    } else if (!curSeg && nsrc && $('.side-top')) {
      $('.side-top').insertAdjacentElement('afterend', nsrc);
      ST.bindSrcSeg($('#src'));
      ST.pickSource(ST.store('src') || 'claude');
    }
    $('#totals').textContent = $('#totals', doc).textContent;
    body.dataset.sig = nb.dataset.sig;
    paintTabs();
    run();
    if (sideScroll) sideScroll.scrollTop = sst;
    ST.scrollToY(mst);
    var back = fp && $('#list .row[data-page="' + fp + '"] .cover');
    if (back) back.focus({ preventScroll: true });
    return { changed: true, text: '会话列表已更新' };
  }
  ST.setPull(function (fresh) {
    return fetch('/' + (fresh ? '?fresh=1' : '')).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }).then(function (text) { return swap(new DOMParser().parseFromString(text, 'text/html')); });
  });

  document.addEventListener('click', function (e) {
    var t = e.target.closest('#pj .tab');
    if (t) { pick(t.dataset.p); ST.scrollToY(0); run(); return; }
    t = e.target.closest('#ac .tab');
    if (t) {
      pickAcct(t.dataset.acct);
      if ($('#ac')) $('#ac').open = false;
      ST.scrollToY(0);
      run();
      return;
    }
    // 点进会话时给标题起个过渡名字，新页面的大标题会从这里“长”出来
    var cover = e.target.closest('.cover');
    if (cover) {
      $$('#list .title').forEach(function (x) { x.style.viewTransitionName = ''; });
      $('.title', cover.parentNode).style.viewTransitionName = 'title';
    }
  });
  q.oninput = ST.debounce(run, 200);
  ar.onchange = tl.onchange = run;
  ST.onSource = function () { paintTabs(); run(); };
  ST.keys = function () {
    return [['J  K  ↓  ↑', '在会话和搜索结果之间移动'], ['Enter', '打开选中的会话'], ['I', '选中会话的详情'],
      ['C', '复制选中会话的 ID'], ['S', ST.srcHint()]];
  };

  document.addEventListener('keydown', function (e) {
    if (ST.hasModal() || e.ctrlKey || e.metaKey || e.altKey) return;
    var k = e.key;
    if (e.target === q) {
      if (k === 'Escape') { q.value = ''; run(); }
      else if (k === 'ArrowDown') { e.preventDefault(); move(1); }
      return;
    }
    if (ST.typing(e)) return;
    if (k === '/') { e.preventDefault(); q.focus(); q.select(); }
    else if (k === 'j' || k === 'ArrowDown') { e.preventDefault(); move(1); }
    else if (k === 'k' || k === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (k === 'i' && focusedRow()) ST.openInfo(focusedRow().dataset.page);
    else if (k === 'c' && focusedRow()) {
      var b = $('[data-copy]', focusedRow());
      ST.copyFrom(b, b.dataset.copy, b.dataset.copied);
    }
  });

  // 回到列表时恢复刚才的筛选和搜索；从会话页回来的，连滚动位置和来处的标题一起恢复
  var saved = ST.tab('idx') || {};
  if (saved.ar === false) ar.checked = false;
  if (saved.tl) tl.checked = true;
  if (saved.q && !q.value) q.value = saved.q;
  project = saved.p || '';
  account = saved.a || '';
  ST.pickSource(ST.store('src') || 'claude');
  paintTabs();
  var from = /\/s\/([0-9a-f]+)/.exec(document.referrer || '');
  if (from) {
    var back = $('#list .row[data-page="' + from[1] + '"] .title');
    if (back) back.style.viewTransitionName = 'title';
    list.classList.add('still');
  }
  if (q.value) run(); else filter();
  if (from) ST.scrollToY(ST.tab('idx-y') || 0);
  else q.focus({ preventScroll: true });    // 新打开时光标直接在搜索框里，可以马上输入
  window.addEventListener('pagehide', function () { ST.tab('idx-y', ST.scrollYOf()); });
})();
