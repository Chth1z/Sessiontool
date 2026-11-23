"""极简 Markdown → HTML 渲染器（无第三方依赖，转义所有原始 HTML，防止 XSS）。"""
import html
import re

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
