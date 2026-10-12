"""命令行入口：python -m sessiontool [serve|list|export|reindex]"""
import argparse
import json
import os
import sys
import urllib.request
import webbrowser

from . import __version__
from .export import export_to
from .render import fmt
from .server import App, make_server
from .sources import Sources

DEFAULT_PORT = 7707


def progress(i, n, path, size):
    print('  [%d/%d] 读取 %s（%.1f MB）' % (i, n, os.path.basename(path)[:8], size / 1048576), flush=True)


def open_app(args):
    app = App(Sources(root=args.root, home=args.home))
    if not os.path.isdir(app.sources.root):
        sys.exit('找不到会话记录目录：%s' % app.sources.root)
    if not app.index.files():
        print('首次运行，正在建立索引（记录越多越久，之后只读新增内容）…')
    app.catalog.refresh(progress, force=True)
    return app


def running(port):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % port, timeout=0.5) as r:
            return json.load(r).get('app') == 'sessiontool'
    except (OSError, ValueError):
        return False


def cmd_serve(args):
    httpd = None
    for port in range(args.port, args.port + 20):
        url = 'http://127.0.0.1:%d/' % port
        if running(port):
            print('已经在运行：%s' % url)
            if not args.no_browser:
                webbrowser.open(url)
            return
        try:
            httpd = make_server(None, port)
            break
        except OSError:
            continue
    if httpd is None:
        sys.exit('端口 %d 起的 20 个端口都被占用，请用 --port 指定别的端口。' % args.port)
    httpd.app = open_app(args)
    print('Sessiontool %s：%s 个会话 → %s' % (__version__, len(httpd.app.catalog.sessions), url))
    print('保持此窗口打开；按 Ctrl+C 或直接关闭窗口即停止。')
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')


def cmd_list(args):
    app = open_app(args)
    for s, c, depth, _ in app.entries():
        flags = ''.join(t for t, on in (('[复刻]', s.parent), ('[归档]', s.archived)) if on)
        print('%-10s %s  %3d 问  %6.1f MB  %-14s %s%s %s' % (s.page, fmt(c['last']), c['n_user'], s.size / 1048576, s.proj[:14],
                                                         '  ' * depth, c['title'], flags))


def cmd_export(args):
    app = open_app(args)
    cat = app.catalog
    if args.all:
        targets = cat.sessions
    else:
        if not args.session:
            sys.exit('请给出会话编号或标题片段，或者用 --all 导出全部。')
        targets = cat.find(args.session)
        if not targets:
            sys.exit('没有匹配「%s」的会话，用 list 查看全部。' % args.session)
        if len(targets) > 1:
            print('匹配到多个会话，请用编号指定：')
            for s in targets:
                print('  %-10s %s' % (s.page, cat.content(s)['title']))
            sys.exit(1)
    for s in targets:
        print(export_to(cat, s, args.out, args.format, args.images))


def cmd_reindex(args):
    sources = Sources(root=args.root, home=args.home)
    for name in ('index.db', 'index.db-wal', 'index.db-shm'):
        path = os.path.join(sources.home, name)
        if os.path.exists(path):
            os.remove(path)
    app = open_app(args)
    print('索引已重建：%d 个会话。' % len(app.catalog.sessions))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    ap = argparse.ArgumentParser(prog='sessiontool', description='在本机完整查看 Claude 桌面应用 / Claude Code 的会话记录')
    ap.add_argument('--version', action='version', version=__version__)
    ap.add_argument('--root', help='会话记录目录（默认 ~/.claude/projects）')
    ap.add_argument('--home', help='索引存放的文件夹（默认 ~/.sessiontool）')
    sub = ap.add_subparsers(dest='cmd')
    p = sub.add_parser('serve', help='启动本地网页并打开浏览器（默认）')
    p.add_argument('--port', type=int, default=DEFAULT_PORT)
    p.add_argument('--no-browser', action='store_true', help='不自动打开浏览器')
    sub.add_parser('list', help='列出全部会话')
    p = sub.add_parser('export', help='把会话导出成单个 HTML 或 Markdown 文件')
    p.add_argument('session', nargs='?', help='会话编号（list 的第一列）或标题片段')
    p.add_argument('--all', action='store_true', help='导出全部会话')
    p.add_argument('-f', '--format', choices=('html', 'md'), default='html')
    p.add_argument('-o', '--out', default='export', help='输出文件夹（默认 ./export）')
    p.add_argument('--images', action='store_true', help='HTML 里内嵌工具截图（文件会很大）')
    sub.add_parser('reindex', help='删除索引并重建')
    args = ap.parse_args(argv)
    if not args.cmd:
        args.cmd, args.port, args.no_browser = 'serve', DEFAULT_PORT, False
    {'serve': cmd_serve, 'list': cmd_list, 'export': cmd_export, 'reindex': cmd_reindex}[args.cmd](args)


if __name__ == '__main__':
    main()
