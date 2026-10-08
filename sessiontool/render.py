"""条目 → HTML / Markdown。

两种页面：服务模式（工具详情和图片按需向本地服务要），以及独立文件模式（导出用，所有内容内嵌）。
"""
import collections
import html
import os
import re
import zlib
from datetime import datetime
from urllib.parse import quote

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


def when(iso, now=None):
    """列表里用的简短时间：今天只写时刻，昨天写“昨天”，再早写日期。"""
    t = local(iso)
    if not t:
        return ''
    now = now or datetime.now().astimezone()
    days = (now.date() - t.date()).days
    if days == 0:
        return t.strftime('%H:%M')
    if days == 1:
        return '昨天 ' + t.strftime('%H:%M')
    return t.strftime('%m-%d %H:%M' if t.year == now.year else '%Y-%m-%d')


def bucket(iso, now=None):
    t = local(iso)
    if not t:
        return '更早'
    now = now or datetime.now().astimezone()
    days = (now.date() - t.date()).days
    if days <= 0:
        return '今天'
    if days == 1:
        return '昨天'
    if days < 7:
        return '近 7 天'
    return '%d 月' % t.month if t.year == now.year else '%d 年 %d 月' % (t.year, t.month)


def size(n):
    return '%.1f GB' % (n / 1073741824) if n >= 1073741824 else '%.1f MB' % (n / 1048576)


def tokens(n):
    return '%.0fk' % (n / 1000.0) if isinstance(n, (int, float)) else '?'


def looks_like_path(s):
    return bool(re.match(r'([A-Za-z]:[\\/]|/|~[\\/])', s)) and '\n' not in s


def short_path(path, cwd='', keep=64):
    """长路径只留有辨识度的部分：在项目内的写相对路径，否则留末尾。"""
    norm = lambda p: p.replace('/', '\\').rstrip('\\').lower()
    if cwd and norm(path).startswith(norm(cwd) + '\\'):
        path = path[len(cwd.rstrip('\\/')) + 1:]
    return path if len(path) <= keep else '…' + path[-keep:]


def preview(text):
    """列表里的一行摘要：@"C:\\很长\\的路径\\文件.doc" 只留文件名。"""
    text = re.sub(r'@"([^"]+)"', lambda m: '@' + re.split(r'[\\/]', m.group(1).rstrip('\\/'))[-1], text)
    return re.sub(r'\s+', ' ', text).strip()


def hue(name):
    return zlib.crc32(name.encode('utf-8')) % 360


def static_text(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as f:
        return f.read()


def head(title, standalone):
    """主题脚本放在 head 里同步执行，免得深色模式下先闪一下白底。"""
    if standalone:
        assets = '<style>' + static_text('app.css') + '</style><script>' + static_text('theme.js') + '</script>'
    else:
        assets = ('<link rel="icon" href="/static/icon.svg"><link rel="stylesheet" href="/static/app.css">'
                  '<script src="/static/theme.js"></script>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(title) + '</title>'
            + assets + '</head>')


def scripts(standalone):
    return '<script>' + static_text('app.js') + '</script>' if standalone else '<script src="/static/app.js"></script>'


THEME_BUTTON = '<button type="button" id="theme" title="切换浅色 / 深色 / 跟随系统"></button>'
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
MINOR = ('stop', 'auto', 'notice', 'note', 'compact', 'cmd', 'summary', 'think')


def duration(a, b):
    ta, tb = local(a), local(b)
    if not ta or not tb or tb < ta:
        return ''
    m = int((tb - ta).total_seconds() // 60)
    if m < 1:
        return '不到 1 分钟'
    if m < 60:
        return '%d 分钟' % m
    return '%d 小时 %d 分' % divmod(m, 60) if m % 60 else '%d 小时' % (m // 60)


def split_turns(items):
    """条目 → 轮次。一轮 = 你的一条消息，加上之后直到你下一条消息之前的全部内容。

    每轮是 {'prompt', 'steps', 'finals', 'tail', 'plain'}：finals 是这一轮末尾连续的 Claude 回复（最终答复），
    steps 是它之前的中间过程，tail 是答复之后的零碎提示；plain 表示 steps 里没有真正的过程，不必单独成块。
    复刻点、旧分支这类标记单独成一项 {'mark': 条目}。
    """
    turns, cur = [], None

    def close():
        nonlocal cur
        if cur is None:
            return
        prompt, rest = cur
        cur = None
        tail, finals = [], []
        while rest and rest[-1]['kind'] in MINOR:
            tail.insert(0, rest.pop())
        while rest and rest[-1]['kind'] == 'asst':
            finals.insert(0, rest.pop())
        if not finals:              # 没有最终答复：零碎提示放回原处，保持时间顺序
            rest, tail = rest + tail, []
        plain = not any(it['kind'] in ('asst', 'tools', 'sent') for it in rest)
        if prompt or rest or finals or tail:
            turns.append({'prompt': prompt, 'steps': rest, 'finals': finals, 'tail': tail, 'plain': plain})

    for it in items:
        if it['kind'] in ('fork', 'branch'):
            close()
            turns.append({'mark': it})
        elif it['kind'] == 'user':
            close()
            cur = (it, [])
        else:
            if cur is None:
                cur = (None, [])
            cur[1].append(it)
    close()
    return turns

# ---------- 会话页 ----------


class ServerMode:
    """工具详情和图片留给浏览器按需向本地服务请求。"""
    standalone = False

    def __init__(self, agents=()):
        self.agents = agents

    def image(self, ref):               # 你发的图片
        return '/img/' + ref

    def shot(self, ref):                # 工具输出里的截图
        return '/img/' + ref

    def local(self, path):              # 应用另存到 tool-results 的截图；别处的路径服务端不给读，这里就不放
        ok = os.path.basename(os.path.dirname(path)) == 'tool-results' and os.path.isfile(path)
        return '/local?p=' + quote(path, safe='') if ok else ''

    def sent(self, ref, path):          # 发给你的图片文件，原位置还在才显示
        return '/sent/' + ref if os.path.isfile(path) else ''

    def agent(self, agent_id):
        return '/agent/' + quote(agent_id, safe='') if agent_id in self.agents else ''

    def tool_body(self, t):
        return '<div class="tc"></div>'

    def tool_attrs(self, t):
        url = '/api/tool?u=' + t['use'] + ('&r=' + t['res'] if t['res'] else '')
        return ' data-u="%s"' % url


class Renderer:
    def __init__(self, mode, cwd=''):
        self.mode = mode
        self.cwd = cwd
        self.ids = set()
        self.toc = []
        self.day = None

    def anchor(self, prefix, u):
        key = prefix + u
        if not u or key in self.ids:
            return ''
        self.ids.add(key)
        return ' id="%s"' % key

    def stamp(self, iso):
        return '<time title="%s">%s</time>' % (fmt(iso, '%Y-%m-%d %H:%M:%S'), fmt(iso, '%H:%M'))

    def daymark(self, it, main):
        t = local(it.get('ts'))
        if not main or not t or t.date() == self.day:
            return ''
        self.day = t.date()
        label = '%s 周%s' % (t.strftime('%Y-%m-%d'), WEEK[t.weekday()])
        self.toc.append('<div class="d">%s</div>' % label)
        return '<div class="day"><span>%s</span></div>' % label

    def pics(self, urls, cls='pics'):
        urls = [u for u in urls if u]
        if not urls:
            return ''
        return '<div class="%s">%s</div>' % (cls, ''.join('<img class="pic" loading="lazy" src="%s" alt="图片">' % u for u in urls))

    # ----- 各种条目 -----

    def user(self, it, main):
        anchor = self.anchor('m-', it['u'])
        num = '<a class="num" href="#m-%s">#%d</a>' % (it['u'], it['n']) if it.get('n') else ''
        tag = '<span class="badge">回复进行中追加</span>' if it.get('queued') else ''
        if main and it.get('n') and anchor:
            self.toc.append('<a href="#m-%s" title="%s"><b>%d</b><span>%s</span></a>' % (
                it['u'], esc(fmt(it['ts']) + '\n' + it['text'][:300]), it['n'], esc(preview(it['text'])[:60] or '（图片）')))
        body = '<div class="body">%s</div>' % md(it['text']) if it['text'] else ''
        return ('<section class="msg user"%s><div class="av">你</div><div class="mc"><header><b>你</b>%s%s%s'
                '<button type="button" class="copy">复制</button></header>%s%s</div></section>'
                % (anchor, self.stamp(it['ts']), num, tag, body, self.pics(self.mode.image(r) for r in it['imgs'])))

    def final(self, it):
        return ('<section class="msg asst"%s><div class="av">C</div><div class="mc"><header><b>Claude</b>%s'
                '<button type="button" class="copy">复制</button></header><div class="body">%s</div></div></section>'
                % (self.anchor('m-', it['u']), self.stamp(it['ts']), md(it['text'])))

    def step(self, it):
        return '<div class="step"%s>%s<div class="body">%s</div></div>' % (self.anchor('m-', it['u']), self.stamp(it['ts']), md(it['text']))

    def tool(self, t):
        badges = ''
        if t['error']:
            badges += '<span class="badge err">失败</span>'
        if t['nimg']:
            badges += '<span class="badge">%d 图</span>' % t['nimg']
        if not t['res']:
            badges += '<span class="badge">无输出记录</span>'
        sub = self.mode.agent(t['agent']) if t['agent'] else ''
        if sub:
            badges += '<a class="badge go" href="%s">查看子代理的过程 →</a>' % sub
        hint = short_path(t['hint'], self.cwd) if looks_like_path(t['hint']) else t['hint']
        attrs = self.anchor('t-', t['u']) + (' data-r="%s"' % t['ru'] if t['ru'] else '') + self.mode.tool_attrs(t)
        return ('<details class="tool"%s><summary><code>%s</code><span class="hint" title="%s">%s</span>%s</summary>%s</details>'
                % (attrs, esc(t['name']), esc(t['hint']), esc(hint), badges, self.mode.tool_body(t)))

    def tools(self, it):
        cnt = collections.Counter(x['name'] for x in it['tools'])
        label = '、'.join('%s ×%d' % (n, c) if c > 1 else n for n, c in cnt.most_common())
        fails = sum(1 for x in it['tools'] if x['error'])
        shots = [self.mode.shot(r) for x in it['tools'] for r in x['imgs']] + [self.mode.local(p) for x in it['tools'] for p in x['local']]
        return ('<details class="tools"><summary><span class="n">%d 次工具调用</span><span class="hint">%s</span>%s</summary>%s</details>%s' % (
            len(it['tools']), esc(label), '<span class="badge err">%d 次失败</span>' % fails if fails else '',
            ''.join(self.tool(x) for x in it['tools']), self.pics(shots, 'thumbs')))

    def sent(self, it):
        shown, names = [], []
        for path, ref in it['files']:
            name = re.split(r'[\\/]', path)[-1]
            url = self.mode.sent(ref, path) if path.lower().endswith(IMAGE_EXT) else ''
            if url:
                shown.append(url)
            else:
                gone = '' if os.path.exists(path) else '<small>已不在原位置</small>'
                names.append('<span class="file" title="%s">%s%s</span>' % (esc(path), esc(name), gone))
        return ('<div class="sent"%s><div class="k">发给你的文件 · %s</div>%s%s%s</div>' % (
            self.anchor('t-', it['u']), fmt(it['ts'], '%H:%M'), '<p>%s</p>' % esc(it['caption']) if it['caption'] else '',
            self.pics(shown), '<div class="files-sent">%s</div>' % ''.join(names) if names else ''))

    def line(self, text, iso, attrs=''):
        return '<div class="line"%s><span>%s · %s</span></div>' % (attrs, text, fmt(iso, '%H:%M'))

    def minor(self, it):
        k = it['kind']
        if k == 'think':
            return '<details class="fold think"><summary>思考过程</summary><div class="body">%s</div></details>' % md(it['text'])
        if k == 'summary':
            return ('<details class="fold"%s><summary>上下文压缩摘要 · %s</summary><div class="body">%s</div></details>'
                    % (self.anchor('m-', it['u']), fmt(it['ts'], '%H:%M'), md(it['text'])))
        if k == 'compact':
            how = {'auto': '自动', 'manual': '手动'}.get(it['trigger'], '')
            return self.line('上下文已%s压缩（%s → %s tokens）' % (how, tokens(it['pre']), tokens(it['post'])), it['ts'])
        if k == 'note':
            return '<details class="fold sys"><summary>系统通知 · %s</summary><pre>%s</pre></details>' % (fmt(it['ts'], '%H:%M'), esc(it['text'][:5000]))
        if k == 'cmd':
            return ('<details class="fold sys"><summary>本地命令 <code>%s</code> · %s</summary><pre>%s</pre></details>'
                    % (esc((it['cmd'] + ' ' + it['args']).strip()[:120]), fmt(it['ts'], '%H:%M'), esc(it['out'])))
        if k == 'stop':
            return self.line('你中断了这次回复', it['ts'])
        if k == 'auto':
            return self.line('额度恢复，应用自动发送了“继续”', it['ts'])
        if k == 'notice':
            return self.line(esc(it['text'][:300]), it['ts'], self.anchor('m-', it['u']))
        return ''

    def flow(self, items, main):
        """一轮里的中间内容，按时间顺序。"""
        out = []
        for it in items:
            k = it['kind']
            if k in ('asst', 'tools', 'sent'):
                out.append(self.daymark(it, main))
            out.append(self.step(it) if k == 'asst' else self.tools(it) if k == 'tools' else self.sent(it) if k == 'sent' else self.minor(it))
        return out

    def steps(self, t, main):
        """中间过程：可以整块折起来，只留最终答复。"""
        says = sum(1 for it in t['steps'] if it['kind'] == 'asst')
        calls = sum(len(it['tools']) for it in t['steps'] if it['kind'] == 'tools')
        shots = sum(x['nimg'] for it in t['steps'] if it['kind'] == 'tools' for x in it['tools'])
        parts = [p for p in ('%d 段说明' % says if says else '', '%d 次工具调用' % calls if calls else '',
                             '%d 张截图' % shots if shots else '') if p]
        start = (t['prompt'] or t['steps'][0]).get('ts')
        end = (t['finals'][0] if t['finals'] else t['steps'][-1]).get('ts')
        took = duration(start, end)
        if took:
            parts.append('用时 ' + took)
        if not t['finals']:
            parts.append('这一轮没有最终答复')
        return ('<details class="steps" open><summary><b>过程</b><span>%s</span></summary><div class="rail">%s</div></details>'
                % (' · '.join(parts), ''.join(self.flow(t['steps'], main))))

    def conversation(self, items, main=True):
        out = []
        for t in split_turns(items):
            mark = t.get('mark')
            if mark and mark['kind'] == 'fork':
                out.append('<div class="forkline"><span>以上来自原会话 · 从这里开始是复刻后的内容</span></div>')
                self.toc.append('<div class="d fk">复刻点</div>')
            elif mark:
                n = sum(1 for x in mark['items'] if x['kind'] in ('user', 'asst'))
                out.append('<details class="fold branch"><summary>改写前的旧分支（%d 条消息，应用里已不显示）· %s</summary>%s</details>'
                           % (n, fmt(mark['ts'], '%H:%M'), ''.join(self.conversation(mark['items'], main=False))))
            else:
                first = t['prompt'] or (t['steps'] + t['finals'] + t['tail'])[0]
                out.append(self.daymark(first, main))
                out.append('<article class="turn">')
                if t['prompt']:
                    out.append(self.user(t['prompt'], main))
                if t['plain']:
                    out += self.flow(t['steps'], main)
                else:
                    out.append(self.steps(t, main))
                for f in t['finals']:
                    out.append(self.daymark(f, main))
                    out.append(self.final(f))
                out += self.flow(t['tail'], main)
                out.append('</article>')
        return out


def changed_files(c, cwd):
    if not c['changed']:
        return ''
    rows = []
    for path, n, u in c['changed']:
        name = re.split(r'[\\/]', path)[-1]
        folder = path[:len(path) - len(name)].rstrip('\\/')
        same = folder.replace('\\', '/').lower() == cwd.replace('\\', '/').rstrip('/').lower()
        rows.append('<li><a href="#t-%s" title="%s"><b>%s</b>%s</a>%s</li>' % (
            u, esc(path), esc(name), '' if same or not folder else '<small>%s</small>' % esc(short_path(folder, cwd, 70)),
            '<small>×%d</small>' % n if n > 1 else ''))
    return '<details class="files"><summary>修改过 %d 个文件</summary><ul>%s</ul></details>' % (len(c['changed']), ''.join(rows))


VIEW = ('<div class="seg" id="view" title="完整：全部内容；对话：隐藏工具调用；结果：折起中间过程，只留每轮的最终答复">'
        '<button type="button" data-v="full">完整</button><button type="button" data-v="chat">对话</button>'
        '<button type="button" data-v="result">结果</button></div>')


def session_page(s, c, mode, parent=None, state='', back=None):
    """parent: (页面编号, 标题)，仅复刻的会话有。state: 内容指纹，页面据此发现新记录。
    back: (地址, 文字)，子代理页用它回到调用它的会话。"""
    r = Renderer(mode, s.cwd)
    body = r.conversation(c['items'])
    facts = ['<span class="proj" title="%s"><i style="background:hsl(%d 55%% 55%%)"></i>%s</span>' % (esc(s.cwd), hue(s.proj), esc(s.proj)),
             '<span>%s → %s</span>' % (fmt(c['first'], '%m-%d %H:%M'), fmt(c['last'], '%m-%d %H:%M')),
             '<span>%d 问</span><span>%d 答</span><span>%d 次工具调用</span>' % (c['n_user'], c['n_asst'], c['n_tools'])]
    if parent:
        facts.append('<span>复刻自 %s</span>' % (esc(parent[1]) if mode.standalone else '<a href="/s/%s">%s</a>' % (parent[0], esc(parent[1]))))
    if c['nfiles'] > 1:
        facts.append('<span>由 %d 份记录合并</span>' % c['nfiles'])
    if c['n_branch']:
        facts.append('<span>%d 处改写</span>' % c['n_branch'])
    more = '<button type="button" data-act="tools">展开全部工具调用</button>'
    if mode.standalone or back:
        attrs, search, app = '', '', ''
    else:
        attrs = ' data-state="/api/state?page=%s" data-sig="%s"' % (s.page, state)
        app = '' if s.orphan else '<a class="btn" href="claude://claude.ai/epitaxy/%s" title="在 Claude 桌面应用里打开这个会话">在应用中打开</a>' % esc(s.id)
        more += ('<a href="/export/%s.html">导出 HTML<small>单个文件，可离线打开</small></a>'
                 '<a href="/export/%s.html?images=1">导出 HTML（含截图）<small>文件可能很大</small></a>'
                 '<a href="/export/%s.md">导出 Markdown<small>只有对话文字</small></a>' % (s.page, s.page, s.page))
    if not mode.standalone:
        search = '<input id="fq" type="search" placeholder="搜索本会话…" title="空格分隔多个词；按 / 聚焦，Enter 下一处">'
    bar = ('<div class="bar">' + search + VIEW + '<span class="sp"></span>' + app
           + '<details class="menu"><summary class="btn">更多</summary><div>' + more + '</div></details>' + THEME_BUTTON + '</div>')
    if back:
        home = '<a class="back" href="%s">← %s</a>' % (back[0], esc(back[1]))
    else:
        home = '' if mode.standalone else '<a class="back" href="/">← 全部会话</a>'
    nav = (home + '<div class="jump"><button type="button" data-act="top">↑ 开头</button>'
           '<button type="button" data-act="end">↓ 最新</button></div>'
           '<div class="navhead">提问目录 · J / K 切换</div>' + ''.join(r.toc))
    # 拼接而不是 % 格式化：内嵌的样式和脚本里有 % 号
    return ''.join([head(c['title'], mode.standalone), '<body class="session"', attrs, '><div class="layout"><nav>', nav,
                    '</nav><main>', bar, '<header class="head"><h1>', esc(c['title']), '</h1><div class="facts">',
                    ''.join(facts), '</div>', changed_files(c, s.cwd), '</header>', '\n'.join(body),
                    '</main></div>', scripts(mode.standalone), '</body></html>'])

# ---------- 索引页 ----------


def index_row(s, c, depth, now):
    tags = ''
    if s.parent:
        tags += '<span class="badge">复刻</span>'
    if s.archived:
        tags += '<span class="badge">已归档</span>'
    if s.orphan:
        tags += '<span class="badge">不在应用列表中</span>'
    return ('<a class="row%s" href="/s/%s" data-page="%s" data-p="%s" data-t="%s" data-a="%s" style="--d:%d">'
            '<div class="r1"><span class="title">%s</span>%s<time title="%s">%s</time></div>'
            '<div class="r2">%s</div>'
            '<div class="r3"><span class="proj"><i style="background:hsl(%d 55%% 55%%)"></i>%s</span><span>%d 问</span><span>%d 答</span><span>%s</span></div></a>'
            % (' child' if depth else '', s.page, s.page, esc(s.proj), esc(c['title'].lower()), '1' if s.archived else '', min(depth, 3),
               esc(c['title']), tags, fmt(c['last']), when(c['last'], now),
               esc(preview(c['first_prompt'])) or '（没有文字提问）',
               hue(s.proj), esc(s.proj), c['n_user'], c['n_asst'], size(s.size)))


def index_page(entries, state=''):
    """entries: [(session, content, 层级, 所在家族的最后活动时间)]，复刻的会话紧跟在原会话后面。"""
    now = datetime.now().astimezone()
    out, last_bucket = [], None
    for s, c, depth, family_last in entries:
        b = bucket(family_last, now)
        if b != last_bucket:
            if last_bucket is not None:
                out.append('</section>')
            out.append('<section class="bucket"><h2>%s</h2>' % b)
            last_bucket = b
        out.append(index_row(s, c, depth, now))
    if last_bucket is not None:
        out.append('</section>')
    counts = collections.OrderedDict()          # 项目按最近活动排序，和列表一致
    for s, _, _, _ in entries:
        counts[s.proj] = counts.get(s.proj, 0) + 1
    tabs = '<button type="button" class="tab on" data-p=""><span>全部会话</span><small>%d</small></button>' % len(entries) + ''.join(
        '<button type="button" class="tab" data-p="%s"><i style="background:hsl(%d 55%% 55%%)"></i><span>%s</span><small>%d</small></button>'
        % (esc(p), hue(p), esc(p), n) for p, n in counts.items())
    total = sum(s.size for s, _, _, _ in entries)
    empty = '' if entries else '<p class="empty">还没有找到任何会话记录。</p>'
    return ''.join([
        head('Claude 会话记录', False), '<body class="index" data-state="/api/state" data-sig="', state, '"><div class="shell">',
        '<aside><a class="brand" href="/"><img src="/static/icon.svg" width="28" height="28" alt="">'
        '<span>Sessiontool<small>Claude 会话记录</small></span></a>',
        '<div class="side-h">项目</div><div class="tabs" id="pj">', tabs, '</div>',
        '<div class="side-h">选项</div>'
        '<label class="tg"><input type="checkbox" id="ar" checked> 显示已归档的会话</label>'
        '<label class="tg"><input type="checkbox" id="tl"> 搜索时包含工具调用与输出</label>',
        '<div class="side-foot"><span>%d 个会话 · %s</span>' % (len(entries), size(total)), THEME_BUTTON, '</div></aside>',
        '<main><div class="search"><input id="q" type="search" placeholder="搜索全部会话的对话内容，空格分隔多个词" autofocus>'
        '<kbd>/</kbd></div>',
        '<div class="meta" id="status">显示 <span id="cnt">%d</span> 个会话</div>' % len(entries),
        '<div id="hits"></div><div id="list">', empty, '\n'.join(out), '</div></main></div>', scripts(False), '</body></html>'])

# ---------- Markdown 导出 ----------


def session_markdown(s, c):
    out = ['# %s\n' % c['title'],
           '%s　·　%s → %s　·　你 %d 条 / Claude %d 段\n' % (s.cwd, fmt(c['first']), fmt(c['last']), c['n_user'], c['n_asst'])]

    def walk(items):
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
            elif k == 'sent':
                out.append('\n> 发给你的文件：%s%s\n' % ('、'.join(re.split(r'[\\/]', p)[-1] for p, _ in it['files']),
                                                    '（%s）' % it['caption'] if it['caption'] else ''))
            elif k == 'summary':
                out.append('\n<details><summary>上下文压缩摘要　%s</summary>\n\n%s\n\n</details>\n' % (fmt(it['ts']), it['text']))
            elif k == 'fork':
                out.append('\n---\n\n**以上来自原会话，从这里开始是复刻后的内容**\n')
            elif k == 'stop':
                out.append('\n*（你中断了这次回复）*\n')
            elif k == 'branch':
                out.append('\n<details><summary>改写前的旧分支</summary>\n')
                walk(it['items'])
                out.append('\n</details>\n')

    walk(c['items'])
    return ''.join(out)
