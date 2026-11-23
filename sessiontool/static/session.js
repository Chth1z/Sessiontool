// 会话页交互：视图切换、会话内搜索、目录正倒序与跟随、精确阅读位置记忆、增量块更新
(function () {
  'use strict';
  var ST = window.ST;
  var body = ST.body, $ = ST.$, $$ = ST.$$, el = ST.el, ibtn = ST.ibtn;
  var flow = $('#flow'), page = body.dataset.page || '';
  var posKey = 'pos:' + (page || location.pathname);

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
  function go(stepDir, quiet) {
    if (!marks.length) return;
    if (cur >= 0 && marks[cur]) marks[cur].classList.remove('cur');
    cur = (cur + stepDir + marks.length) % marks.length;
    var m = marks[cur];
    m.classList.add('cur');
    if (!quiet) {
      ST.reveal(m);
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
  function highlight(q, near, quiet) {
    var keep = quiet ? cur : -1;
    clearMarks();
    activeQ = q;
    var words = ST.terms(q);
    if (!words.length) return;
    $$('main .msg .body, main .step > .body, main .sent, main details.fold > .body, main details.tool[open] > .tc').forEach(function (scope) {
      if (view !== 'full' && scope.closest(view === 'result'
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
  ST.onToolLoaded = function (d) { if (activeQ) highlight(activeQ, d); };

  /* ================= 视图与滚动 ================= */

  var VIEWS = ['full', 'chat', 'result'];
  var views = $$('#view button');
  function setView(v, keep) {
    if (VIEWS.indexOf(v) < 0) v = 'full';
    view = v;
    views.forEach(function (b) { b.classList.toggle('on', b.dataset.v === v); });
    body.classList.toggle('chat', v === 'chat');
    body.classList.toggle('result', v === 'result');
    if (keep) {
      ST.store('view', v);
      if (activeQ) highlight(activeQ, null, true);
    }
  }
  function switchView(v) {
    if (VIEWS.indexOf(v) < 0) v = 'full';
    if (v === view) return;
    keepPlace(function () { setView(v, true); });
  }
  views.forEach(function (b) { b.onclick = function () { switchView(b.dataset.v); }; });

  var progEl = $('.progress'), floats = el('div', 'floats');
  var totop = ibtn('up', '回到开头'), toend = ibtn('down', '滑到底部');
  totop.dataset.act = 'top';
  toend.dataset.act = 'end';
  floats.appendChild(totop);
  floats.appendChild(toend);
  body.appendChild(floats);

  var scrollAnim = 0;
  function stopSmoothScroll() { if (scrollAnim) { cancelAnimationFrame(scrollAnim); scrollAnim = 0; } }
  function barClearance() { var b = $('.bar'); return (b ? b.offsetHeight : 56) + 20; }
  function smoothScrollTo(destY, animate) {
    stopSmoothScroll();
    var maxY = Math.max(0, ST.scrollHOf() - ST.viewHOf());
    var targetY = Math.max(0, Math.min(maxY, destY));
    var startY = ST.scrollYOf(), diff = targetY - startY, dist = Math.abs(diff);
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!animate || reduced || dist < 4) {
      ST.scrollToY(targetY);
      syncProgress();
      return;
    }
    var dur = Math.min(420, Math.max(220, 180 + Math.sqrt(dist) * 2.2)), t0 = performance.now();
    function frame(now) {
      var p = Math.min(1, (now - t0) / dur);
      ST.scrollToY(startY + diff * (1 - Math.pow(1 - p, 3)));
      syncProgress();
      if (p < 1) scrollAnim = requestAnimationFrame(frame);
      else scrollAnim = 0;
    }
    scrollAnim = requestAnimationFrame(frame);
  }
  function scrollNodeIntoView(node, animate) {
    var s = ST.mainScroller(), baseTop = s === window ? 0 : s.getBoundingClientRect().top;
    smoothScrollTo(ST.scrollYOf() + (node.getBoundingClientRect().top - baseTop) - barClearance(), animate);
  }
  if (ST.mainEl) {
    ST.mainEl.addEventListener('wheel', stopSmoothScroll, { passive: true });
    ST.mainEl.addEventListener('touchstart', stopSmoothScroll, { passive: true });
    ST.mainEl.addEventListener('pointerdown', function (e) { if (e.target === ST.mainEl) stopSmoothScroll(); });
  }
  window.addEventListener('wheel', stopSmoothScroll, { passive: true });
  window.addEventListener('touchstart', stopSmoothScroll, { passive: true });

  var progRaf = 0;
  function syncProgress() {
    var y = ST.scrollYOf(), vh = ST.viewHOf(), sh = ST.scrollHOf(), max = Math.max(0, sh - vh);
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
  function keepPlace(fn) {
    stopSmoothScroll();
    var clear = barClearance(), at = firstBlockAt(clear);
    var blk = at >= 0 ? flow.children[at] : null, ref = blk, childIdx = -1, top = 0;
    if (blk) {
      if (blk.classList.contains('turn')) {
        for (var i = 0; i < blk.children.length; i++) {
          var cr = blk.children[i].getBoundingClientRect();
          if (cr.height > 0 && cr.bottom > clear) { ref = blk.children[i]; childIdx = i; top = cr.top; break; }
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
        ST.scrollByY(nr.top - top);
      } else if (blk) {
        var fb = null;
        for (var j = Math.max(0, childIdx); j < blk.children.length; j++) {
          if (blk.children[j].getBoundingClientRect().height > 0) { fb = blk.children[j]; break; }
        }
        if (!fb) {
          for (var k = childIdx - 1; k >= 0; k--) {
            if (blk.children[k].getBoundingClientRect().height > 0) { fb = blk.children[k]; break; }
          }
        }
        ST.scrollByY((fb || blk).getBoundingClientRect().top - clear);
      }
    }
    syncProgress();
  }

  /* ================= 左侧提问目录与阅读位置记忆 ================= */

  var navEl = $('.layout > nav'), tocEl = $('nav .toc'), sortBtn = $('.toc-sort');
  var rawToc = tocEl ? tocEl.innerHTML : '', tocSort = ST.store('toc-sort') === 'desc' ? 'desc' : 'asc';

  function buildDescToc(html) {
    var nodes = ST.parse(html), groups = [], curDay = null, curGroup = null;
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

  ST.actions.info = function () { ST.openInfo(page); };
  ST.actions.top = function () { smoothScrollTo(0, true); };
  ST.actions.end = function () { smoothScrollTo(ST.scrollHOf(), true); };
  ST.actions.tocsort = function () {
    tocSort = tocSort === 'desc' ? 'asc' : 'desc';
    ST.store('toc-sort', tocSort);
    renderToc();
    collect();
    spy(false, false);
    if (tocEl) tocEl.scrollTop = 0;
  };
  ST.actions.tools = function (b) {
    var all = $$('details.tools'), open = !all.some(function (x) { return x.open; });
    if (open && view !== 'full') setView('full', true);
    ST.bulk(function () {
      if (open) $$('details.steps').forEach(function (d) { d.open = true; });
      all.forEach(function (x) { x.open = open; });
    });
    b.firstChild.textContent = open ? '收起全部工具调用' : '展开全部工具调用';
    b.closest('details').open = false;
    syncProgress();
  };
  ST.actions.fold = function (b) {
    var d = b.closest('details.steps');
    ST.bulk(function () { d.open = false; });
    d.scrollIntoView({ block: 'center' });
    syncProgress();
  };

  var prompts = [], links = {}, active = null;
  function collect() {
    prompts = $$('#flow > .turn > .msg.user[id]');
    links = {};
    $$('nav .toc a').forEach(function (a) { links[a.getAttribute('href').slice(1)] = a; });
    active = null;
  }
  function current() {
    var best = null, line = ST.viewHOf() * 0.4, lo = 0, hi = prompts.length - 1;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (prompts[mid].getBoundingClientRect().top <= line) { best = prompts[mid]; lo = mid + 1; }
      else hi = mid - 1;
    }
    return best;
  }
  function atEnd() { return ST.viewHOf() + ST.scrollYOf() >= ST.scrollHOf() - 200; }

  function spy(moved, syncToc) {
    syncProgress();
    if (pill && atEnd()) pill.classList.remove('on');
    var best = current(), a = best && links[best.id];
    if (a === active) return;
    if (active) active.classList.remove('on');
    active = a;
    if (a) {
      a.classList.add('on');
      if ((moved || syncToc) && (!navEl || !navEl.matches(':hover'))) scrollTocTo(a);
    }
  }
  function savePos() {
    var sy = Math.round(ST.scrollYOf());
    if (sy < 80) { ST.store(posKey, null); return; }
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
    ST.store(posKey, JSON.stringify(anchor ? { id: anchor.id, y: Math.round(anchorTop), sy: sy } : { id: '', y: 0, sy: sy }));
  }
  function restorePos() {
    var raw = ST.store(posKey);
    if (!raw) return false;
    var rec = null;
    if (raw.charAt(0) === '{') {
      try { rec = JSON.parse(raw); } catch (e) { return false; }
    } else {
      rec = { id: raw, y: 76, sy: 0 };
    }
    if (!rec) return false;
    var anchor = rec.id ? document.getElementById(rec.id) : null;
    if (anchor) {
      if (!anchor.offsetHeight) ST.bulk(function () { ST.reveal(anchor); });
      if (!anchor.offsetHeight) {
        var host = anchor.closest('.turn');
        anchor = (host && ($('.msg.asst', host) || $('.msg.user', host))) || null;
        rec.y = barClearance();
      }
      if (anchor && anchor.offsetHeight) {
        ST.scrollByY(anchor.getBoundingClientRect().top - rec.y);
        requestAnimationFrame(function () {
          if (!userMoved && anchor.isConnected && anchor.offsetHeight) {
            ST.scrollByY(anchor.getBoundingClientRect().top - rec.y);
            spy(false, true);
          }
        });
        return true;
      }
    }
    if (rec.sy > 0) { ST.scrollToY(rec.sy); return true; }
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
    var y = ST.viewHOf() * 0.4, at = firstBlockAt(y);
    if (at < 0) return null;
    var blk = flow.children[at];
    return blk.classList.contains('turn') && blk.getBoundingClientRect().top <= y ? blk : null;
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
    ST.bulk(function () { ST.reveal(t); });
    if (!t.offsetHeight && view !== 'full') {
      if (view === 'result' && t.closest('.step')) setView('chat', false);
      else setView('full', false);
    }
    scrollNodeIntoView(t, !!animate);
    $$('.flash').forEach(function (x) { x.classList.remove('flash'); });
    void t.offsetWidth;
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

  /* ================= 增量更新 ================= */

  var pill = null;
  function showPill() {
    if (!pill) {
      pill = el('button', 'newpill');
      pill.type = 'button';
      pill.appendChild(el('span', null, '有新内容'));
      pill.appendChild(ST.icon('down'));
      pill.onclick = function () { pill.classList.remove('on'); ST.actions.end(); };
      body.appendChild(pill);
    }
    requestAnimationFrame(function () { pill.classList.add('on'); });
  }
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
    var news = ST.parse(j.blocks.join('\n')), end = atEnd(), turnsBefore = $$('#flow > .turn').length;
    keepPlace(function () {
      var head = $('main .head'), filesOpen = !!$('.files[open]', head), nhead = ST.parse(j.head)[0];
      head.replaceWith(nhead);
      if (filesOpen && $('.files', nhead)) $('.files', nhead).open = true;
      news.forEach(function (n, k) {
        var o = olds[j.start + k];
        if (o) keepOpen(o, n); else n.classList.add('new');
      });
      ST.bulk(function () {
        olds.slice(j.start).forEach(function (o) { o.remove(); });
        news.forEach(function (n) { flow.appendChild(n); ST.awaitImages(n); });
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
    if (end) ST.scrollToY(ST.scrollHOf());
    else if (!manual && news.length) showPill();
    syncProgress();
    var more = $$('#flow > .turn').length - turnsBefore;
    return { changed: true, text: more > 0 ? '已更新 · 新增 ' + more + ' 轮对话' : '已更新到最新内容',
      action: end ? null : { action: '跳到最新', run: ST.actions.end } };
  }
  ST.setPull(function (fresh) {
    return fetch('/api/blocks' + (fresh ? '?fresh=1' : ''), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page: page, keys: [].map.call(flow.children, function (n) { return n.dataset.k || ''; }) })
    }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (j) { return apply(j, fresh); });
  });

  ST.keys = [['J  K', '下一条 / 上一条你的提问'], ['1  2  3', '完整 / 对话 / 结果视图'],
    ['E', '折起或展开当前这一轮的过程'], ['I', '会话详情'], ['Enter  Shift+Enter', '搜索时跳到下一处 / 上一处'],
    ['←  →', '放大图片时切换上一张 / 下一张']];

  var ready = false, userMoved = false;
  var savePosLater = ST.debounce(savePos, 140), spyLater = ST.debounce(function () { spy(true); }, 50);
  setView(ST.store('view') || 'full', false);
  renderToc();
  collect();

  var fq = $('#fq'), target = jump(false), q0 = '';
  if (fq) {
    q0 = new URLSearchParams(location.search).get('q') || '';
    if (q0) { fq.value = q0; highlight(q0, target); }
    fq.oninput = ST.debounce(function () { highlight(fq.value.trim(), null); }, 250);
    fq.onkeydown = function (e) {
      if (e.key === 'Enter') go(e.shiftKey ? -1 : 1);
      if (e.key === 'Escape') { fq.value = ''; highlight('', null); fq.blur(); }
    };
  }
  window.addEventListener('hashchange', function () { jump(true); });

  var restored = !target && !q0 && restorePos();
  spy(false, restored || !!target);
  requestAnimationFrame(function () { ready = true; syncProgress(); });

  ST.onMainScroll(function () {
    syncProgressSoon();
    if (!ready) return;
    userMoved = true;
    spyLater();
    savePosLater();
  });
  window.addEventListener('resize', ST.debounce(syncProgress, 120));
  window.addEventListener('pagehide', function () { if (userMoved) savePos(); });
  document.addEventListener('visibilitychange', function () { if (document.hidden && userMoved) savePos(); });

  document.addEventListener('keydown', function (e) {
    if (ST.hasModal() || ST.typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
    var k = e.key;
    if (k === 'j') step(1);
    else if (k === 'k') step(-1);
    else if (k === '/' && fq) { e.preventDefault(); fq.focus(); fq.select(); }
    else if (k === 'i' && $('#info')) ST.openInfo(page);
    else if (k >= '1' && k <= '3') switchView(VIEWS[k - 1]);
    else if (k === 'e' && view !== 'result') {
      var t = turnInView(), d = t && $('details.steps', t);
      if (d) keepPlace(function () { ST.bulk(function () { d.open = !d.open; }); });
    }
  });
})();
