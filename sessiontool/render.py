"""条目 → HTML / Markdown。

两种页面：服务模式（工具详情和图片按需向本地服务要），以及独立文件模式（导出用，所有内容内嵌）。
"""
import bisect
import collections
import html
import json
import os
import re
import zlib
from datetime import datetime
from urllib.parse import quote

from .pricing import model_name

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
            lang = re.sub(r'[^\w+#.-]', '', st[3:].strip().split(' ')[0])[:20]
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i])
                i += 1
            # 外面包一层，页面脚本在这层上放“复制”按钮；data-lang 用来显示语言
            out.append('<div class="code"%s><pre><code>%s</code></pre></div>'
                       % (' data-lang="%s"' % lang if lang else '', html.escape('\n'.join(buf))))
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


def num(n):
    """1234 → 1.2k，12345678 → 12.3M。"""
    for div, unit in ((1e9, 'B'), (1e6, 'M'), (1e3, 'k')):
        if n >= div:
            return ('%.1f' % (n / div)).rstrip('0').rstrip('.') + unit
    return str(n)


def money(x):
    """按 API 价格估算的美元数：$0.004、$1.23、$1,234。"""
    if x is None:
        return '—'
    if x >= 1000:
        return '$' + format(round(x), ',')
    return '$%.2f' % x if x >= 0.01 or not x else '$%.3f' % x


def acct_chip(a, cls='acct'):
    """账号的小标签：邮箱 @ 前面那段，悬停看完整邮箱。颜色由邮箱决定，同一个账号到处一个颜色。"""
    if not a:
        return ''
    tip = '账号：' + (a['email'] or a['name']) + ('\nmulti-claude 配置：' + a['profile'] if a.get('profile') else '')
    return '<span class="%s" style="--h:%d" title="%s"><i></i>%s</span>' % (cls, hue(a['email'] or a['key']), esc(tip), esc(a['name']))


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

# ---------- 图标 ----------

# 24×24 的线条图标，放进页面里的一张雪碧图；服务端和页面脚本都用 <use href="#i-名字"> 引用
ICONS = {
    'refresh': '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.6v.4"/>',
    'copy': '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5v-3a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/>',
    'check': '<path d="M5 12.5l4.5 4.5L19 7"/>',
    'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4l1.4-1.4M18 6l1.4-1.4"/>',
    'moon': '<path d="M20 14.2A8 8 0 0 1 9.8 4a7.5 7.5 0 1 0 10.2 10.2z"/>',
    'auto': '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor" stroke="none"/>',
    'more': '<path d="M5 12h.01M12 12h.01M19 12h.01" stroke-width="2.8"/>',
    'open': '<path d="M14 4h6v6"/><path d="M20 4l-8.5 8.5"/><path d="M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"/>',
    'x': '<path d="M6 6l12 12M18 6L6 18"/>',
    'up': '<path d="M12 19V5M6 11l6-6 6 6"/>',
    'down': '<path d="M12 5v14M6 13l6 6 6-6"/>',
    'left': '<path d="M15 5l-7 7 7 7"/>',
    'right': '<path d="M9 5l7 7-7 7"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    'keys': '<rect x="3" y="6" width="18" height="12" rx="2.5"/><path d="M7 10h.01M11 10h.01M15 10h.01M8 14h8" stroke-width="2.2"/>',
    'list': '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" stroke-width="2"/>',
    'chart': '<path d="M4 20h16"/><path d="M7 16v-5M12 16V6M17 16v-8"/>',
    'table': '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 10h17M3.5 15h17M10 10v9.5"/>',
    'sort': '<path d="M7 4v16M7 20l-3.5-3.5M7 20l3.5-3.5M17 20V4M17 4l-3.5 3.5M17 4l3.5 3.5"/>',
    'chev': '<path d="M6 9l6 6 6-6"/>',
}
SPRITE = ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none">'
          + ''.join('<symbol id="i-%s" viewBox="0 0 24 24">%s</symbol>' % kv for kv in ICONS.items()) + '</svg>')


def icon(name):
    return '<svg class="ic" aria-hidden="true"><use href="#i-%s"/></svg>' % name


def ibutton(name, title, attrs=''):
    """只有图标的按钮；文字说明放在 title 和 aria-label 里。"""
    return '<button type="button" class="ib" title="%s" aria-label="%s"%s>%s</button>' % (title, title, attrs, icon(name))


THEME_BUTTON = '<button type="button" class="ib" id="theme" title="切换浅色 / 深色 / 跟随系统" aria-label="切换主题"></button>'
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
MINOR = ('stop', 'auto', 'notice', 'note', 'compact', 'cmd', 'summary', 'think')


def keyed(block):
    """给顶层的块打上内容指纹 → (块, 指纹)。页面更新时只替换指纹变了的块，其余块的展开状态和已加载的内容都不动。"""
    k = '%08x' % (zlib.crc32(block.encode('utf-8')) & 0xffffffff)
    return block.replace('>', ' data-k="%s">' % k, 1), k


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
    def __init__(self, mode, cwd='', codex=False, spend=None):
        self.mode = mode
        self.cwd = cwd
        self.who = ('Codex', 'X', ' cx') if codex else ('Claude', 'C', '')     # 答复的署名、头像上的字、样式
        self.spend = spend or []            # [(时间, 费用, 输出 token)]，按时间排好
        self.stamps = [x[0] for x in self.spend]
        self.ids = set()
        self.toc = []
        self.keys = []                      # 顶层各块的内容指纹，和块一一对应
        self.day = None

    def cost(self, start, end):
        """[start, end) 之间各次回复的费用合计；这段时间没有这个会话自己的用量时为 None。"""
        if not self.stamps or not start:
            return None
        i = bisect.bisect_left(self.stamps, start)
        j = bisect.bisect_left(self.stamps, end) if end else len(self.stamps)
        return sum(x[1] for x in self.spend[i:j]) if j > i else None

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
        num = '<a class="num" href="#m-%s" title="这条提问的链接">#%d</a>' % (it['u'], it['n']) if it.get('n') else ''
        tag = '<span class="badge">回复进行中追加</span>' if it.get('queued') else ''
        if main and it.get('n') and anchor:
            self.toc.append('<a href="#m-%s" title="%s"><b>%d</b><span>%s</span></a>' % (
                it['u'], esc(fmt(it['ts']) + '\n' + it['text'][:300]), it['n'], esc(preview(it['text'])[:60] or '（图片）')))
        body = '<div class="body">%s</div>' % md(it['text']) if it['text'] else ''
        return ('<section class="msg user"%s><div class="av">你</div><div class="mc"><header><b>你</b>%s%s%s'
                '<button type="button" class="copy">复制</button></header>%s%s</div></section>'
                % (anchor, self.stamp(it['ts']), num, tag, body, self.pics(self.mode.image(r) for r in it['imgs'])))

    def final(self, it, cost=None):
        spent = '<span class="spent" title="这一轮的用量按 API 价格估算">%s</span>' % money(cost) if cost else ''
        return ('<section class="msg asst%s"%s><div class="av">%s</div><div class="mc"><header><b>%s</b>%s%s'
                '<button type="button" class="copy">复制</button></header><div class="body">%s</div></div></section>'
                % (self.who[2], self.anchor('m-', it['u']), self.who[1], self.who[0], self.stamp(it['ts']), spent, md(it['text'])))

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
            return '<details class="fold think" open><summary>思考过程</summary><div class="body">%s</div></details>' % md(it['text'])
        if k == 'summary':
            return ('<details class="fold"%s><summary>上下文压缩摘要 · %s</summary><div class="body">%s</div></details>'
                    % (self.anchor('m-', it['u']), fmt(it['ts'], '%H:%M'), md(it['text'])))
        if k == 'compact':
            how = {'auto': '自动', 'manual': '手动'}.get(it['trigger'], '')
            size = '（%s → %s tokens）' % (tokens(it['pre']), tokens(it['post'])) if it.get('pre') else ''
            return self.line('上下文已%s压缩%s' % (how, size), it['ts'])
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

    def steps(self, t, main, cost=None):
        """中间过程：可以整块折起来，只留最终答复。cost 是这一轮的费用估算。"""
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
        if cost:
            parts.append(money(cost))
        if not t['finals']:
            parts.append('这一轮没有最终答复')
        # 过程长的时候，读到底部也给一个折起的入口，不用滚回去找开头那一行
        fold = '<button type="button" class="fold-up" data-act="fold">收起这段过程</button>' if len(t['steps']) >= 5 else ''
        return ('<details class="steps" open><summary title="点击折起或展开这一轮的中间过程"><b>过程</b><span>%s</span></summary>'
                '<div class="rail">%s%s</div></details>' % (' · '.join(parts), ''.join(self.flow(t['steps'], main)), fold))

    def conversation(self, items, main=True):
        """→ 顶层块的列表：日期分隔、一轮对话、复刻点、旧分支。主对话里的块带内容指纹（记在 self.keys）。"""
        out = []

        def emit(block):
            if block:
                if main:
                    block, k = keyed(block)
                    self.keys.append(k)
                out.append(block)

        turns = split_turns(items)
        # 每一轮从你的提问开始，到下一轮的提问为止；这段时间里的回复用量算这一轮的
        starts = [None if t.get('mark') else (t['prompt'] or (t['steps'] + t['finals'] + t['tail'])[0]).get('ts') for t in turns]
        for i, t in enumerate(turns):
            mark = t.get('mark')
            if mark and mark['kind'] == 'fork':
                emit('<div class="forkline"><span>以上来自原会话 · 从这里开始是复刻后的内容</span></div>')
                self.toc.append('<div class="d fk">复刻点</div>')
            elif mark:
                n = sum(1 for x in mark['items'] if x['kind'] in ('user', 'asst'))
                emit('<details class="fold branch"><summary>改写前的旧分支（%d 条消息，应用里已不显示）· %s</summary>%s</details>'
                     % (n, fmt(mark['ts'], '%H:%M'), ''.join(self.conversation(mark['items'], main=False))))
            else:
                cost = self.cost(starts[i], next((x for x in starts[i + 1:] if x), None)) if main else None
                emit(self.daymark(t['prompt'] or (t['steps'] + t['finals'] + t['tail'])[0], main))
                parts = [self.user(t['prompt'], main)] if t['prompt'] else []
                parts += self.flow(t['steps'], main) if t['plain'] else [self.steps(t, main, cost)]
                for k, f in enumerate(t['finals']):
                    last = t['plain'] and k == len(t['finals']) - 1     # 没有过程可折的一轮，费用写在答复上
                    parts += [self.daymark(f, main), self.final(f, cost if last else None)]
                parts += self.flow(t['tail'], main)
                emit('<article class="turn">%s</article>' % ''.join(parts))
        return out


def changed_files(c, cwd):
    if not c.get('changed'):
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


VIEW = ('<div class="seg" id="view" title="完整：全部内容（默认展开思考）；对话：隐藏工具调用和思考过程；'
        '结果：隐藏中间过程，只看提问与最终答复（按 1 / 2 / 3 切换）">'
        '<button type="button" data-v="full">完整</button>'
        '<button type="button" data-v="chat">对话</button><button type="button" data-v="result">结果</button></div>')
LIVE = ('<button type="button" class="live" data-act="live" title="实时更新：有新记录时自动显示，不用刷新页面（点击暂停或继续）">'
        '<i></i><span>实时</span></button>')


def embed(name, data):
    """把数据放进页面，供页面脚本读取（导出的独立文件也靠它，不需要服务）。"""
    return '<script type="application/json" id="%s">%s</script>' % (name, json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))


def cost_text(u):
    """会话或分组的费用：价格未知的模型不计入，有这种情况时金额后面加个 +。"""
    if u['cost']:
        return money(u['cost']) + ('+' if u['unpriced'] else '')
    return '价格未知' if u['unpriced'] else money(0)


def usage_tip(u):
    rate = '，缓存命中 %.1f%%' % (u['rate'] * 100) if u.get('rate') is not None else ''
    return '按 API 价格估算：%d 次回复，%s tokens%s。订阅不按 token 计费，这是同样的用量按 API 计价的金额。' % (
        u['n'], num(u['tokens']), rate)


def session_view(s, c, mode, parent=None, state='', back=None, info=None):
    """会话页的各部分，整页由 session_html 拼起来。服务把变了的块单独发给已经打开的页面，所以分开存放。

    parent: (页面编号, 标题)，仅复刻的会话有。state: 内容指纹，页面据此实时更新。
    back: (地址, 文字)，子代理页用它回到调用它的会话。info: 详情面板的数据。"""
    codex = getattr(s, 'src', '') == 'codex'
    r = Renderer(mode, s.cwd, codex, None if back else c.get('spend'))
    blocks = r.conversation(c['items'])
    live = not mode.standalone and not back         # 有本地服务可问、并且是一个真正的会话
    info = info or {}
    ident = info.get('id') or info.get('cli')
    facts = []
    if ident:
        facts.append('<button type="button" class="idchip" data-copy="%s" data-copied="会话 ID" title="点击复制完整的会话 ID：%s">'
                     '<span>ID</span><code>%s</code>%s</button>' % (esc(ident), esc(ident), esc(s.page or ident[:8]), icon('copy')))
    facts.append('<span>%s → %s</span>' % (fmt(c['first'], '%m-%d %H:%M'), fmt(c['last'], '%m-%d %H:%M')))
    facts.append('<span>%d 问</span><span>%d 答</span><span>%d 次工具调用</span>' % (c['n_user'], c['n_asst'], c['n_tools']))
    if c['nfiles'] > 1:
        facts.append('<span>由 %d 份记录合并</span>' % c['nfiles'])
    if c.get('n_branch'):
        facts.append('<span>%d 处改写</span>' % c['n_branch'])
    if getattr(s, 'model', ''):
        facts.append('<span>%s%s</span>' % (esc(model_name(s.model)), ' · ' + esc(s.effort) if s.effort else ''))
    u = c.get('usage')
    if u and u['n'] and not back:
        facts.append('<span class="spent" title="%s">%s</span>' % (esc(usage_tip(u)), cost_text(u)))
    if info:
        facts.append('<button type="button" class="linkish" data-act="info">详情</button>')
    crumbs = '<span class="proj" title="%s"><i style="background:hsl(%d 55%% 55%%)"></i>%s</span>' % (esc(s.cwd), hue(s.proj), esc(s.proj))
    crumbs += acct_chip(info.get('account'))
    if codex:
        crumbs += '<span class="badge cx">Codex</span>'
    if parent:
        crumbs += '<span class="badge">复刻自 %s</span>' % (
            esc(parent[1]) if mode.standalone else '<a href="/s/%s">%s</a>' % (parent[0], esc(parent[1])))
    if getattr(s, 'archived', False):
        crumbs += '<span class="badge">已归档</span>'

    more = '<button type="button" data-act="tools">展开全部工具调用</button>'
    tools = ''
    if info:
        tools += ibutton('info', '会话详情（I）', ' data-act="info"')
    if live:
        tools = LIVE + ibutton('refresh', '立刻重读磁盘（R）', ' data-act="refresh"') + tools
        if info.get('link'):
            tools += ('<a class="ib" href="%s" title="在 Claude 应用中打开这个会话（有多个 Claude 时由系统默认的那个打开）" '
                      'aria-label="在 Claude 应用中打开">%s</a>' % (esc(info['link']), icon('open')))
        more += ('<a href="/export/%s.html">导出 HTML<small>单个文件，可离线打开</small></a>'
                 '<a href="/export/%s.html?images=1">导出 HTML（含截图）<small>文件可能很大</small></a>'
                 '<a href="/export/%s.md">导出 Markdown<small>只有对话文字</small></a>' % (s.page, s.page, s.page))
    more += '<button type="button" data-act="keys">键盘快捷键<small>按 ? 也可以打开</small></button>'
    search = ''
    if not mode.standalone:
        search = ('<label class="find-in">%s<input id="fq" type="search" placeholder="搜索本会话…" '
                  'title="空格分隔多个词；按 / 聚焦，Enter 下一处，Shift+Enter 上一处"></label>' % icon('search'))
    bar = ('<div class="bar">' + search + VIEW + '<span class="sp"></span>' + tools
           + '<details class="menu"><summary class="ib" title="更多" aria-label="更多">' + icon('more') + '</summary><div>' + more
           + '</div></details>' + THEME_BUTTON + '</div>')
    if back:
        home = '<a class="back" href="%s">%s%s</a>' % (back[0], icon('left'), esc(back[1]))
    else:
        home = '' if mode.standalone else '<a class="back" href="/">%s全部会话</a>' % icon('left')
    toc = ''.join(r.toc)
    nav = ('<div class="nav-top">' + home + '<div class="navhead"><span>提问目录</span>'
           '<button type="button" class="toc-sort" data-act="tocsort" title="切换提问目录顺序">'
           '%s<span>正序</span></button></div></div><div class="toc">' % icon('sort') + toc + '</div>')
    attrs = ' data-page="%s" data-state="/api/state?page=%s" data-sig="%s"' % (s.page, s.page, state) if live else ''
    if codex:
        attrs += ' data-src="codex"'
    head_html = ''.join(['<header class="head"><div class="crumbs">', crumbs, '</div><h1>', esc(c['title']), '</h1><div class="facts">',
                         ''.join(facts), '</div>', changed_files(c, s.cwd), '</header>'])
    # 拼接而不是 % 格式化：内嵌的样式和脚本里有 % 号
    top = ''.join([head(c['title'], mode.standalone), '<body class="session"', attrs, '>', SPRITE,
                   '<div class="progress"></div><div class="layout"><nav>', nav, '</nav><main><div class="page">', bar])
    return {'title': c['title'], 'sig': state, 'top': top, 'head': head_html, 'toc': toc, 'blocks': blocks, 'keys': r.keys,
            'info': info or None, 'standalone': mode.standalone}


def session_html(v):
    return ''.join([v['top'], v['head'], '<div id="flow">', '\n'.join(v['blocks']), '</div></div></main></div>',
                    embed('info', v['info']) if v['info'] else '', scripts(v['standalone']), '</body></html>'])


def session_page(s, c, mode, parent=None, state='', back=None, info=None):
    return session_html(session_view(s, c, mode, parent, state, back, info))

# ---------- 索引页、统计页 ----------


def sidebar(counts, page):
    """左边栏顶部：标识与右上角 会话/统计 滑块；来源切换（Claude / Codex 并列 + 独立的小“全部”按钮）。"""
    srcs = ''
    if counts.get('codex'):
        srcs = ('<div class="src-row" id="src">'
                '<div class="seg srcs" title="在 Claude 与 Codex 之间切换（按 S 循环切换）">'
                '<button type="button" data-s="claude">Claude<small>%d</small></button>'
                '<button type="button" data-s="codex">Codex<small>%d</small></button></div>'
                '<button type="button" class="src-all" data-s="all" title="同时显示 Claude 和 Codex">全部</button></div>'
                % (counts.get('claude', 0), counts['codex']))
    on = lambda p: ' class="on" aria-current="page"' if p == page else ''
    return ('<div class="side-top"><a class="brand" href="/"><img src="/static/icon.svg" width="26" height="26" alt="">'
            '<span>Sessiontool</span></a>'
            '<nav class="modes" data-page="%s" aria-label="页面">'
            '<a href="/"%s>会话</a><a href="/stats"%s>统计</a></nav></div>' % (page, on('list'), on('stats')) + srcs)


def index_row(s, c, depth, now, i, accounts):
    tags = ''
    if s.src == 'codex':
        tags += '<span class="badge cx srcb">Codex</span>'
    if s.parent:
        tags += '<span class="badge">复刻</span>'
    if s.archived:
        tags += '<span class="badge">已归档</span>'
    if s.orphan:
        tags += '<span class="badge">不在应用列表中</span>'
    first, recent = preview(c['first_prompt']), preview(c['last_prompt'])
    if c['n_user'] > 1 and recent and recent != first:      # 聊了不止一轮：显示最近在做什么，比重复开头有用
        sub = '<span class="lbl">最近</span>' + esc(recent)
    else:
        sub = esc(first) or '（没有文字提问）'
    ident = s.cli_ids[-1] if getattr(s, 'unlisted', False) or s.orphan or s.src == 'codex' else s.id
    acts = ('<button type="button" class="ib sm" data-copy="%s" data-copied="会话 ID" title="复制会话 ID" aria-label="复制会话 ID">%s</button>'
            '<button type="button" class="ib sm" data-act="info" title="详情" aria-label="详情">%s</button>'
            % (esc(ident), icon('copy'), icon('info')))
    u = c.get('usage') or {}
    spent = '<span class="spent" title="%s">%s</span>' % (esc(usage_tip(u)), cost_text(u)) if u.get('n') else ''
    return ('<div class="row%s" data-page="%s" data-p="%s" data-t="%s" data-a="%s" data-src="%s" data-acct="%s" '
            'style="--d:%d;--i:%d;--c:hsl(%d 55%% 55%%)">'
            '<a class="cover" href="/s/%s" aria-label="%s"></a>'
            '<div class="r1"><span class="title">%s</span>%s%s<time title="%s">%s</time></div>'
            '<div class="r2">%s</div>'
            '<div class="r3"><span class="proj"><i></i>%s</span><span>%d 问</span><span>%d 答</span>%s<span>%s</span>'
            '<span class="acts">%s</span></div></div>'
            % (' child' if depth else '', s.page, esc(s.proj), esc(c['title'].lower()), '1' if s.archived else '', s.src,
               esc(s.account), min(depth, 3), min(i, 16), hue(s.proj), s.page, esc(c['title']),
               esc(c['title']), acct_chip(accounts.get(s.account)), tags, fmt(c['last']), when(c['last'], now), sub,
               esc(s.proj), c['n_user'], c['n_asst'], spent, size(s.size), acts))


def index_page(entries, state='', accounts=None):
    """entries: [(session, content, 层级, 所在家族的最后活动时间)]，复刻的会话紧跟在原会话后面。"""
    accounts = accounts or {}
    now = datetime.now().astimezone()
    out, last_bucket = [], None
    for i, (s, c, depth, family_last) in enumerate(entries):
        b = bucket(family_last, now)
        if b != last_bucket:
            if last_bucket is not None:
                out.append('</section>')
            out.append('<section class="bucket"><h2>%s</h2>' % b)
            last_bucket = b
        out.append(index_row(s, c, depth, now, i, accounts))
    if last_bucket is not None:
        out.append('</section>')
    # 项目按最近活动排序，和列表一致；各来源分别计数，切换来源时页面脚本据此显示
    projects, people = collections.OrderedDict(), collections.OrderedDict()
    for s, _, _, _ in entries:
        projects.setdefault(s.proj, collections.Counter())[s.src] += 1
        if s.account:
            people.setdefault(s.account, collections.Counter())[s.src] += 1
    tabs = ('<button type="button" class="tab on" data-p="" data-c="%d" data-x="%d"><span>全部会话</span><small></small></button>'
            % (sum(n['claude'] for n in projects.values()), sum(n['codex'] for n in projects.values()))) + ''.join(
        '<button type="button" class="tab" data-p="%s" data-c="%d" data-x="%d"><i style="background:hsl(%d 55%% 55%%)"></i>'
        '<span>%s</span><small></small></button>' % (esc(p), n['claude'], n['codex'], hue(p), esc(p)) for p, n in projects.items())
    counts = collections.Counter(s.src for s, _, _, _ in entries)
    acct_box = ''
    if people:
        acct_opts = ('<button type="button" class="tab on" data-acct="" data-c="%d" data-x="%d">'
                     '<span>全部账号</span><small></small></button>' % (counts['claude'], counts['codex'])) + ''.join(
            '<button type="button" class="tab" data-acct="%s" data-c="%d" data-x="%d" title="%s">'
            '<i style="background:hsl(%d 55%% 55%%)"></i><span>%s</span><small></small></button>'
            % (esc(k), n['claude'], n['codex'], esc((accounts.get(k) or {}).get('email') or k),
               hue((accounts.get(k) or {}).get('email') or k), esc((accounts.get(k) or {}).get('name') or k[:8]))
            for k, n in people.items())
        acct_box = ('<div class="side-acct"><div class="side-h">账号</div><details class="menu acct-dd" id="ac">'
                    '<summary title="按账号筛选会话">'
                    '<span class="ac-cur"><i id="ac-dot" hidden></i><span id="ac-name">全部账号</span></span>'
                    '<small id="ac-cnt"></small>%s</summary>'
                    '<div>%s</div></details></div>' % (icon('chev'), acct_opts))
    total = sum(s.size for s, _, _, _ in entries)
    empty = '' if entries else '<p class="empty">还没有找到任何会话记录。</p>'
    return ''.join([
        head('会话记录 · Sessiontool', False), '<body class="index" data-state="/api/state" data-sig="', state, '">', SPRITE,
        '<div class="shell"><aside><div class="side-head">', sidebar(counts, 'list'), acct_box, '</div>',
        '<div class="side-scroll" id="side-scroll"><div class="side-h">项目</div><div class="tabs" id="pj">', tabs, '</div></div>',
        '<div class="side-bottom"><div class="side-opts"><div class="side-h">选项</div>'
        '<label class="tg"><input type="checkbox" id="ar" checked> 显示已归档的会话</label>'
        '<label class="tg"><input type="checkbox" id="tl"> 搜索时包含工具调用与输出</label></div>',
        '<div class="side-foot"><span id="totals">%d 个会话 · %s</span><span class="foot-acts">' % (len(entries), size(total)),
        ibutton('keys', '键盘快捷键（?）', ' data-act="keys"'), THEME_BUTTON, '</span></div></div></aside>',
        '<main><div class="page"><div class="top"><div class="search"><input id="q" type="search" placeholder="搜索全部会话的对话内容，空格分隔多个词">'
        '<kbd>/</kbd></div>', ibutton('refresh', '立刻重读磁盘（R）', ' data-act="refresh"'), '</div>',
        '<div class="meta" id="status"><span id="cnt">%d</span> 个会话 · 更新于 <time id="synced">%s</time>%s</div>'
        % (len(entries), now.strftime('%H:%M:%S'), LIVE),
        '<div id="hits"></div><div id="list">', empty, '\n'.join(out), '</div></div></main></div>', scripts(False), '</body></html>'])


def stats_page(sessions, state=''):
    """统计页的骨架：筛选条件在服务端只给出选项，数字和图都由页面脚本向 /api/stats 要来再画。"""
    counts = collections.Counter(s.src for s in sessions)
    ranges = ''.join('<button type="button" data-d="%d">%s</button>' % (d, label)
                     for d, label in ((7, '7 天'), (30, '30 天'), (90, '90 天'), (0, '全部')))
    acct_dd = ('<div class="pick"><span>账号</span><details class="menu acct-dd" id="acct">'
               '<summary title="按账号筛选统计"><span class="ac-cur"><i id="acct-dot" hidden></i>'
               '<span id="acct-name">全部账号</span></span>' + icon('chev') + '</summary>'
               '<div></div></details></div>')
    return ''.join([
        head('统计 · Sessiontool', False), '<body class="stats" data-state="/api/state" data-sig="', state, '">', SPRITE,
        '<div class="shell"><aside><div class="side-head">', sidebar(counts, 'stats'), '</div>',
        '<div class="side-scroll"><div class="side-digest" id="digest"><div class="shimmer"></div></div></div>',
        '<div class="side-bottom"><div class="side-foot">'
        '<span title="订阅用户实际不按 token 付费；无价格的模型可在 ~/.sessiontool/prices.json 补充">按 API 价格估算</span>'
        '<span class="foot-acts">', ibutton('keys', '键盘快捷键（?）', ' data-act="keys"'), THEME_BUTTON,
        '</span></div></div></aside>',
        '<main><div class="page"><div class="st-top"><h1>统计</h1>', LIVE, '</div>'
        '<div class="filters"><div class="seg" id="range" title="时间范围">', ranges, '</div>', acct_dd,
        '<span class="sp"></span><span class="meta" id="span"></span></div>'
        '<div id="st" class="st"><div class="shimmer"></div></div></div></main></div>', scripts(False), '</body></html>'])

# ---------- Markdown 导出 ----------


def session_markdown(s, c):
    who = 'Codex' if getattr(s, 'src', '') == 'codex' else 'Claude'
    out = ['# %s\n' % c['title'],
           '%s　·　%s → %s　·　你 %d 条 / %s %d 段\n' % (s.cwd, fmt(c['first']), fmt(c['last']), c['n_user'], who, c['n_asst'])]

    def walk(items):
        for it in items:
            k = it['kind']
            if k == 'user':
                out.append('\n---\n\n## 你 %s　%s\n\n%s\n' % ('#%d' % it['n'] if it.get('n') else '', fmt(it['ts']), it['text']))
                if it['imgs']:
                    out.append('（附图 %d 张，未收录）\n' % len(it['imgs']))
            elif k == 'asst':
                out.append('\n### %s　%s\n\n%s\n' % (who, fmt(it['ts']), it['text']))
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
