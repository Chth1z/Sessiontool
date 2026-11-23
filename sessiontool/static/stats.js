// 统计页交互与图表渲染：时间/账号/来源筛选、摘要与趣味换算、SVG 堆叠柱状图/热力图/时段图/用量表
(function () {
  'use strict';
  var ST = window.ST;
  var body = ST.body, $ = ST.$, $$ = ST.$$, el = ST.el, svg = ST.svg, ibtn = ST.ibtn;
  var st = $('#st'), rangeSeg = $('#range'), spanEl = $('#span'), digestEl = $('#digest');
  var acctMenu = $('#acct'), acctName = $('#acct-name'), acctDot = $('#acct-dot');
  var range = +(ST.store('st-range') || 30), acct = ST.store('st-acct') || '', data = null, ask = 0;
  var metric = ST.store('st-metric') || 'cost', quipStep = 0;
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
    ST.store('st-range', range);
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
      ST.store('st-acct', acct);
      ST.syncAcctSummary(acctMenu, acct, acctName, acctDot);
      load();
    });
  }

  // quiet：实时更新时悄悄换上新数字；换筛选条件时旧图半透明地留着，等新数据到了再换，不闪白
  function load(fresh, quiet) {
    var mine = ++ask;
    if (!quiet) st.classList.add('loading');
    return fetch('/api/stats?days=' + range + '&account=' + encodeURIComponent(acct) + '&src=' + ST.srcParam() + (fresh ? '&fresh=1' : ''))
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
  ST.setPull(function (manual) { return load(manual, !manual); });
  ST.onSource = function () {
    var src = ST.source();
    if (acct && data && data.accounts && !data.accounts.some(function (a) {
      return (src === 'all' || a.src === src) && a.key === acct;
    })) {
      acct = '';
      ST.store('st-acct', '');
    }
    load();
  };
  ST.keys = function () { return [['S', ST.srcHint()]]; };

  // ----- 提示框：数值在前、名字在后；内容一律用 textContent -----
  function showTip(e, rows, head) {
    tip.textContent = '';
    if (head) tip.appendChild(el('div', 'th', head));
    rows.forEach(function (r) {
      var line = el('div', 'tr');
      if (r[2]) line.appendChild(el('i', 'key ' + r[2]));
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
  function fmtMetric(v, m) { return m === 'cost' ? ST.money(v) : m === 'n' ? ST.compact(v) + ' 次' : ST.compact(v); }
  function shortDate(d) { var p = d.split('-'); return (+p[1]) + '/' + (+p[2]); }
  function dayName(d) { var t = new Date(d + 'T00:00:00'); return d + ' 周' + ST.WEEK[(t.getDay() + 6) % 7]; }
  function slotClass(i) { return i < data.slots.length ? 's' + (i + 1) : 's0'; }
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
          var r = j === segs.length - 1 ? Math.min(4, bw / 2, h - gap) : 0, hh = h - gap;
          g.appendChild(svg('path', { 'class': 'seg ' + slotClass(m[0]),
            d: 'M' + x + ',' + (y + hh) + 'V' + (y + r) + (r ? 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y : '') + 'H' + (x + bw - r)
              + (r ? 'Q' + (x + bw) + ',' + y + ' ' + (x + bw) + ',' + (y + r) : '') + 'V' + (y + hh) + 'Z' }));
        }
        base = y;
      });
      g.appendChild(svg('rect', { x: L + i * band, y: T, width: band, height: ph, 'class': 'hit' }));
      hover(g, function (e) {
        var rows = segs.slice().reverse().map(function (m) { return [fmtMetric(m[idx], metric), slotName(m[0]), slotClass(m[0])]; });
        rows.push([metric === 'cost' ? ST.cost(d) : fmtMetric(totals[i], metric), '合计']);
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
    Object.keys(used).map(Number).sort(function (a, b) { return a - b; }).forEach(function (i) {
      legend.appendChild(ST.swatch(slotClass(i), slotName(i)));
    });
    host.appendChild(legend);
  }
  function dailyTable(host) {
    var used = {};
    data.days.forEach(function (d) { d.models.forEach(function (m) { if (m[1] || m[2]) used[m[0]] = 1; }); });
    var slots = Object.keys(used).map(Number).sort(function (a, b) { return a - b; });
    var rows = data.days.slice().reverse().filter(function (d) { return d.n || d.prompts; }).map(function (d) {
      var by = {};
      d.models.forEach(function (m) { by[m[0]] = m; });
      return [dayName(d.d), d.prompts, d.n, ST.compact(d.tokens), ST.pct(d.rate, 0), ST.cost(d)].concat(slots.map(function (i) {
        return by[i] ? ST.money(by[i][1]) : '';
      }));
    });
    host.appendChild(ST.grid(['日期', '提问', '回复', 'Tokens', '命中率', '费用'].concat(slots.map(slotName)), rows));
  }

  // ----- 日历与时段热力图 -----
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
    var start = new Date(Math.min(from, new Date(end.getFullYear(), end.getMonth(), end.getDate() - 181)));
    start.setDate(start.getDate() - (start.getDay() + 6) % 7);
    var weeks = Math.ceil((Math.round((end - start) / 864e5) + 1) / 7);
    var W = Math.max(300, host.clientWidth), L = 26, T = 18;
    var stepc = Math.max(9, Math.min(17, Math.floor((W - L) / weeks))), cell = stepc - 3;
    var level = levels(data.days.map(function (d) { return d.n; }));
    var s = svg('svg', { 'class': 'chart heat', width: L + weeks * stepc, height: T + 7 * stepc, role: 'img',
      'aria-label': '每天的回复次数' });
    [0, 2, 4].forEach(function (w) {
      s.appendChild(svg('text', { x: 0, y: T + w * stepc + cell - 1, 'class': 'tick' }, '周' + ST.WEEK[w]));
    });
    var lastMonth = -1, lastLabel = -9;
    for (var w = 0; w < weeks; w++) {
      for (var dw = 0; dw < 7; dw++) {
        var t = new Date(start.getFullYear(), start.getMonth(), start.getDate() + w * 7 + dw);
        if (t > end) continue;
        var iso = t.getFullYear() + '-' + ST.pad(t.getMonth() + 1) + '-' + ST.pad(t.getDate()), d = by[iso];
        if (dw === 0 && t.getMonth() !== lastMonth) {
          lastMonth = t.getMonth();
          if (w < weeks - 2 && w - lastLabel >= 3) {
            s.appendChild(svg('text', { x: L + w * stepc, y: 11, 'class': 'tick' }, (t.getMonth() + 1) + '月'));
            lastLabel = w;
          }
        }
        var rect = svg('rect', { x: L + w * stepc, y: T + dw * stepc, width: cell, height: cell, rx: 2.5,
          'class': 'cell ' + (d ? 'h' + level(d.n) : 'out') });
        if (d) {
          (function (d) {
            hover(rect, function (e) {
              showTip(e, [[d.n + ' 次', '回复'], [d.prompts + ' 次', '提问'], [ST.cost(d), '费用'], [ST.compact(d.tokens), 'tokens']],
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
  function drawHours(host) {
    var hrs = data.hours, flat = [].concat.apply([], hrs), level = levels(flat);
    var W = Math.max(300, host.clientWidth), L = 30, T = 4, B = 18;
    var stepc = Math.max(10, Math.min(30, Math.floor((W - L) / 24))), cell = stepc - 3;
    var s = svg('svg', { 'class': 'chart', width: L + 24 * stepc, height: T + 7 * stepc + B, role: 'img', 'aria-label': '一周里各个时段的回复次数' });
    for (var d = 0; d < 7; d++) {
      s.appendChild(svg('text', { x: 0, y: T + d * stepc + cell - 1, 'class': 'tick' }, '周' + ST.WEEK[d]));
      for (var h = 0; h < 24; h++) {
        var rect = svg('rect', { x: L + h * stepc, y: T + d * stepc, width: cell, height: cell, rx: 2.5, 'class': 'cell h' + level(hrs[d][h]) });
        (function (d, h) {
          hover(rect, function (e) {
            showTip(e, [[hrs[d][h] + ' 次', '回复']], '周' + ST.WEEK[d] + ' ' + ST.pad(h) + ':00–' + ST.pad((h + 1) % 24) + ':00');
          });
        })(d, h);
        s.appendChild(rect);
      }
    }
    for (h = 0; h < 24; h += 3) s.appendChild(svg('text', { x: L + h * stepc, y: T + 7 * stepc + 12, 'class': 'tick' }, ST.pad(h)));
    host.appendChild(s);
  }

  // ----- 额度与账号筛选 -----
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
  function fillAccounts(list) {
    if (!acctMenu) return false;
    var src = ST.source();
    var visible = (list || []).filter(function (a) { return src === 'all' || a.src === src; });
    var pickWrap = acctMenu.closest('.pick');
    if (pickWrap) pickWrap.hidden = !visible.length;
    if (acct && !visible.some(function (a) { return a.key === acct; })) {
      acct = '';
      ST.store('st-acct', '');
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
      dot.style.background = 'hsl(' + ST.hue(a.email || a.key) + ' 55% 55%)';
      b.appendChild(dot);
      b.appendChild(el('span', null, a.name));
      if (a.email && a.email !== a.name) b.appendChild(el('small', null, a.email));
      box.appendChild(b);
    });
    ST.syncAcctSummary(acctMenu, acct, acctName, acctDot);
    return false;
  }

  // ----- 左侧摘要与尺度换算 -----
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
      if (tok >= 450000) {
        var r0 = fmtRatio(tok / 450000);
        scales.push(['Token 用量是整部', ['《万叶集》'], '的 ', [r0 + ' 倍'], '——相当于把 4,516 首和歌来回吞吐了 ', [r0 + ' 遍'], '。']);
      } else {
        scales.push(['Token 用量约为', ['《万叶集》'], '的 ', [ST.pct(tok / 450000, 0)], '，折合差不多 ', [Math.max(1, Math.round(tok / 450000 * 4516)).toLocaleString() + ' 首'], ' 和歌的篇幅。']);
      }
      if (tok >= 1100000) scales.push(['总吞吐量相当于百二十回本', ['《红楼梦》'], '的 ', [fmtRatio(tok / 1100000) + ' 倍'], '。']);
      else scales.push(['总吞吐量相当于', ['《红楼梦》'], '前 ', [Math.max(1, Math.round(tok / 1100000 * 120)) + ' 回'], ' 的体量。']);
      if (tok >= 1300000) scales.push(['流经模型的上下文是', ['《三体》三部曲'], '全集的 ', [fmtRatio(tok / 1300000) + ' 倍'], '。']);
      else scales.push(['流经模型的上下文约为', ['《三体》三部曲'], '的 ', [ST.pct(tok / 1300000, 0)], '。']);
      if (tok >= 750000) scales.push(['总 Token 量是托尔斯泰', ['《战争与和平》'], '的 ', [fmtRatio(tok / 750000) + ' 倍'], '。']);
      else scales.push(['总 Token 量约为一部', ['《战争与和平》'], '的 ', [ST.pct(tok / 750000, 0)], '。']);
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
      tangibles.push(['提示词缓存免去了 ', [ST.compact(t.cache_read) + ' tokens'], ' 的重复预读，相当于替模型少翻了 ', [fmtRatio(t.cache_read / 450000) + ' 部《万叶集》'], '。']);
    }
    if (t.thinking > 0 && out > 0) {
      tangibles.push(['模型在正式作答前悄悄推演了 ', [ST.compact(t.thinking) + ' tokens'], ' 的思考链，占全部输出的 ', [ST.pct(t.thinking / out, 0)], '。']);
    }

    if (d.tools > 0 && d.prompts > 0) {
      habits.push(['平均你每提 1 个问题，Agent 就在后台自动执行 ', [(d.tools / d.prompts).toFixed(1) + ' 次'], ' 工具调用（累计 ', [d.tools.toLocaleString() + ' 次'], '）。']);
    }
    if (d.hours && t.n >= 5) {
      var win = [0, 0, 0, 0];
      for (var wd = 0; wd < 7; wd++) for (var hr = 0; hr < 24; hr++) win[Math.floor(hr / 6)] += d.hours[wd][hr];
      var night = win[0] / t.n;
      if (night >= 0.22) {
        habits.push(['有 ', [ST.pct(night, 0)], ' 的回复诞生在凌晨 0–6 点——妥妥的深夜炼丹师作息。']);
      } else {
        var names = ['凌晨（0–6 点）', '上午（6–12 点）', '下午（12–18 点）', '夜间（18–24 点）'], bi = 0;
        for (var wi = 1; wi < 4; wi++) if (win[wi] > win[bi]) bi = wi;
        habits.push(['你最常在', [names[bi]], '与模型并肩推进，贡献了 ', [ST.pct(win[bi] / t.n, 0)], ' 的回复。']);
      }
    }
    if (d.best_streak >= 2) {
      habits.push(['最长曾连续 ', [d.best_streak + ' 天'], ' 每天都在和 Agent 切磋代码' + (d.streak >= 2 ? '，目前正连更 ' : '。'),
        d.streak >= 2 ? [d.streak + ' 天'] : '', d.streak >= 2 ? '。' : '']);
    }
    if (d.top && d.top.length && d.top[0].n >= 10) {
      var tt = d.top[0].title || '未命名会话';
      if (tt.length > 18) tt = tt.slice(0, 17) + '…';
      habits.push(['最重度的一场对话', ['「' + tt + '」'], '单场就往返了 ', [d.top[0].n.toLocaleString() + ' 次'], ' 回复（折合 ', [ST.cost(d.top[0])], '）。']);
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
    var perDay = d.active_days ? (t.cost ? ST.money(t.cost / d.active_days) + ' / 天' : Math.round(t.n / d.active_days) + ' 答 / 天') : '—';
    var dayText = d.active_days + ' 天' + (d.streak >= 2 ? ' · 连更 ' + d.streak + ' 天'
      : d.best_streak >= 2 ? ' · 最长 ' + d.best_streak + ' 天' : '');
    var items = [
      ['估算花费', ST.cost(t)],
      ['活跃日均', perDay],
      ['活跃天数', dayText],
      ['总吞吐量', ST.compact(t.tokens) + ' tokens'],
      ['模型净输出', ST.compact(t.output) + ' tokens']
    ];
    if (t.thinking > 0) items.push(['思考推演', ST.compact(t.thinking) + ' tokens']);
    if (t.rate != null) items.push(['缓存命中', ST.pct(t.rate) + ' · ' + ST.compact(t.cache_read)]);
    items.push(['对话规模', d.sessions + ' 场 · ' + d.prompts + ' 问 · ' + ST.compact(t.n) + ' 答']);
    if (d.tools > 0) items.push(['工具调用', d.tools.toLocaleString() + ' 次' + (d.prompts ? '（' + (d.tools / d.prompts).toFixed(1) + '/问）' : '')]);
    items.push(['主力模型', d.favorite ? d.favorite.name + ' · ' + ST.pct(d.favorite.share, 0) : '—']);
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
    st.style.minHeight = st.offsetHeight + 'px';
    paint();
    st.style.minHeight = '';
  }
  function paint() {
    var d = data, t = d.total, src = ST.source();
    hideTip();
    if (fillAccounts(d.accounts)) return;
    paintDigest(d);
    spanEl.textContent = d.range.from + ' → ' + d.range.to;
    st.textContent = '';
    if (!t.n && !d.prompts) { st.appendChild(el('p', 'empty', '这段时间里没有用量记录。')); return; }

    var top = el('section', 'st-hero'), big = el('div', 'big');
    big.appendChild(el('b', !t.cost && t.unpriced ? 'na' : null, ST.cost(t)));
    big.appendChild(el('span', null, '按 API 价格估算 · ' + (d.range.days ? '最近 ' + d.range.days + ' 天' : '全部时间')
      + (t.unpriced ? ' · ' + ST.unpricedNote(t) : '')));
    top.appendChild(big);
    var kpis = el('div', 'kpis');
    [['Tokens', ST.compact(t.tokens), '其中输出 ' + ST.compact(t.output)],
      ['缓存命中率', ST.pct(t.rate), '读缓存 ' + ST.compact(t.cache_read)],
      ['回复', ST.compact(t.n), d.tools + ' 次工具调用'],
      ['会话', d.sessions, d.prompts + ' 次提问'],
      ['活跃天数', d.active_days, '最长连续 ' + d.best_streak + ' 天 · 当前 ' + d.streak + ' 天'],
      ['最常用的模型', d.favorite ? d.favorite.name : '—', d.favorite ? ST.pct(d.favorite.share, 0) + ' 的回复' : ''],
      ['最忙的时段', d.peak ? '周' + ST.WEEK[d.peak.weekday] + ' ' + ST.pad(d.peak.hour) + ':00' : '—', d.peak ? d.peak.n + ' 次回复' : '']
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
      ST.store('st-metric', v);
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
    c.body.appendChild(ST.grid(['模型', '回复', '未缓存的输入', '输出', '其中思考', '读缓存', '写缓存', '命中率', '费用'], d.models.map(function (m) {
      return [ST.swatch(slotClass(m.slot), m.name), ST.compact(m.n), ST.compact(m.input), ST.compact(m.output), ST.compact(m.thinking),
        ST.compact(m.cache_read), ST.compact(m.cache_write), ST.pct(m.rate, 0), m.priced ? ST.money(m.cost) : '—'];
    }), { share: d.models.map(function (m) { return t.cost ? m.cost / t.cost : 0; }) }));

    var hasRealAcct = d.by_account.some(function (a) { return !!a.key; });
    if (hasRealAcct || d.quota.length) {
      c = card('账号', d.quota.length ? '额度是应用自己记下的最近一次：5 小时窗口和 7 天窗口用了多少' : '');
      c.body.appendChild(ST.grid(['账号', '会话', '回复', 'Tokens', '命中率', '费用'], d.by_account.map(function (a) {
        return [a.key ? ST.acctChip(a) : '未关联账号', a.sessions, ST.compact(a.n), ST.compact(a.tokens), ST.pct(a.rate, 0), ST.cost(a)];
      }), { share: d.by_account.map(function (a) { return t.cost ? a.cost / t.cost : 0; }) }));
      if (d.quota.length) {
        var qs = el('div', 'quota');
        d.quota.forEach(function (q) {
          var b = el('div', 'qcard'), h = el('div', 'qh');
          h.appendChild(ST.acctChip({ key: q.org, name: q.account, email: q.email }));
          h.appendChild(el('small', null, '记于 ' + ST.ago(q.t)));
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
    c.body.appendChild(ST.grid(['推理强度', '回复', '输出', '其中思考', '费用'], d.efforts.map(function (e) {
      return [e.effort || '（未记录）', ST.compact(e.n), ST.compact(e.output), ST.compact(e.thinking), ST.cost(e)];
    }), { share: d.efforts.map(function (e) { return t.cost ? e.cost / t.cost : 0; }) }));
    c = card('项目', '前 20 个');
    two.appendChild(c.box);
    c.body.appendChild(ST.grid(['项目', '会话', '回复', 'Tokens', '费用'], d.projects.map(function (p) {
      var meta = ST.SRC[p.src];
      var suffix = src === 'all' && meta && meta.cls ? '（' + meta.name + '）' : '';
      return [p.proj + suffix, p.sessions, ST.compact(p.n), ST.compact(p.tokens), ST.cost(p)];
    }), { share: d.projects.map(function (p) { return t.cost ? p.cost / t.cost : 0; }) }));

    c = card('花得最多的会话', '');
    var ol = el('ol', 'toplist');
    d.top.forEach(function (x) {
      var li = el('li'), head = el('div', 'tl-title'), a = el('a', null, x.title);
      a.href = '/s/' + x.page;
      head.appendChild(a);
      var meta = ST.SRC[x.src];
      if (src === 'all' && meta && meta.cls) head.appendChild(el('span', 'badge ' + meta.cls, meta.name));
      li.appendChild(head);
      li.appendChild(el('small', null, x.proj + (x.account ? ' · ' + x.account : '') + ' · ' + ST.compact(x.n) + ' 次回复'));
      li.appendChild(el('b', null, ST.cost(x)));
      ol.appendChild(li);
    });
    c.body.appendChild(ol);
  }

  window.addEventListener('resize', ST.debounce(function () { if (data) draw(); }, 200));
  paintRange();
  ST.pickSource(ST.store('src') || 'claude');
  load();
})();
