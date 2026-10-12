"""把 .jsonl 会话记录解析进 SQLite 索引。

记录文件只会追加，所以索引记住每个文件读到的位置，下次只读新增的部分。
索引里只存文字和位置；图片、工具的完整输入输出留在原文件里，用到时按偏移量取。
"""
import hashlib
import json
import os
import re
import sqlite3
import threading

SCHEMA = 7
LOCAL_IMAGE = re.compile(r'\[Image: source: ([^\]\r\n]+\.(?:png|jpe?g|gif|webp))\]', re.I)

DDL = """
CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, cli TEXT, size INT, mtime INT,
                   off INT, guard TEXT, title TEXT, cwd TEXT);
CREATE TABLE rec(id INTEGER PRIMARY KEY, file INT, off INT, uuid TEXT, parent TEXT, ts TEXT, sid TEXT,
                 kind TEXT, data TEXT, text TEXT, tool TEXT);
CREATE INDEX rec_file ON rec(file, off);
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
"""

HINT_KEYS = ('description', 'file_path', 'command', 'pattern', 'query', 'url', 'skill', 'prompt', 'path')


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


def is_agent_file(path):
    """子代理的记录放在 <会话>/subagents/ 下，一个子代理一个文件。"""
    return os.path.basename(os.path.dirname(path)) == 'subagents'


def is_base64_image(block):
    src = block.get('source') or {}
    return src.get('type') == 'base64' and isinstance(src.get('data'), str)


def prompt_blocks(prompt):
    """回复进行中追加的消息（attachment.prompt）→ (块列表, 文字)。带的图片按下标登记。"""
    if isinstance(prompt, str):
        return ([['text', prompt]], prompt) if prompt.strip() else ([], '')
    blocks, texts = [], []
    for i, b in enumerate(prompt if isinstance(prompt, list) else []):
        if not isinstance(b, dict):
            continue
        if b.get('type') == 'text' and (b.get('text') or '').strip():
            texts.append(b['text'])
        elif b.get('type') == 'image' and is_base64_image(b):
            blocks.append(['img', i])
    text = '\n'.join(texts)
    return ([['text', text]] if text else []) + blocks, text


def parse_record(d, sidechain=False):
    """一行 JSON → (kind, data, text, tool)。只参与父子关系的行返回 ('link', None, '', '')。

    sidechain=True 用于子代理自己的记录文件：那里每一行都带 isSidechain。
    """
    link = ('link', None, '', '')
    t = d.get('type')
    if t in ('user', 'assistant'):
        if d.get('isSidechain') and not sidechain:
            return link
        msg = d.get('message') or {}
        content = msg.get('content')
        if isinstance(content, str):
            content = [{'type': 'text', 'text': content}]
        if not isinstance(content, list):
            return link
        blocks, texts, tools = [], [], []
        for i, b in enumerate(content):
            if not isinstance(b, dict):
                continue
            bt = b.get('type')
            if bt == 'text':
                s = b.get('text') or ''
                if s.strip():
                    blocks.append(['text', s])
                    texts.append(s)
            elif bt == 'image':
                if is_base64_image(b):
                    blocks.append(['img', i])
            elif bt == 'thinking':
                s = (b.get('thinking') or '').strip()
                if s:
                    blocks.append(['think', s])
            elif bt == 'tool_use':
                inp = b.get('input')
                name = b.get('name') or '?'
                hint = tool_hint(inp)
                extra = None
                if name == 'SendUserFile' and isinstance(inp, dict):
                    # 发给你的文件：记下路径，页面上直接列出来，图片还能显示
                    files = [f for f in inp.get('files') or [] if isinstance(f, str)]
                    extra = {'files': files, 'caption': str(inp.get('caption') or '')[:500]}
                blocks.append(['use', b.get('id'), name, hint, i, extra])
                tools.append('%s %s %s' % (name, hint, json.dumps(inp, ensure_ascii=False)[:3000]))
            elif bt == 'tool_result':
                text, images = flatten_result(b.get('content'))
                local = LOCAL_IMAGE.findall(text)[:20]
                result = d.get('toolUseResult')
                agent = result.get('agentId') if isinstance(result, dict) else None
                blocks.append(['res', b.get('tool_use_id'), i, text[:300], len(text), images,
                               bool(b.get('is_error')), local, agent if isinstance(agent, str) else None])
                tools.append(text[:6000])
        if not blocks:
            return link
        data = {'b': blocks}
        if d.get('isMeta'):
            data['meta'] = 1
        if d.get('isCompactSummary'):
            data['compact'] = 1
        if msg.get('model') == '<synthetic>' or d.get('isApiErrorMessage'):
            data['synthetic'] = 1
        elif t == 'assistant' and msg.get('id'):
            # 一次回复按内容块拆成多行，每行都带同一份用量；统计时按消息编号只算一次
            u = msg.get('usage') or {}
            data['mid'] = msg['id']
            data['model'] = msg.get('model') or ''
            data['usage'] = [int(u.get(k) or 0) for k in ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                                                           'cache_creation_input_tokens')]
        origin = (d.get('origin') or {}).get('kind')
        if origin:
            data['origin'] = origin
        return t, data, '\n'.join(texts), '\n'.join(tools)
    if t == 'attachment':
        # 回复进行中你追加的消息不记成 user 行，只在这里
        a = d.get('attachment') or {}
        if (a.get('type') == 'queued_command' and a.get('commandMode') == 'prompt'
                and (a.get('origin') or {}).get('kind') in (None, 'human')):
            blocks, text = prompt_blocks(a.get('prompt'))
            if blocks:
                return 'queued', {'b': blocks}, text, ''
        return link
    if t == 'system':
        sub = d.get('subtype')
        if sub == 'compact_boundary':
            m = d.get('compactMetadata') or {}
            return 'compact', {'trigger': m.get('trigger'), 'pre': m.get('preTokens'), 'post': m.get('postTokens')}, '', ''
        if sub == 'local_command':
            run = d.get('commandRun') or {}
            out = re.sub(r'</?local-command-\w+>', '', str(d.get('content') or '')).strip()
            return 'cmd', {'cmd': run.get('command'), 'args': run.get('args'), 'out': out[:20000]}, '', ''
    return link


class Index:
    def __init__(self, sources):
        self.sources = sources
        os.makedirs(sources.home, exist_ok=True)
        self.path = os.path.join(sources.home, 'index.db')
        self.lock = threading.Lock()
        self.local = threading.local()
        con = self.con()
        try:
            row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
        except sqlite3.OperationalError:
            row = None
        if not row or row[0] != str(SCHEMA):
            con.executescript('DROP TABLE IF EXISTS rec; DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS meta;' + DDL)
            con.execute("INSERT INTO meta VALUES('schema', ?)", (str(SCHEMA),))
            con.commit()

    def con(self):
        con = getattr(self.local, 'con', None)
        if con is None:
            con = sqlite3.connect(self.path, timeout=60)
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('PRAGMA synchronous=NORMAL')
            self.local.con = con
        return con

    def close(self):
        con = getattr(self.local, 'con', None)
        if con is not None:
            con.close()
            self.local.con = None

    # ---------- 同步 ----------

    @staticmethod
    def _guard(path, off):
        """已读部分末尾的指纹，用来确认文件确实只是被追加。"""
        if off <= 0:
            return ''
        with open(path, 'rb') as f:
            f.seek(max(0, off - 256))
            return hashlib.sha1(f.read(min(off, 256))).hexdigest()

    def sync(self, progress=None):
        """让索引与磁盘一致，返回有变化的文件数。progress(i, n, path, 待读字节数)。"""
        with self.lock:
            con = self.con()
            known = {r['path']: r for r in con.execute('SELECT * FROM files')}
            todo = []
            for p in self.sources.transcripts():
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                k = known.pop(p, None)
                if not k or k['size'] != st.st_size or k['mtime'] != st.st_mtime_ns:
                    todo.append((p, st, k))
            for i, (p, st, k) in enumerate(todo, 1):
                if progress:
                    progress(i, len(todo), p, st.st_size - (k['off'] if k else 0))
                self._parse(con, p, st, k)
                con.commit()
            for k in known.values():
                con.execute('DELETE FROM rec WHERE file=?', (k['id'],))
                con.execute('DELETE FROM files WHERE id=?', (k['id'],))
            con.commit()
            return len(todo) + len(known)

    def _parse(self, con, path, st, known):
        start, title, cwd, last_ts = 0, None, None, ''
        if known:
            fid = known['id']
            if st.st_size >= known['off'] and self._guard(path, known['off']) == known['guard']:
                start, title, cwd = known['off'], known['title'], known['cwd']
                row = con.execute('SELECT ts FROM rec WHERE file=? ORDER BY off DESC LIMIT 1', (fid,)).fetchone()
                last_ts = row[0] if row else ''
            else:
                con.execute('DELETE FROM rec WHERE file=?', (fid,))
        else:
            cli = os.path.splitext(os.path.basename(path))[0]
            fid = con.execute('INSERT INTO files(path, cli, size, mtime, off, guard) VALUES(?,?,0,0,0,?)',
                              (path, cli, '')).lastrowid
        rows, off = [], start
        sidechain = is_agent_file(path)
        with open(path, 'rb') as f:
            f.seek(start)
            while True:
                line = f.readline()
                if not line:
                    break
                try:
                    d = json.loads(line)
                except ValueError:
                    if not line.endswith(b'\n'):
                        break           # 正在写入的半行，下次再读
                    off += len(line)
                    continue
                if isinstance(d, dict):
                    if d.get('type') == 'custom-title' and d.get('customTitle'):
                        title = d['customTitle']
                    cwd = cwd or d.get('cwd')
                    if d.get('uuid'):
                        last_ts = d.get('timestamp') or last_ts
                        kind, data, text, tool = parse_record(d, sidechain)
                        rows.append((fid, off, d['uuid'], d.get('parentUuid'), last_ts, d.get('sessionId'), kind,
                                     json.dumps(data, ensure_ascii=False) if data is not None else None, text, tool))
                off += len(line)
                if len(rows) >= 2000:
                    con.executemany('INSERT INTO rec(file,off,uuid,parent,ts,sid,kind,data,text,tool) '
                                    'VALUES(?,?,?,?,?,?,?,?,?,?)', rows)
                    rows = []
        con.executemany('INSERT INTO rec(file,off,uuid,parent,ts,sid,kind,data,text,tool) VALUES(?,?,?,?,?,?,?,?,?,?)', rows)
        con.execute('UPDATE files SET size=?, mtime=?, off=?, guard=?, title=?, cwd=? WHERE id=?',
                    (st.st_size, st.st_mtime_ns, off, self._guard(path, off), title, cwd, fid))

    # ---------- 读取 ----------

    def files(self):
        return [dict(r) for r in self.con().execute('SELECT * FROM files ORDER BY path')]

    def rows(self, file_id):
        return self.con().execute('SELECT id,file,off,uuid,parent,ts,sid,kind,data FROM rec WHERE file=? ORDER BY off',
                                  (file_id,)).fetchall()

    def raw(self, file_id, off):
        """按索引里登记过的位置，从原文件读回完整的一行。"""
        con = self.con()
        if not con.execute('SELECT 1 FROM rec WHERE file=? AND off=?', (file_id, off)).fetchone():
            return None
        row = con.execute('SELECT path FROM files WHERE id=?', (file_id,)).fetchone()
        try:
            with open(row['path'], 'rb') as f:
                f.seek(off)
                return json.loads(f.readline())
        except (OSError, ValueError):
            return None

    def search(self, terms, tools=False, limit=3000):
        """每个词都要出现在同一条消息里（文字；tools=True 时工具调用与输出也算）。"""
        conds, args = [], []
        for term in terms:
            like = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            if tools:
                conds.append("(text LIKE ? ESCAPE '\\' OR tool LIKE ? ESCAPE '\\')")
                args += [like, like]
            else:
                conds.append("text LIKE ? ESCAPE '\\'")
                args.append(like)
        sql = ("SELECT id,file,uuid,ts,kind,data,text,tool FROM rec WHERE kind IN ('user','assistant','queued') AND "
               + ' AND '.join(conds) + ' ORDER BY ts LIMIT ?')
        return self.con().execute(sql, args + [limit]).fetchall()
