"""各解析与统计模块共用的零依赖基础工具。"""
import contextlib
import sqlite3
from datetime import datetime
from urllib.request import pathname2url

HINT_KEYS = ('description', 'file_path', 'command', 'cmd', 'pattern', 'query', 'url', 'skill', 'prompt', 'path')


def tool_hint(inp):
    if not isinstance(inp, dict):
        return ''
    for k in HINT_KEYS:
        if inp.get(k):
            # 路径要完整保留（用来汇总改过的文件），其余只是一行提示
            return str(inp[k]).replace('\n', ' ')[:400 if k in ('file_path', 'path') else 120]
    return ''


def flatten_result(content):
    """tool_result 的 content → (文字, 图片所在的下标列表)。"""
    if isinstance(content, str):
        return content, []
    texts, images = [], []
    for j, b in enumerate(content if isinstance(content, list) else []):
        if not isinstance(b, dict):
            continue
        if b.get('type') == 'text':
            texts.append(b.get('text') or '')
        elif b.get('type') == 'image':
            images.append(j)
    return '\n'.join(texts), images


def is_base64_image(block):
    src = block.get('source') or {}
    return src.get('type') == 'base64' and isinstance(src.get('data'), str)


def parse_iso_local(iso):
    """ISO-8601 时间字符串 → 本地时区 datetime；无效返回 None。"""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone()
    except (AttributeError, ValueError):
        return None


@contextlib.contextmanager
def readonly_sqlite(path, timeout=1):
    """以只读方式打开外部应用维护的 SQLite 数据库。"""
    con = sqlite3.connect('file:%s?mode=ro' % pathname2url(path), uri=True, timeout=timeout)
    try:
        yield con
    finally:
        con.close()
