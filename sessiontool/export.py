"""把会话导出成单个文件：自带样式、可离线打开的 HTML，或纯文字的 Markdown。"""
import base64
import json
import os
import re

from . import render
from .details import load_image, load_local_image, load_sent_image, load_tool


class StandaloneMode:
    """导出用：工具详情直接写进页面，图片内嵌。"""
    standalone = True

    def __init__(self, index, sources, images=False, limit=20000):
        self.index, self.sources = index, sources
        self.images = images        # 是否内嵌工具截图（体积大）；你自己发的图片总是内嵌
        self.limit = limit

    def _uri(self, loaded):
        return 'data:%s;base64,%s' % (loaded[1], base64.b64encode(loaded[0]).decode('ascii')) if loaded else ''

    def image(self, ref):
        return self._uri(load_image(self.index, ref))

    def shot(self, ref):
        return self._uri(load_image(self.index, ref)) if self.images else ''

    def local(self, path):
        return self._uri(load_local_image(self.sources, path)) if self.images else ''

    def sent(self, ref, path):
        return self._uri(load_sent_image(self.index, ref)) if self.images else ''

    def agent(self, agent_id):
        return ''

    def tool_attrs(self, t):
        return ''

    def _cut(self, s):
        return s if len(s) <= self.limit else s[:self.limit] + '\n…（已截断，共 %d 字符）' % len(s)

    def tool_body(self, t):
        d = load_tool(self.index, self.sources, t['use'], t['res'])
        out = []
        inp = d['input']
        if isinstance(inp, dict):
            for k, v in inp.items():
                s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)
                if len(s) < 90 and '\n' not in s:
                    out.append('<div class="kv"><span class="k">%s</span><span class="v">%s</span></div>' % (render.esc(k), render.esc(s)))
                else:
                    out.append('<div class="k">%s</div><pre>%s</pre>' % (render.esc(k), render.esc(self._cut(s))))
        elif inp is not None:
            out.append('<pre>%s</pre>' % render.esc(self._cut(json.dumps(inp, ensure_ascii=False, indent=2))))
        text = d['full'] or d['result']
        if text:
            out.append('<div class="k">%s</div><pre class="%s">%s</pre>' % ('输出（失败）' if d['error'] else '输出',
                                                                           'err' if d['error'] else '', render.esc(self._cut(text))))
        # 截图在工具调用下方的缩略图里（带 --images 导出时），这里只说明没带的情况
        n = len(d['images']) + len(d['local_images'])
        if n and not self.images:
            out.append('<div class="k">（%d 张截图未导出，导出时加 --images 可包含）</div>' % n)
        return '<div class="tc">%s</div>' % ''.join(out)


def export_html(catalog, s, images=False):
    c = catalog.content(s)
    parent = (s.parent.page, catalog.content(s.parent)['title']) if s.parent else None
    return render.session_page(s, c, StandaloneMode(catalog.index, catalog.sources, images), parent, info=catalog.info(s))


def export_markdown(catalog, s):
    return render.session_markdown(s, catalog.content(s))


def safe_name(title, page):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', title).strip()[:60].strip(' .')
    return '%s_%s' % (name or '会话', page)


def export_to(catalog, s, folder, fmt='html', images=False):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, safe_name(catalog.content(s)['title'], s.page) + '.' + fmt)
    text = export_markdown(catalog, s) if fmt == 'md' else export_html(catalog, s, images)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path
