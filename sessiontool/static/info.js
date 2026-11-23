// 会话详情抽屉、工具调用按需加载、折叠块按需高度过渡与代码块复制按钮（列表页与会话页共用）
(function () {
  'use strict';
  var ST = window.ST;
  var $ = ST.$, el = ST.el, ibtn = ST.ibtn;

  var PERMISSION = {
    'default': '每次询问', acceptEdits: '自动接受编辑', plan: '计划模式', auto: '自动判断', bypassPermissions: '跳过权限确认',
    never: '从不询问', 'on-request': '需要时询问', 'on-failure': '失败时询问', untrusted: '不受信任的命令要询问'
  };
  var STATUS = { completed: '已完成', review_ready: '等你过目', blocked: '受阻', in_progress: '进行中', needs_input: '等你处理', failed: '失败' };
  var ORIGIN = {
    codex_exec: '命令行（codex exec）', 'codex-tui': '终端界面', codex_cli_rs: '命令行', vscode: 'VS Code 扩展', codex_vscode: 'VS Code 扩展',
    cli: '命令行（Claude Code）', 'sdk-cli': '命令行（SDK）', 'claude-vscode': 'VS Code 扩展',
    'claude-desktop': 'Claude 桌面应用', 'claude-desktop-3p': 'Claude 桌面应用', 'local-agent': 'Claude 桌面应用', local_agent: 'Claude 桌面应用',
    antigravity: 'Antigravity 应用', 'antigravity-cli': '命令行（Antigravity CLI）'
  };

  function usageSection(b, u, agents) {
    var s = ST.section(b, '费用与用量');
    var hero = el('div', 'hero');
    hero.appendChild(el('b', null, ST.cost(u)));
    hero.appendChild(el('span', null, '按 API 价格估算 · ' + u.n + ' 次回复' + (agents ? '（含 ' + agents + ' 个子代理的）' : '')));
    s.appendChild(hero);
    ST.costBar(s, u.parts);
    ST.tiles(s, [['缓存命中率', ST.pct(u.rate)], ['输出', u.output], ['未缓存的输入', u.input], ['读缓存', u.cache_read],
      ['写缓存', u.cache_write], ['其中思考', u.thinking, 1], ['网页搜索', u.web, 1]]);
    s.appendChild(el('small', 'hint', '订阅不按 token 计费，这是同样的用量按 API 计价的金额。缓存命中率是读缓存占全部输入的比例。'
      + (u.unpriced ? ' ' + ST.unpricedNote(u) + '。' : '')));
    if (u.models.length) {
      s = ST.section(b, '按模型');
      s.appendChild(ST.grid(['模型', '回复', '输出', '命中率', '费用'], u.models.map(function (m) {
        return [m.name || '未记录模型', m.n, ST.compact(m.output), ST.pct(m.rate, 0), m.priced ? ST.money(m.cost) : '—'];
      }), { share: u.models.map(function (m) { return u.cost ? m.cost / u.cost : 0; }) }));
    }
    if (u.efforts.length) {
      s = ST.section(b, '按推理强度');
      s.appendChild(ST.grid(['推理强度', '回复', '输出', '费用'], u.efforts.map(function (e) {
        return [e.effort || '（未记录）', e.n, ST.compact(e.output), ST.cost(e)];
      }), { share: u.efforts.map(function (e) { return u.cost ? e.cost / u.cost : 0; }) }));
    }
  }

  function fillInfo(b, d) {
    var p = ST.SRC[d.src] || ST.SRC.claude;
    var isSession = ST.body.classList.contains('session');
    var t = el('div', 'dtitle');
    t.appendChild(el('strong', null, d.title));
    var tags = el('div', 'dtags');
    tags.appendChild(el('span', 'badge', d.proj));
    if (d.account) tags.appendChild(ST.acctChip(d.account));
    tags.appendChild(el('span', 'badge ' + p.badge, p.name));
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

    var s = ST.section(b, '标识');
    if (d.id) s.appendChild(ST.field('应用会话 ID', d.id, { hint: '在 Claude 里提到这个会话时用它' }));
    s.appendChild(ST.field(p.idLabel, d.cli, { hint: p.idHint }));
    d.files.filter(function (f) { return !f.current; }).forEach(function (f) { s.appendChild(ST.field('更早的记录 ID', f.id)); });
    s.appendChild(ST.field('恢复命令', d.resume, { hint: '在终端里的项目文件夹下运行' }));
    if (d.link) s.appendChild(ST.field('应用链接', d.link));

    if (d.account || d.org || d.store) {
      s = ST.section(b, '账号');
      if (d.account && d.account.email) s.appendChild(ST.field('邮箱', d.account.email));
      if (d.account && d.account.id) s.appendChild(ST.field('账号 ID', d.account.id));
      if (d.org) s.appendChild(ST.field('组织 ID', d.org));
      ST.pairs(s, [['multi-claude 配置', d.store], [p.verLabel, d.version], ['从哪里开始的', ORIGIN[d.origin] || d.origin]]);
    } else if (d.origin || d.version) {
      s = ST.section(b, '来源');
      ST.pairs(s, [['从哪里开始的', ORIGIN[d.origin] || d.origin], ['版本', d.version]]);
    }

    s = ST.section(b, '位置');
    s.appendChild(ST.field('项目文件夹', d.cwd || '无文件夹', d.cwd ? {} : { plain: true, copy: false }));
    d.files.forEach(function (f) { s.appendChild(ST.field(f.current ? '记录文件（当前）' : '记录文件', f.path, { note: ST.bytes(f.size) })); });

    s = ST.section(b, '时间');
    ST.pairs(s, [['创建', ST.stamp(d.created)], ['第一条消息', ST.stamp(d.first)], ['最后活动', ST.stamp(d.last)], ['前后跨度', ST.span(d.first, d.last)]]);

    if (d.usage && d.usage.n) usageSection(b, d.usage, d.agents);

    s = ST.section(b, '模型与设置');
    ST.pairs(s, [['当前模型', d.model], ['推理强度', d.effort], [p.permLabel, PERMISSION[d.permission] || d.permission],
      ['完成的轮数', d.turns != null ? String(d.turns) : ''], ['写入过的分支', (d.branches || []).join('、')]]);

    s = ST.section(b, '数量');
    var c = d.counts;
    ST.tiles(s, [['提问', c.prompts], ['答复', c.replies], ['工具调用', c.tools], ['工具截图', c.shots, 1], ['你发的图片', c.images, 1],
      ['发给你的文件', c.sent, 1], ['修改的文件', c.changed, 1], ['上下文压缩', c.compact, 1], ['改写', c.branch, 1],
      ['记录文件', c.records], ['记录大小', ST.bytes(d.size)]]);

    if (d.tools && d.tools.length) {
      s = ST.section(b, '用得最多的工具');
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
      s = ST.section(b, '提问');
      s.appendChild(ST.field('第一条', d.first_prompt, { plain: true, copy: false }));
      if (d.last_prompt && d.last_prompt !== d.first_prompt) s.appendChild(ST.field('最近一条', d.last_prompt, { plain: true, copy: false }));
    }

    var rel = (d.parent ? [['复刻自', d.parent]] : []).concat((d.children || []).map(function (x) { return ['它的复刻', x]; }));
    if (rel.length) {
      s = ST.section(b, '相关会话');
      rel.forEach(function (r) {
        var a = el('a', 'rel');
        a.href = '/s/' + r[1].page;
        a.appendChild(el('small', null, r[0]));
        a.appendChild(el('span', null, r[1].title));
        if (ST.live) s.appendChild(a); else s.appendChild(el('div', 'rel', r[0] + '：' + r[1].title));
      });
    }
    if (d.subagents && d.subagents.length) {
      s = ST.section(b, '子代理（' + d.subagents.length + '）');
      d.subagents.forEach(function (ag) {
        if (ST.live) {
          var a = el('a', 'rel');
          a.href = '/agent/' + encodeURIComponent(ag.id);
          a.appendChild(el('small', null, ag.id.slice(0, 8)));
          a.appendChild(el('span', null, ag.name));
          s.appendChild(a);
        } else {
          s.appendChild(el('div', 'rel', ag.name));
        }
      });
    }
  }

  function openInfo(page) {
    var b = ST.openLayer('drawer', '会话详情');
    var own = $('#info');
    if (own && (!page || page === ST.body.dataset.page)) { fillInfo(b, JSON.parse(own.textContent)); return; }
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

  /* ================= 工具调用按需加载与折叠块动效 ================= */

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
      if (ST.onToolLoaded) ST.onToolLoaded(d);
    }).catch(function () {
      d.dataset.done = '';
      tc.textContent = '加载失败，收起后再展开可重试。';
    });
  }

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

  document.addEventListener('mouseover', function (e) {
    var c = e.target.closest && e.target.closest('.code');
    if (c && !c.dataset.cc) {
      c.dataset.cc = '1';
      c.appendChild(ibtn('copy', '复制', 'sm cc'));
    }
  });

  ST.openInfo = openInfo;
})();
