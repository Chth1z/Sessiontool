"""把 .jsonl 会话记录增量解析进 SQLite 索引。

记录文件只会追加，所以索引记住每个文件读到的位置，下次只读新增的部分。
索引里只存文字和位置；图片、工具的完整输入输出留在原文件里，用到时按偏移量取。
每次回复的 token 用量另存一张表，统计时不必再读消息。
各来源的格式解析委托给 providers（claude / codex / gemini），本模块只负责存储与增量调度。
"""
import hashlib
import json
import os
import sqlite3
import threading

from . import claude, providers
from .claude import EMAIL, LOCAL_IMAGE, is_agent_file, parse_record, prompt_blocks, usage as claude_usage
from .util import HINT_KEYS, flatten_result, is_base64_image, tool_hint

SCHEMA = 11

DDL = """
CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, src TEXT, cli TEXT, size INT, mtime INT, off INT, guard TEXT,
                   title TEXT, cwd TEXT, email TEXT, org TEXT, ctx TEXT);
CREATE TABLE rec(id INTEGER PRIMARY KEY, file INT, off INT, uuid TEXT, parent TEXT, ts TEXT, sid TEXT,
                 kind TEXT, data TEXT, text TEXT, tool TEXT);
CREATE INDEX rec_file ON rec(file, off);
CREATE TABLE usage(file INT, off INT, mid TEXT, ts TEXT, sid TEXT, model TEXT, effort TEXT, speed TEXT,
                   inp INT, out INT, cr INT, cw5 INT, cw1h INT, web INT, think INT);
CREATE INDEX usage_file ON usage(file);
CREATE INDEX usage_mid ON usage(mid);
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
"""
USAGE_COLS = ('mid', 'ts', 'sid', 'model', 'effort', 'speed', 'inp', 'out', 'cr', 'cw5', 'cw1h', 'web', 'think')


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
            con.executescript('DROP TABLE IF EXISTS rec; DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS usage;'
                              'DROP TABLE IF EXISTS meta;' + DDL)
            con.execute("INSERT INTO meta VALUES('schema', ?)", (str(SCHEMA),))
            con.commit()
        else:
            con.execute('CREATE INDEX IF NOT EXISTS usage_mid ON usage(mid)')
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
            for p, src in self.sources.transcripts():
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                k = known.pop(p, None)
                if not k or k['size'] != st.st_size or k['mtime'] != st.st_mtime_ns:
                    todo.append((p, src, st, k))
            for i, (p, src, st, k) in enumerate(todo, 1):
                if progress:
                    progress(i, len(todo), p, st.st_size - (k['off'] if k else 0))
                self._parse(con, p, src, st, k)
                con.commit()
            for k in known.values():
                for table in ('rec', 'usage'):
                    con.execute('DELETE FROM %s WHERE file=?' % table, (k['id'],))
                con.execute('DELETE FROM files WHERE id=?', (k['id'],))
            con.commit()
            return len(todo) + len(known)

    def _parse(self, con, path, src, st, known):
        prov = providers.get(src)
        start, ctx = 0, {}
        meta = {'title': None, 'cwd': None, 'email': None, 'org': None}
        if known:
            fid, cli = known['id'], known['cli']
            if st.st_size >= known['off'] and self._guard(path, known['off']) == known['guard']:
                start = known['off']
                meta = {k: known[k] for k in meta}
                ctx = json.loads(known['ctx'] or '{}')
            else:
                for table in ('rec', 'usage'):
                    con.execute('DELETE FROM %s WHERE file=?' % table, (fid,))
        else:
            cli = prov.file_cli(path)
            fid = con.execute('INSERT INTO files(path, src, cli, size, mtime, off, guard) VALUES(?,?,?,0,0,0,?)',
                              (path, src, cli, '')).lastrowid
        if src == 'gemini':
            ctx.setdefault('sid', cli)
        extra = prov.load_extra(path)
        rows, uses, off = [], [], start
        last_ts = ctx.get('ts', '')
        if src == 'claude' and known and start:
            row = con.execute('SELECT ts FROM rec WHERE file=? ORDER BY off DESC LIMIT 1', (fid,)).fetchone()
            last_ts = row[0] if row else ''
        sidechain = is_agent_file(path)

        def flush():
            con.executemany('INSERT INTO rec(file,off,uuid,parent,ts,sid,kind,data,text,tool) VALUES(?,?,?,?,?,?,?,?,?,?)', rows)
            con.executemany('INSERT INTO usage(file,off,%s) VALUES(?,?%s)' % (','.join(USAGE_COLS), ',?' * len(USAGE_COLS)), uses)
            del rows[:], uses[:]

        def used(use, sid):
            use.setdefault('ts', last_ts)
            use.setdefault('sid', sid or '')
            uses.append((fid, off) + tuple(use[k] for k in USAGE_COLS))

        def emit_linear(recs, use):
            sid = ctx.get('sid')
            for i, (kind, data, text, tool) in enumerate(recs):
                # 无内置 uuid 的来源：用字节偏移和会话 ID 拼稳定锚点（前 8 位是偏移）
                uuid = '%08x%s-%s' % (off & 0xffffffff, '' if i == 0 else '.%d' % i, sid or fid)
                rows.append((fid, off, uuid, ctx.get('last'), last_ts, sid, kind,
                             json.dumps(data, ensure_ascii=False) if data is not None else None, text, tool))
                ctx['last'] = uuid
            if use:
                used(use, sid)

        parse_line = getattr(prov.module, 'parse_line', None)
        ts_key = getattr(prov.module, 'TS_KEY', 'timestamp')
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
                    if parse_line:
                        last_ts = d.get(ts_key) or last_ts
                        emit_linear(*parse_line(d, ctx, extra))
                    else:
                        claude.update_meta(d, ctx, meta)
                        if d.get('uuid'):
                            last_ts = d.get(ts_key) or last_ts
                            kind, data, text, tool = parse_record(d, sidechain)
                            rows.append((fid, off, d['uuid'], d.get('parentUuid'), last_ts, d.get('sessionId'), kind,
                                         json.dumps(data, ensure_ascii=False) if data is not None else None, text, tool))
                            use = claude_usage(d)
                            if use:
                                used(use, d.get('sessionId'))
                off += len(line)
                if len(rows) + len(uses) >= 2000:
                    flush()
        flush()
        prov.module.finalize_meta(ctx, meta, last_ts)
        con.execute('UPDATE files SET size=?, mtime=?, off=?, guard=?, title=?, cwd=?, email=?, org=?, ctx=? WHERE id=?',
                    (st.st_size, st.st_mtime_ns, off, self._guard(path, off), meta['title'], meta['cwd'],
                     meta['email'], meta['org'], json.dumps(ctx, ensure_ascii=False) if ctx else None, fid))

    # ---------- 读取 ----------

    def files(self):
        return [dict(r) for r in self.con().execute('SELECT * FROM files ORDER BY path')]

    def nonempty_files(self):
        """至少含有一条非连接记录或用量记录的文件编号集合（利用文件索引早停，避免扫全表）。"""
        return {r[0] for r in self.con().execute(
            "SELECT id FROM files f WHERE EXISTS (SELECT 1 FROM rec r WHERE r.file=f.id AND r.kind!='link' LIMIT 1) "
            "OR EXISTS (SELECT 1 FROM usage u WHERE u.file=f.id LIMIT 1)")}

    def rows(self, file_id, start=0):
        """一份记录里的各行（start：只要从这个位置起的），按位置排。"""
        return self.con().execute('SELECT id,file,off,uuid,parent,ts,sid,kind,data FROM rec WHERE file=? AND off>=? ORDER BY off',
                                  (file_id, start)).fetchall()

    def raw(self, file_id, off):
        """按索引里登记过的位置，从原文件读回完整的一行。返回 (这一行, 来源)。"""
        con = self.con()
        if not con.execute('SELECT 1 FROM rec WHERE file=? AND off=?', (file_id, off)).fetchone():
            return None, None
        row = con.execute('SELECT path, src FROM files WHERE id=?', (file_id,)).fetchone()
        try:
            with open(row['path'], 'rb') as f:
                f.seek(off)
                return json.loads(f.readline()), row['src']
        except (OSError, ValueError):
            return None, None

    def usage(self, files=None):
        """每次回复的用量，同一次回复（消息编号相同）只取最早的一份。files 限定在这些文件里。"""
        where = ' WHERE file IN (%s)' % ','.join('%d' % int(f) for f in files) if files is not None else ''
        if files is not None and not files:
            return []
        return self.con().execute('SELECT file, %s, MIN(ts) AS ts FROM usage%s GROUP BY mid ORDER BY ts'
                                  % (','.join(c for c in USAGE_COLS if c != 'ts'), where)).fetchall()

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
