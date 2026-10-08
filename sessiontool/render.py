"""条目 → HTML / Markdown。

两种页面：服务模式（工具详情和图片按需向本地服务要），以及独立文件模式（导出用，所有内容内嵌）。
"""
import collections
import html
import os
import re
from datetime import datetime

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
WEEK = '一二三四五六日'

# ---------- 极简 Markdown ----------

LIST = re.compile(r'^(\s*)([-*+]|\d+[.)])\s+(.*)')
TABLE_SEP = re.compile(r'\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?')


def inline(s):
    codes = []

    def stash(m):
        codes.append('<code>' + html.escape(m.group(1)) + '</code>')
        return '\x00%d\x00' % (len(codes) - 1)

    def link(m):
        text, url = m.group(1), m.group(2).replace('"', '&quot;')
        if re.match(r'https?://', url):
            return '<a href="%s" target="_blank" rel="noopener">%s</a>' % (url, text)
        return '<span class="flink" title="%s">%s</span>' % (url, text)

    s = re.sub(r'`([^`\n]+)`', stash, s.replace('\x00', ''))
    s = html.escape(s, quote=False)
    s = re.sub(r'\[([^\]\n]+)\]\(([^)\s]+)\)', link, s)
    s = re.sub(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])', r'<em>\1</em>', s)
    return re.sub(r'\x00(\d+)\x00', lambda m: codes[int(m.group(1))], s)


def cells(row):
    row = row.strip().replace('\\|', '\x01')
    if row.startswith('|'):
        row = row[1:]
    if row.endswith('|'):
        row = row[:-1]
    return [c.strip().replace('\x01', '|') for c in row.split('|')]


def md(text):
    out, para = [], []
    lines = text.replace('\r\n', '\n').split('\n')

    def flush():
        if para:
            out.append('<p>' + '<br>'.join(inline(x) for x in para) + '</p>')
            del para[:]

    i = 0
    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        if st.startswith('```'):
            flush()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i])
                i += 1
            out.append('<pre><code>' + html.escape('\n'.join(buf)) + '</code></pre>')
            i += 1
            continue
        if not st:
            flush()
            i += 1
            continue
        m = re.match(r'(#{1,6})\s+(.*)', st)
        if m:
            flush()
            n = min(len(m.group(1)) + 2, 6)
            out.append('<h%d>%s</h%d>' % (n, inline(m.group(2)), n))
            i += 1
            continue
        if re.fullmatch(r'(-{3,}|\*{3,}|_{3,})', st):
            flush()
            out.append('<hr>')
            i += 1
            continue
        if '|' in st and i + 1 < len(lines) and TABLE_SEP.fullmatch(lines[i + 1].strip() or 'x'):
            flush()
            head = cells(st)
            i += 2
            rows = []
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                rows.append(cells(lines[i]))
                i += 1
            t = '<div class="tw"><table><thead><tr>' + ''.join('<th>%s</th>' % inline(c) for c in head) + '</tr></thead><tbody>'
            for r in rows:
                t += '<tr>' + ''.join('<td>%s</td>' % inline(c) for c in r) + '</tr>'
            out.append(t + '</tbody></table></div>')
            continue
        m = LIST.match(ln)
        if m:
            flush()
            ordered = m.group(2)[0].isdigit()
            start = re.sub(r'\D', '', m.group(2)) if ordered else ''
            buf = []
            while i < len(lines):
                m2 = LIST.match(lines[i])
                if m2:
                    buf.append([len(m2.group(1).expandtabs(4)), m2.group(3)])
                elif lines[i].strip() and lines[i][:1] in ' \t':
                    buf[-1][1] += '\n' + lines[i].strip()
                else:
                    break
                i += 1
            base = min(b[0] for b in buf)
            tag = 'ol start="%s"' % start if ordered else 'ul'
            out.append('<%s>' % tag + ''.join(
                '<li style="margin-left:%.1fem">%s</li>' % ((ind - base) // 2 * 1.2, inline(t).replace('\n', '<br>'))
                for ind, t in buf) + '</%s>' % tag[:2])
            continue
        if st.startswith('>'):
            flush()
            buf = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i]))
                i += 1
            out.append('<blockquote>' + md('\n'.join(buf)) + '</blockquote>')
            continue
        para.append(st)
        i += 1
    flush()
    return '\n'.join(out)

# ---------- 小工具 ----------


def esc(s):
    return html.escape(str(s), quote=True)


def local(iso):
    try:
        return datetime.fromisoformat((iso or '').replace('Z', '+00:00')).astimezone()
    except ValueError:
        return None


def fmt(iso, f='%Y-%m-%d %H:%M'):
    t = local(iso)
    return t.strftime(f) if t else ''


def tokens(n):
    return '%.0fk' % (n / 1000.0) if isinstance(n, (int, float)) else '?'


def static_text(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as f:
        return f.read()


def head(title, standalone):
    style = '<style>%s</style>' % static_text('app.css') if standalone else '<link rel="stylesheet" href="/static/app.css">'
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title>%s</head>' % (esc(title), style))

# ---------- 会话页 ----------


class ServerMode:
    """工具详情和图片留给浏览器按需请求。"""
    standalone = False

    def image(self, ref):
        return '/img/' + ref

    def tool_body(self, t):
        return '<div class="tc"></div>'

    def tool_attrs(self, t):
        url = '/api/tool?u=' + t['use'] + ('&r=' + t['res'] if t['res'] else '')
        return ' data-u="%s"' % url


class Renderer:
    def __init__(self, mode):
        self.mode = mode
        self.ids = set()
        self.toc = []
        self.day = None

    def anchor(self, prefix, u):
        key = prefix + u
        if not u or key in self.ids:
            return ''
        self.ids.add(key)
        return ' id="%s"' % key

    def pics(self, refs):
        out = []
        for ref in refs:
            url = self.mode.image(ref)
            if url:
                out.append('<a href="%s" target="_blank"><img class="pic" loading="lazy" src="%s" alt="图片"></a>' % (url, url))
        return ''.join(out)

    def tool(self, t):
        badges = ''
        if t['error']:
            badges += ' <span class="badge err">失败</span>'
        if t['nimg']:
            badges += ' <span class="badge">%d 图</span>' % t['nimg']
        if not t['res']:
            badges += ' <span class="badge">无输出记录</span>'
        attrs = self.anchor('t-', t['u']) + (' data-r="%s"' % t['ru'] if t['ru'] else '') + self.mode.tool_attrs(t)
        return ('<details class="tool"%s><summary><code>%s</code> <span class="hint">%s</span>%s</summary>%s</details>'
                % (attrs, esc(t['name']), esc(t['hint']), badges, self.mode.tool_body(t)))

    def items(self, items, main=True):
        out = []
        for it in items:
            k = it['kind']
            t = local(it.get('ts'))
            if main and t and t.date() != self.day and k in ('user', 'asst', 'tools'):
                self.day = t.date()
                label = '%s 周%s' % (t.strftime('%Y-%m-%d'), WEEK[t.weekday()])
                out.append('<div class="day">%s</div>' % label)
                self.toc.append('<div class="d">%s</div>' % label)
            if k == 'user':
                num = '#%d' % it['n'] if it.get('n') else ''
                tag = ' <span class="badge">回复进行中追加</span>' if it.get('queued') else ''
                if main and it.get('n'):
                    self.toc.append('<a href="#m-%s" title="%s"><small>%s</small> %s</a>' % (
                        it['u'], esc(it['text'][:300]), fmt(it['ts'], '%H:%M'), esc(it['text'][:40].replace('\n', ' ') or '（图片）')))
                out.append('<section class="msg user"%s><header><b>你</b> · %s · %s%s</header><div class="body">%s%s</div></section>'
                           % (self.anchor('m-', it['u']), fmt(it['ts']), num, tag, md(it['text']), self.pics(it['imgs'])))
            elif k == 'asst':
                out.append('<section class="msg asst"%s><header><b>Claude</b> · %s</header><div class="body">%s</div></section>'
                           % (self.anchor('m-', it['u']), fmt(it['ts']), md(it['text'])))
            elif k == 'notice':
                out.append('<div class="line"%s>%s · %s</div>' % (self.anchor('m-', it['u']), esc(it['text'][:300]), fmt(it['ts'], '%H:%M')))
            elif k == 'tools':
                cnt = collections.Counter(x['name'] for x in it['tools'])
                label = '、'.join('%s×%d' % (n, c) if c > 1 else n for n, c in cnt.most_common())
                fails = sum(1 for x in it['tools'] if x['error'])
                out.append('<details class="tools"><summary>工具调用 %d 次：%s%s</summary>%s</details>' % (
                    len(it['tools']), esc(label), ' <span class="badge err">%d 次失败</span>' % fails if fails else '',
                    ''.join(self.tool(x) for x in it['tools'])))
            elif k == 'think':
                out.append('<details class="fold think"><summary>思考过程</summary><div class="body">%s</div></details>' % md(it['text']))
            elif k == 'summary':
                out.append('<details class="fold"%s><summary>上下文压缩摘要 · %s</summary><div class="body">%s</div></details>'
                           % (self.anchor('m-', it['u']), fmt(it['ts']), md(it['text'])))
            elif k == 'compact':
                how = {'auto': '自动', 'manual': '手动'}.get(it['trigger'], '')
                out.append('<div class="line">上下文已%s压缩（%s → %s tokens）· %s</div>' % (how, tokens(it['pre']), tokens(it['post']), fmt(it['ts'], '%H:%M')))
            elif k == 'note':
                out.append('<details class="fold sys"><summary>系统通知 · %s</summary><pre>%s</pre></details>' % (fmt(it['ts']), esc(it['text'][:5000])))
            elif k == 'cmd':
                out.append('<details class="fold sys"><summary>本地命令 <code>%s</code> · %s</summary><pre>%s</pre></details>'
                           % (esc((it['cmd'] + ' ' + it['args']).strip()[:120]), fmt(it['ts']), esc(it['out'])))
            elif k == 'stop':
                out.append('<div class="line">你中断了这次回复 · %s</div>' % fmt(it['ts'], '%H:%M'))
            elif k == 'auto':
                out.append('<div class="line">额度恢复，应用自动发送了“继续” · %s</div>' % fmt(it['ts'], '%H:%M'))
            elif k == 'fork':
                out.append('<div class="forkline">以上来自原会话 · 从这里开始是复刻后的内容</div>')
                self.toc.append('<div class="d">—— 复刻点 ——</div>')
            elif k == 'branch':
                n = sum(1 for x in it['items'] if x['kind'] in ('user', 'asst'))
                out.append('<details class="fold branch"><summary>改写前的旧分支（%d 条消息，应用里已不显示）· %s</summary>%s</details>'
                           % (n, fmt(it['ts']), ''.join(self.items(it['items'], main=False))))
        return out


def session_page(s, c, mode, parent=None):
    """parent: (页面编号, 标题)，仅复刻的会话有。"""
    r = Renderer(mode)
    body = r.items(c['items'])
    extra = ''
    if parent:
        extra += '　·　复刻自 ' + (esc(parent[1]) if mode.standalone else '<a href="/s/%s">%s</a>' % (parent[0], esc(parent[1])))
    if c['nfiles'] > 1:
        extra += '　·　由 %d 份记录合并' % c['nfiles']
    if c['n_branch']:
        extra += '　·　%d 处改写' % c['n_branch']
    meta = '%s　·　%s → %s　·　你 %d 条 / Claude %d 段 / 工具 %d 次%s' % (
        esc(s.cwd), fmt(c['first']), fmt(c['last']), c['n_user'], c['n_asst'], c['n_tools'], extra)
    if mode.standalone:
        bar = ('<div class="bar"><button data-act="tools">展开/收起工具调用</button><label><input type="checkbox" id="onlychat"> 只看对话</label></div>')
        back = ''
        script = '<script>%s</script>' % static_text('standalone.js')
    else:
        bar = ('<div class="bar"><input id="fq" type="search" placeholder="在本会话中搜索…">'
               '<label><input type="checkbox" id="onlychat"> 只看对话</label>'
               '<button data-act="tools">展开/收起工具调用</button>'
               '<a class="btn" href="/export/%s.html" title="单个 HTML 文件，可离线打开">导出 HTML</a>'
               '<a class="btn" href="/export/%s.md">导出 Markdown</a></div>' % (s.page, s.page))
        back = '<a class="back" href="/">← 全部会话</a>'
        script = '<script src="/static/app.js"></script>'
    # 拼接而不是 % 格式化：内嵌的样式和脚本里有 % 号
    return ''.join([head(c['title'], mode.standalone), '<body class="session"><div class="layout"><nav>', back, ''.join(r.toc),
                    '</nav><main><h1>', esc(c['title']), '</h1><div class="meta">', meta, '</div>', bar, '\n'.join(body),
                    '</main></div>', script, '</body></html>'])

# ---------- 索引页 ----------


def index_page(entries):
    """entries: [(session, content, parent_title)]，已按最后活动时间倒序。"""
    rows = []
    for s, c, parent_title in entries:
        tags = ''
        if s.parent:
            tags += '<span class="badge">复刻</span>'
        if s.archived:
            tags += '<span class="badge">已归档</span>'
        if s.orphan:
            tags += '<span class="badge">不在应用列表中</span>'
        sub = esc(c['first_prompt'][:100])
        if parent_title:
            sub = '复刻自「%s」　' % esc(parent_title) + sub
        rows.append('<tr data-page="%s" data-p="%s" data-t="%s" data-a="%s"><td><a href="/s/%s">%s</a>%s<small>%s</small></td>'
                    '<td class="n">%s</td><td class="n">%s</td><td class="n">%d</td><td class="n">%.1f MB</td></tr>'
                    % (s.page, esc(s.proj), esc(c['title'].lower()), '1' if s.archived else '', s.page, esc(c['title']), tags, sub,
                       esc(s.proj), fmt(c['last']), c['n_user'], s.size / 1048576))
    projects = sorted(set(s.proj for s, _, _ in entries))
    opts = '<option value="">全部项目</option>' + ''.join('<option>%s</option>' % esc(p) for p in projects)
    return ''.join([
        head('Claude 会话记录', False), '<body class="index"><main><h1>Claude 会话记录</h1>',
        '<div class="meta">显示 <span id="cnt">%d</span> / %d 个会话 · 刷新页面即读取最新记录</div>' % (len(rows), len(rows)),
        '<div class="bar"><input id="q" type="search" placeholder="搜索全部会话的对话内容…" autofocus>',
        '<select id="pj">', opts, '</select>',
        '<label><input type="checkbox" id="tl"> 含工具调用与输出</label>',
        '<label><input type="checkbox" id="ar" checked> 含已归档</label></div><div id="hits"></div>',
        '<table class="idx"><thead><tr><th>会话</th><th>项目</th><th>最后活动</th><th>提问</th><th>记录大小</th></tr></thead><tbody>',
        '\n'.join(rows), '</tbody></table></main><script src="/static/app.js"></script></body></html>'])

# ---------- Markdown 导出 ----------


def session_markdown(s, c):
    out = ['# %s\n' % c['title'],
           '%s　·　%s → %s　·　你 %d 条 / Claude %d 段\n' % (s.cwd, fmt(c['first']), fmt(c['last']), c['n_user'], c['n_asst'])]

    def walk(items, depth=0):
        for it in items:
            k = it['kind']
            if k == 'user':
                out.append('\n---\n\n## 你 %s　%s\n\n%s\n' % ('#%d' % it['n'] if it.get('n') else '', fmt(it['ts']), it['text']))
                if it['imgs']:
                    out.append('（附图 %d 张，未收录）\n' % len(it['imgs']))
            elif k == 'asst':
                out.append('\n### Claude　%s\n\n%s\n' % (fmt(it['ts']), it['text']))
            elif k == 'tools':
                out.append('\n> 工具调用：' + '、'.join('%s（%s）' % (t['name'], t['hint']) if t['hint'] else t['name'] for t in it['tools']) + '\n')
            elif k == 'summary':
                out.append('\n<details><summary>上下文压缩摘要　%s</summary>\n\n%s\n\n</details>\n' % (fmt(it['ts']), it['text']))
            elif k == 'fork':
                out.append('\n---\n\n**以上来自原会话，从这里开始是复刻后的内容**\n')
            elif k == 'stop':
                out.append('\n*（你中断了这次回复）*\n')
            elif k == 'branch':
                out.append('\n<details><summary>改写前的旧分支</summary>\n')
                walk(it['items'], depth + 1)
                out.append('\n</details>\n')

    walk(c['items'])
    return ''.join(out)
