"""本地网页服务。只监听 127.0.0.1，只读，不向外发送任何内容。

实时更新：后台线程每秒和磁盘同步一次；页面开着一条事件流（Server-Sent Events），有新记录时服务告诉它，
它再只取变了的那部分换上，不用刷新整页。
"""
import collections
import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__, render, stats
from .details import load_image, load_local_image, load_sent_image, load_tool
from .export import export_html, export_markdown, safe_name
from .index import Index
from .sessions import Catalog, Session

CSP = ("default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'")
STATIC_TYPES = {'app.css': 'text/css; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8',
                'theme.js': 'text/javascript; charset=utf-8', 'icon.svg': 'image/svg+xml'}
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '[::1]')
RANGES = (0, 7, 30, 90, 365)


class App:
    def __init__(self, sources):
        self.sources = sources
        self.index = Index(sources)
        self.catalog = Catalog(self.index)
        self.pages, self.figures = {}, {}
        self.version = 0                    # 每发现一次变化加一，等着的事件流据此醒来
        self.cond = threading.Condition()

    def refresh(self, force=False):
        if self.catalog.refresh(force=force):
            with self.cond:
                self.version += 1
                self.cond.notify_all()

    def watch(self, interval=1.0):
        """后台线程：隔一会儿和磁盘同步一次。"""
        while True:
            try:
                self.refresh(force=True)
            except Exception:
                traceback.print_exc()
            time.sleep(interval)

    def wait(self, version, timeout):
        """等到有变化（或超时），返回当前的变化序号。"""
        with self.cond:
            self.cond.wait_for(lambda: self.version != version, timeout)
            return self.version

    def entries(self):
        """[(会话, 内容, 层级, 家族最后活动时间)]：按家族最后活动倒序，复刻的会话紧跟在原会话后面。"""
        cat = self.catalog
        info = {s.id: cat.content(s) for s in cat.sessions}
        kids, roots = collections.defaultdict(list), []
        for s in cat.sessions:
            (kids[s.parent.id] if s.parent else roots).append(s)
        latest = {}

        def family_last(s, seen=()):
            if s.id not in latest:
                latest[s.id] = max([info[s.id]['last']] + [family_last(k, seen + (s.id,)) for k in kids[s.id] if k.id not in seen])
            return latest[s.id]

        out, done = [], set()

        def walk(s, depth, stamp):
            if s.id in done:
                return
            done.add(s.id)
            out.append((s, info[s.id], depth, stamp))
            for k in sorted(kids[s.id], key=family_last, reverse=True):
                walk(k, depth + 1, stamp)

        for s in sorted(roots, key=family_last, reverse=True):
            walk(s, 0, family_last(s))
        for s in cat.sessions:          # 复刻关系成环时兜底，不让任何会话从列表里消失
            walk(s, 0, info[s.id]['last'])
        return out

    def index_html(self):
        cat = self.catalog
        return render.index_page(self.entries(), cat.state(), cat.accounts)

    def view(self, s):
        """会话页的各部分（标题区、对话的各块、目录、详情），按内容指纹和详情缓存。"""
        cat = self.catalog
        info = cat.info(s)
        # 页面里还有标题、复刻关系、账号这些来自应用清单的信息，所以缓存要连它们一起比
        key = (cat.state(s), json.dumps(info, sort_keys=True, ensure_ascii=False))
        hit = self.pages.get(s.id)
        if hit and hit[0] == key:
            return hit[1]
        parent = (s.parent.page, cat.content(s.parent)['title']) if s.parent else None
        v = render.session_view(s, cat.content(s), render.ServerMode(cat.agents), parent, cat.state(s), info=info)
        self.pages[s.id] = (key, v)
        return v

    def session_html(self, s):
        return render.session_html(self.view(s))

    def figures_for(self, src, account, days):
        """统计页的数据，按内容指纹和筛选条件缓存。"""
        key = (self.catalog.state(), src, account, days, time.strftime('%Y-%m-%d'))
        hit = self.figures.get((src, account, days))
        if hit and hit[0] == key:
            return hit[1]
        data = stats.compute(self.catalog, src, account, days)
        self.figures[(src, account, days)] = (key, data)
        return data


class Handler(BaseHTTPRequestHandler):
    server_version = 'Sessiontool/' + __version__
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def finish(self):
        # 每个连接一个线程，线程各有自己的数据库连接；连接结束时顺手关掉，不等垃圾回收
        try:
            super().finish()
        finally:
            app = getattr(self.server, 'app', None)
            if app:
                app.index.close()

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

    def handle_safely(self, route):
        # 只接受发往本机地址的请求，防止别的网站借 DNS 重绑定读取会话内容
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        if host not in LOCAL_HOSTS:
            return self.reply('Forbidden', 'text/plain; charset=utf-8', 403)
        try:
            route()
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception:
            traceback.print_exc()
            try:
                self.reply('内部错误，详情见运行窗口。', 'text/plain; charset=utf-8', 500)
            except OSError:
                pass

    def do_GET(self):
        self.handle_safely(self.route)

    def do_POST(self):
        self.handle_safely(self.route_post)

    def route(self):
        app = self.server.app
        url = urlsplit(self.path)
        path, qs = unquote(url.path), parse_qs(url.query)
        arg = lambda k: (qs.get(k) or [''])[0]
        fresh = arg('fresh') == '1'         # 刷新按钮：跳过两秒内不重复同步的节流，立刻重读磁盘
        if path == '/':
            app.refresh(force=fresh)
            return self.reply(app.index_html())
        if path.startswith('/s/'):
            app.refresh(force=fresh)
            s = app.catalog.by_page.get(path[3:])
            return self.reply(app.session_html(s)) if s else self.not_found()
        if path == '/stats':
            app.refresh(force=fresh)
            return self.reply(render.stats_page(app.catalog.sessions, app.catalog.state()))
        if path == '/api/stats':
            app.refresh(force=fresh)
            days = int(arg('days')) if arg('days').isdigit() and int(arg('days')) in RANGES else 0
            src = arg('src') if arg('src') in ('claude', 'codex') else ''
            return self.reply_json(app.figures_for(src, arg('account'), days))
        if path == '/api/live':
            return self.live(arg('page'))
        if path == '/api/info':
            s = app.catalog.by_page.get(arg('page'))
            return self.reply_json(app.catalog.info(s)) if s else self.not_found()
        if path.startswith('/static/'):
            name = path[8:]
            if name in STATIC_TYPES:
                return self.reply(render.static_text(name), STATIC_TYPES[name])
            return self.not_found()
        if path == '/api/ping':
            return self.reply_json({'app': 'sessiontool', 'version': __version__})
        if path == '/api/state':
            app.refresh()
            s = app.catalog.by_page.get(arg('page')) if arg('page') else None
            return self.reply_json({'sig': app.catalog.state(s)})
        if path == '/api/search':
            q = arg('q').strip()
            src = arg('src') if arg('src') in ('claude', 'codex') else None
            if not q:
                return self.reply_json({'q': q, 'total': 0, 'sessions': []})
            groups = app.catalog.search(q, tools=arg('tools') == '1', src=src)
            return self.reply_json({'q': q, 'total': sum(g['n'] for g in groups), 'sessions': [
                {'page': g['session'].page, 'src': g['session'].src, 'title': app.catalog.content(g['session'])['title'],
                 'n': g['n'], 'hits': [dict(h, time=render.fmt(h['ts'], '%m-%d %H:%M')) for h in g['hits']]} for g in groups]})
        if path == '/api/tool':
            d = load_tool(app.index, app.sources, arg('u'), arg('r') or None)
            d['images'] = ['/img/' + r for r in d['images']] + ['/local?p=' + quote(p, safe='') for p in d.pop('local_images')]
            return self.reply_json(d)
        if path.startswith('/img/'):
            got = load_image(app.index, path[5:])
            return self.reply(got[0], got[1], cache='private, max-age=31536000, immutable') if got else self.not_found()
        if path.startswith('/sent/'):
            got = load_sent_image(app.index, path[6:])
            return self.reply(got[0], got[1], cache='private, max-age=3600') if got else self.not_found()
        if path.startswith('/agent/'):
            app.refresh()
            agent_id = path[7:]
            c = app.catalog.agent_content(agent_id)
            if not c:
                return self.not_found()
            owner = app.catalog.agent_owner(agent_id)
            back = ('/s/' + owner.page, '回到会话') if owner else ('/', '全部会话')
            pseudo = Session(id='agent:' + agent_id, page='', cwd=owner.cwd if owner else '', proj=owner.proj if owner else '子代理',
                             orphan=True)
            return self.reply(render.session_page(pseudo, c, render.ServerMode(app.catalog.agents), back=back))
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

    def route_post(self):
        app = self.server.app
        url = urlsplit(self.path)
        if url.path != '/api/blocks':
            return self.not_found()
        app.refresh(force=parse_qs(url.query).get('fresh') == ['1'])
        n = int(self.headers.get('Content-Length') or 0)
        if n > 1 << 20:
            return self.reply('请求太大。', 'text/plain; charset=utf-8', 413)
        try:
            req = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            req = {}
        s = app.catalog.by_page.get(req.get('page') if isinstance(req, dict) else None)
        if not s:
            return self.not_found()
        # 页面报上它现有各块的指纹，从第一个对不上的块起，把后面的都发回去
        v = app.view(s)
        have = req.get('keys') if isinstance(req.get('keys'), list) else []
        i = 0
        while i < len(have) and i < len(v['keys']) and have[i] == v['keys'][i]:
            i += 1
        self.reply_json({'sig': v['sig'], 'title': v['title'], 'head': v['head'], 'toc': v['toc'], 'info': v['info'],
                         'start': i, 'blocks': v['blocks'][i:], 'count': len(v['blocks'])})

    def live(self, page):
        """事件流：先报一次当前的内容指纹，之后每有变化报一次；隔一会儿发个注释行，免得连接被当成闲置。"""
        app = self.server.app
        if page and page not in app.catalog.by_page:
            return self.not_found()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.close_connection = True
        last, version = None, app.version
        while True:
            s = app.catalog.by_page.get(page) if page else None
            sig = app.catalog.state(s) if s or not page else 'gone'
            if sig != last:
                self.wfile.write(('event: %s\ndata: %s\n\n' % ('hello' if last is None else 'change',
                                                              json.dumps({'sig': sig}))).encode('utf-8'))
                last = sig
            else:
                self.wfile.write(b': ping\n\n')
            self.wfile.flush()
            version = app.wait(version, 20)

    def not_found(self):
        self.reply('没有这个页面。', 'text/plain; charset=utf-8', 404)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False     # Windows 上地址复用会让两个进程同时占住一个端口
    daemon_threads = True


def make_server(app, port):
    httpd = Server(('127.0.0.1', port), Handler)
    httpd.app = app
    return httpd
