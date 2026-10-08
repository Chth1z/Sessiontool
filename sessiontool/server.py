"""本地网页服务。只监听 127.0.0.1，只读，不向外发送任何内容。"""
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__, render
from .details import load_image, load_local_image, load_tool
from .export import export_html, export_markdown, safe_name
from .index import Index
from .sessions import Catalog

CSP = ("default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'")
STATIC_TYPES = {'app.css': 'text/css; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8'}
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '[::1]')


class App:
    def __init__(self, sources):
        self.sources = sources
        self.index = Index(sources)
        self.catalog = Catalog(self.index)
        self.pages = {}

    def entries(self):
        cat = self.catalog
        out = [(s, cat.content(s), cat.content(s.parent)['title'] if s.parent else None) for s in cat.sessions]
        out.sort(key=lambda e: e[1]['last'], reverse=True)
        return out

    def session_html(self, s):
        c = self.catalog.content(s)
        hit = self.pages.get(s.id)
        if hit and hit[0] == c['sig']:
            return hit[1]
        parent = (s.parent.page, self.catalog.content(s.parent)['title']) if s.parent else None
        page = render.session_page(s, c, render.ServerMode(), parent)
        self.pages[s.id] = (c['sig'], page)
        return page


class Handler(BaseHTTPRequestHandler):
    server_version = 'Sessiontool/' + __version__
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def reply(self, body, ctype='text/html; charset=utf-8', status=200, cache='no-store', extra=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def reply_json(self, obj, status=200):
        self.reply(json.dumps(obj, ensure_ascii=False), 'application/json; charset=utf-8', status)

    def do_GET(self):
        # 只接受发往本机地址的请求，防止别的网站借 DNS 重绑定读取会话内容
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        if host not in LOCAL_HOSTS:
            return self.reply('Forbidden', 'text/plain; charset=utf-8', 403)
        try:
            self.route()
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception:
            traceback.print_exc()
            try:
                self.reply('内部错误，详情见运行窗口。', 'text/plain; charset=utf-8', 500)
            except OSError:
                pass

    def route(self):
        app = self.server.app
        url = urlsplit(self.path)
        path, qs = unquote(url.path), parse_qs(url.query)
        arg = lambda k: (qs.get(k) or [''])[0]
        if path == '/':
            app.catalog.refresh()
            return self.reply(render.index_page(app.entries()))
        if path.startswith('/s/'):
            app.catalog.refresh()
            s = app.catalog.by_page.get(path[3:])
            return self.reply(app.session_html(s)) if s else self.not_found()
        if path.startswith('/static/'):
            name = path[8:]
            if name in STATIC_TYPES:
                return self.reply(render.static_text(name), STATIC_TYPES[name])
            return self.not_found()
        if path == '/api/ping':
            return self.reply_json({'app': 'sessiontool', 'version': __version__})
        if path == '/api/search':
            q = arg('q').strip()
            if not q:
                return self.reply_json({'q': q, 'total': 0, 'sessions': []})
            groups = app.catalog.search(q, tools=arg('tools') == '1')
            return self.reply_json({'q': q, 'total': sum(g['n'] for g in groups), 'sessions': [
                {'page': g['session'].page, 'title': app.catalog.content(g['session'])['title'], 'n': g['n'],
                 'hits': [dict(h, time=render.fmt(h['ts'], '%m-%d %H:%M')) for h in g['hits']]} for g in groups]})
        if path == '/api/tool':
            d = load_tool(app.index, app.sources, arg('u'), arg('r') or None)
            d['images'] = ['/img/' + r for r in d['images']] + ['/local?p=' + quote(p, safe='') for p in d.pop('local_images')]
            return self.reply_json(d)
        if path.startswith('/img/'):
            got = load_image(app.index, path[5:])
            return self.reply(got[0], got[1], cache='private, max-age=31536000, immutable') if got else self.not_found()
        if path == '/local':
            got = load_local_image(app.sources, arg('p'))
            return self.reply(got[0], got[1], cache='private, max-age=86400') if got else self.not_found()
        if path.startswith('/export/'):
            page, _, ext = path[8:].rpartition('.')
            s = app.catalog.by_page.get(page)
            if not s or ext not in ('html', 'md'):
                return self.not_found()
            if ext == 'md':
                body, ctype = export_markdown(app.catalog, s), 'text/markdown; charset=utf-8'
            else:
                body, ctype = export_html(app.catalog, s, images=arg('images') == '1'), 'text/html; charset=utf-8'
            name = safe_name(app.catalog.content(s)['title'], s.page) + '.' + ext
            return self.reply(body, ctype, extra={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name)})
        return self.not_found()

    def not_found(self):
        self.reply('没有这个页面。', 'text/plain; charset=utf-8', 404)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False     # Windows 上地址复用会让两个进程同时占住一个端口
    daemon_threads = True


def make_server(app, port):
    httpd = Server(('127.0.0.1', port), Handler)
    httpd.app = app
    return httpd
