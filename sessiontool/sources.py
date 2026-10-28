"""数据位置：会话记录（Claude Code 和 Codex）、桌面应用的会话清单（含 multi-claude 的各个配置）、本工具自己的索引。"""
import base64
import glob
import json
import os
import re
import sqlite3
from urllib.request import pathname2url

# 清单里只留用得到的字段：完整的记录带着几十 KB 的提示词快照，缓存起来没有意义
KEEP = ('sessionId', 'cliSessionId', 'priorCliSessionIds', 'title', 'cwd', 'createdAt', 'lastActivityAt', 'isArchived',
        'forkedFromSessionId', 'model', 'effort', 'permissionMode', 'completedTurns', 'writtenBranches', 'postTurnSummary')


def app_dirs():
    """桌面应用的数据目录 → [(目录, 配置名)]。配置名是 multi-claude 的配置，普通安装的应用为空。

    - 普通安装在 %APPDATA%\\Claude；2.42304 起搬到 %LOCALAPPDATA%\\Claude-Data\\<包名>
    - 商店版把 AppData 重定向到 Packages 下
    - multi-claude 每个配置一份数据目录：~/.multi-claude/data/Claude-<配置名>；0.1.3 以前放在 %LOCALAPPDATA%\\Claude-<配置名>
    - macOS、Linux 各一处
    """
    home = os.path.expanduser('~')
    out = []
    for base in (os.environ.get('APPDATA'), os.path.join(home, 'Library', 'Application Support'), os.path.join(home, '.config')):
        if base:
            out.append((os.path.join(base, 'Claude'), ''))
    local = os.environ.get('LOCALAPPDATA')
    if local:
        out += [(d, '') for d in glob.glob(os.path.join(local, 'Claude-Data', '*'))]
        out += [(d, '') for d in glob.glob(os.path.join(local, 'Packages', 'Claude_*', 'LocalCache', 'Roaming', 'Claude'))]
        for d in (glob.glob(os.path.join(local, 'Claude-*'))
                  + glob.glob(os.path.join(local, 'Packages', 'Claude_*', 'LocalCache', 'Local', 'Claude-*'))):
            name = os.path.basename(d)[7:]
            if name != 'Data':                  # Claude-Data 是上面那层，Claude-3p 是应用自己的
                out.append((d, '' if name == '3p' else name))
    out += [(d, os.path.basename(d)[7:]) for d in glob.glob(os.path.join(home, '.multi-claude', 'data', 'Claude-*'))]
    seen, dirs = set(), []
    for d, name in out:
        key = os.path.normcase(os.path.realpath(d))
        if key not in seen and os.path.isdir(os.path.join(d, 'claude-code-sessions')):
            seen.add(key)
            dirs.append((d, name))
    return dirs


def jwt_claims(token):
    """只解开身份令牌中间那段声明（不验证签名，也不碰别的令牌），用来认出登录的是哪个邮箱。"""
    try:
        seg = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(seg + '=' * (-len(seg) % 4)))
    except (AttributeError, IndexError, ValueError):
        return {}


def read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class Sources:
    def __init__(self, root=None, stores=None, home=None, codex=None, profile=None):
        user = os.path.expanduser('~')
        config = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(user, '.claude')
        self.root = os.path.abspath(root or os.path.join(config, 'projects'))
        # stores：[(会话清单目录, 配置名)]；也接受只给目录
        if stores is None:
            self.apps = app_dirs()
            self.stores = [(os.path.join(d, 'claude-code-sessions'), name) for d, name in self.apps]
        else:
            self.stores = [s if isinstance(s, tuple) else (s, '') for s in stores]
            self.apps = [(os.path.dirname(d), name) for d, name in self.stores]
        self.codex = os.path.abspath(codex or os.environ.get('CODEX_HOME') or os.path.join(user, '.codex'))
        # Claude Code 自己登录的账号记在这里（设了 CLAUDE_CONFIG_DIR 时在那个目录里）
        self.profile = profile or os.path.join(os.environ.get('CLAUDE_CONFIG_DIR') or user, '.claude.json')
        self.home = os.path.abspath(home or os.environ.get('SESSIONTOOL_HOME') or os.path.join(user, '.sessiontool'))
        self._manifests = {}        # 清单文件 → (文件状态, 记录)：只重读改过的
        self._threads = (None, {})
        self._hints = (None, ({}, {}))

    def transcripts(self):
        """[(路径, 来源)]：Claude Code 的会话记录和各会话里子代理的记录；Codex 的会话记录，含已归档的。"""
        claude = (glob.glob(os.path.join(self.root, '*', '*.jsonl'))
                  + glob.glob(os.path.join(self.root, '*', '*', 'subagents', '*.jsonl')))
        codex = (glob.glob(os.path.join(self.codex, 'sessions', '**', 'rollout-*.jsonl'), recursive=True)
                 + glob.glob(os.path.join(self.codex, 'archived_sessions', '**', 'rollout-*.jsonl'), recursive=True))
        return sorted([(p, 'claude') for p in claude] + [(p, 'codex') for p in codex])

    def app_sessions(self):
        """应用的会话清单：{sessionId: 记录}。记录里补上 _account、_org（清单所在的子目录，也就是登录的账号和组织）
        和 _store（multi-claude 的配置名）。一个会话在多处出现时（multi-claude 的配置常从普通应用复制而来）取最近活动的那份。"""
        out, seen = {}, set()
        for d, name in self.stores:
            for p in glob.glob(os.path.join(d, '**', 'local_*.json'), recursive=True):
                seen.add(p)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                stamp = (st.st_mtime_ns, st.st_size)
                hit = self._manifests.get(p)
                if hit and hit[0] == stamp:
                    r = hit[1]
                else:
                    r = read_json(p)
                    if not isinstance(r, dict) or not r.get('sessionId') or not r.get('cliSessionId'):
                        r = None
                    else:
                        rel = os.path.relpath(os.path.dirname(p), d).split(os.sep)
                        rel = (rel + ['', ''])[:2] if rel != ['.'] else ['', '']
                        r = dict({k: r[k] for k in KEEP if k in r}, _account=rel[0], _org=rel[1], _store=name)
                    self._manifests[p] = (stamp, r)
                if not r:
                    continue
                old = out.get(r['sessionId'])
                if not old or (r.get('lastActivityAt') or 0) >= (old.get('lastActivityAt') or 0):
                    out[r['sessionId']] = r
        for p in [p for p in self._manifests if p not in seen]:
            del self._manifests[p]
        return out

    def account_hints(self):
        """能确定的账号 → 邮箱：Claude Code 在终端里登录的账号，Codex 登录的账号。
        另外给出 multi-claude 各配置最近登录的账号 → 配置名，没有邮箱时拿它当名字。文件没改过就用上次的结果。"""
        paths = [self.profile, os.path.join(self.codex, 'auth.json')] + [os.path.join(p, 'config.json') for p, n in self.apps if n]
        stamp = []
        for p in paths:
            try:
                st = os.stat(p)
                stamp.append((st.st_mtime_ns, st.st_size))
            except OSError:
                stamp.append(None)
        if self._hints[0] == stamp:
            return self._hints[1]
        emails, names = {}, {}
        d = read_json(self.profile)
        oa = d.get('oauthAccount') if isinstance(d, dict) else None
        if isinstance(oa, dict) and oa.get('accountUuid') and oa.get('emailAddress'):
            emails[oa['accountUuid']] = oa['emailAddress']
        d = read_json(os.path.join(self.codex, 'auth.json'))
        token = ((d or {}).get('tokens') or {}).get('id_token') if isinstance(d, dict) else None
        claims = jwt_claims(token) if token else {}
        acct = (claims.get('https://api.openai.com/auth') or {}).get('chatgpt_account_id')
        if acct and claims.get('email'):
            emails[acct] = claims['email']
        for path, name in self.apps:
            d = read_json(os.path.join(path, 'config.json')) if name else None
            if isinstance(d, dict) and d.get('lastKnownAccountUuid'):
                names[d['lastKnownAccountUuid']] = name
        self._hints = (stamp, (emails, names))
        return emails, names

    def codex_threads(self):
        """Codex 的线程表 {线程 ID: 行}（标题、是否归档、模型……），在 state_<版本>.sqlite 里。
        老版本只有 session_index.jsonl，那里只有改过的名字。数据库改过才重读；读不了就当没有。"""
        def version(p):
            m = re.search(r'state_(\d+)\.sqlite$', p)
            return int(m.group(1)) if m else -1

        dbs = sorted(glob.glob(os.path.join(self.codex, 'state_*.sqlite')), key=version)
        names = os.path.join(self.codex, 'session_index.jsonl')
        stamp = []
        for p in dbs[-1:] + [dbs[-1] + '-wal' if dbs else '', names]:
            try:
                st = os.stat(p)
                stamp.append((p, st.st_mtime_ns, st.st_size))
            except OSError:
                pass
        if self._threads[0] == stamp:
            return self._threads[1]
        out = {}
        try:
            with open(names, encoding='utf-8') as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and r.get('id') and r.get('thread_name'):
                        out.setdefault(r['id'], {})['name'] = r['thread_name']
        except OSError:
            pass
        if dbs:
            try:
                con = sqlite3.connect('file:%s?mode=ro' % pathname2url(dbs[-1]), uri=True, timeout=1)
                try:
                    con.row_factory = sqlite3.Row
                    for r in con.execute('SELECT * FROM threads'):
                        r = dict(r)
                        out.setdefault(r['id'], {}).update({k: v for k, v in r.items() if v is not None})
                finally:
                    con.close()
            except sqlite3.Error:
                pass
        self._threads = (stamp, out)
        return out

    def plan_usage(self):
        """应用隔一会儿记一次各组织的额度用量：[(组织 ID, 毫秒时间, 5 小时窗口 %, 7 天窗口 %)]，按时间排好。"""
        out = set()
        for path, _ in self.apps:
            d = read_json(os.path.join(path, 'plan-usage-history.json'))
            for s in d.get('samples') or [] if isinstance(d, dict) else []:
                u = s.get('u') if isinstance(s, dict) else None
                if isinstance(u, dict) and s.get('org') and isinstance(s.get('t'), (int, float)):
                    out.add((s['org'], int(s['t']), u.get('fh'), u.get('sd')))
        return sorted(out, key=lambda x: x[1])
