"""应用会话 ↔ 记录文件：合并、去重、识别复刻与改写分支，整理成可渲染的条目；会话属于哪个账号、用了多少。

磁盘上的实际情况：
- 一个应用会话可能对应多份 .jsonl（压缩或重启后新建），新文件会带着旧消息的副本（uuid 不变）。
- 复刻出的会话，记录从父会话最近一次压缩处开始；更早的历史只在父会话的文件里。
- 回复进行中追加的消息记在 attachment 行里，不是 user 行。
- 应用的会话清单按 <账号>/<组织>/ 分目录存放；multi-claude 的每个配置各有一份清单。
- Codex 一个线程一份记录，标题、归档这些在它自己的线程表里。
"""
import collections
import json
import os
import re
import threading
import time
import zlib

from . import pricing
from .index import is_agent_file

AUTO_CONTINUE = 'I hit my usage limit while you were working'
INTERRUPT = re.compile(r'\[Request interrupted by user[^\]]*\]')
NOTE_PREFIX = ('<task-notification', '<ci-monitor-event')
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'apply_patch')


def clean_prompt(s):
    """去掉应用塞进用户消息里的机器内容，只留你实际输入的文字。"""
    s = re.sub(r'<system-reminder>.*?</system-reminder>', '', s, flags=re.S)
    s = re.sub(r'<local-command-(stdout|stderr|caveat)>.*?</local-command-\1>', '', s, flags=re.S)
    s = re.sub(r'\[Image: source: [^\]\n]+\]', '', s)
    m = re.search(r'<command-name>(.*?)</command-name>', s, flags=re.S)
    if m:
        args = re.search(r'<command-args>(.*?)</command-args>', s, flags=re.S)
        s = (m.group(1).strip() + ' ' + (args.group(1).strip() if args else '')).strip()
    return s.strip()


def prompt_text(r):
    return clean_prompt('\n\n'.join(b[1] for b in r['d']['b'] if b[0] == 'text'))


def is_prompt(r):
    """是不是你亲手发的一条消息（而不是工具结果、系统通知、压缩摘要）。"""
    d = r['d']
    if r['kind'] != 'user' or d.get('meta') or d.get('compact') or d.get('origin') not in (None, 'human'):
        return False
    if any(b[0] == 'res' for b in d['b']):
        return False
    text = prompt_text(r)
    if not text:
        return any(b[0] == 'img' for b in d['b'])
    return not (INTERRUPT.fullmatch(text) or text.startswith(NOTE_PREFIX) or text.startswith(AUTO_CONTINUE))


def find_abandoned(recs, links):
    """回退并改写消息后，旧的那一支仍留在记录里。返回 {uuid: 该分支起点的 uuid}。

    判据：接在同一条对话消息后面的、你亲手发的消息有两条以上，最晚的一条是现行的，其余各自带着的后续都是旧分支。
    “接在后面”要跳过中间只起连接作用的记录：旧的那条常常挂在一条钩子小结上，新的那条直接挂在上一条回复上。
    并行工具调用也会产生分叉，但分叉的不是用户消息，不会被误判。
    """
    by = {r['uuid']: r for r in recs if r['uuid']}
    children = collections.defaultdict(list)
    for u, p in links.items():
        if p:
            children[p].append(u)

    def anchor(u):
        p, hops = links.get(u), 0
        while p and p not in by and hops < 50:
            p, hops = links.get(p), hops + 1
        return p

    groups = collections.defaultdict(list)
    for r in recs:
        if r['uuid'] and is_prompt(r):
            a = anchor(r['uuid'])
            if a:
                groups[a].append(r)
    dead = {}
    for prompts in groups.values():
        if len(prompts) < 2:
            continue
        prompts.sort(key=lambda r: r['ts'] or '')
        keep = prompt_text(prompts[-1])
        for r in prompts[:-1]:
            tree, stack = [], [r['uuid']]
            while stack:
                u = stack.pop()
                if u not in tree:
                    tree.append(u)
                    stack.extend(children.get(u, ()))
            # 原样重发、而且前一次什么都没来得及做：不算分支，交给 assemble 里的去重悄悄合并
            if prompt_text(r) == keep and not any(u in by and by[u]['kind'] == 'assistant' for u in tree):
                continue
            for u in tree:
                dead.setdefault(u, r['uuid'])
    return dead


def assemble(recs, links, own_ids, forked):
    """按时间排好的记录 → 页面条目。"""
    dead = find_abandoned(recs, links)
    items, tools = [], {}
    target, branch = items, None
    n_user, marked = 0, not forked
    for r in recs:
        b = dead.get(r['uuid'])
        if b != branch:
            branch = b
            if b:
                box = {'kind': 'branch', 'ts': r['ts'], 'items': []}
                items.append(box)
                target = box['items']
            else:
                target = items
        if not marked and not b and r['sid'] in own_ids:
            marked = True
            if items:
                items.append({'kind': 'fork', 'ts': r['ts']})
        kind, d, ts, u = r['kind'], r['d'], r['ts'], (r['uuid'] or '')[:8]
        ref = '%d.%d' % (r['file'], r['off'])
        prompt = None
        if kind == 'compact':
            target.append({'kind': 'compact', 'ts': ts, 'trigger': d.get('trigger'), 'pre': d.get('pre'), 'post': d.get('post')})
        elif kind == 'cmd':
            target.append({'kind': 'cmd', 'ts': ts, 'cmd': d.get('cmd') or '', 'args': d.get('args') or '', 'out': d.get('out') or ''})
        elif kind == 'queued':
            body = clean_prompt('\n\n'.join(b[1] for b in d['b'] if b[0] == 'text'))
            imgs = ['%s.%d' % (ref, b[1]) for b in d['b'] if b[0] == 'img']
            if (body or imgs) and not body.startswith(NOTE_PREFIX):
                prompt = {'kind': 'user', 'ts': ts, 'u': u, 'text': body, 'imgs': imgs, 'queued': True}
        elif kind == 'user':
            texts, imgs = [], []
            for blk in d['b']:
                if blk[0] == 'text':
                    texts.append(blk[1])
                elif blk[0] == 'img':
                    imgs.append('%s.%d' % (ref, blk[1]))
                elif blk[0] == 'res':
                    tu = tools.get(blk[1])
                    if tu:
                        tu.update(res='%s.%d' % (ref, blk[2]), preview=blk[3], size=blk[4], error=blk[6], ru=u,
                                  imgs=['%s.%d.%d' % (ref, blk[2], j) for j in blk[5]], local=blk[7], agent=blk[8])
                        tu['nimg'] = len(tu['imgs']) + len(tu['local'])
            if d.get('meta'):
                continue
            body = clean_prompt('\n\n'.join(texts))
            if not body and not imgs:
                continue
            if INTERRUPT.fullmatch(body):
                target.append({'kind': 'stop', 'ts': ts})
            elif d.get('compact'):
                target.append({'kind': 'summary', 'ts': ts, 'u': u, 'text': body})
            elif d.get('origin') == 'task-notification' or body.startswith(NOTE_PREFIX):
                target.append({'kind': 'note', 'ts': ts, 'text': body})
            elif body.startswith(AUTO_CONTINUE):
                target.append({'kind': 'auto', 'ts': ts})
            else:
                prompt = {'kind': 'user', 'ts': ts, 'u': u, 'text': body, 'imgs': imgs, 'queued': False}
        elif kind == 'assistant':
            for blk in d['b']:
                if blk[0] == 'text':
                    target.append({'kind': 'notice' if d.get('synthetic') else 'asst', 'ts': ts, 'u': u, 'text': blk[1].strip()})
                elif blk[0] == 'think':
                    target.append({'kind': 'think', 'ts': ts, 'text': blk[1]})
                elif blk[0] == 'use':
                    extra = blk[5] or {}
                    tu = {'name': blk[2], 'hint': blk[3], 'use': '%s.%d' % (ref, blk[4]), 'res': None, 'preview': '',
                          'size': 0, 'nimg': 0, 'error': False, 'u': u, 'ru': '', 'imgs': [], 'local': [], 'agent': None,
                          'paths': extra.get('paths')}
                    tools[blk[1]] = tu
                    if 'files' in extra:        # 发给你的文件单独成一条，不埋在工具调用里
                        target.append({'kind': 'sent', 'ts': ts, 'u': u, 'caption': extra['caption'],
                                       'files': [(path, '%s.%d.%d' % (ref, blk[4], k)) for k, path in enumerate(extra['files'])]})
                    elif target and target[-1]['kind'] == 'tools':
                        target[-1]['tools'].append(tu)
                    else:
                        target.append({'kind': 'tools', 'ts': ts, 'tools': [tu]})
        if prompt:
            # 发出后被中断、应用重启会话又原样重发的同一条消息，只保留后一条
            j = len(target) - 1
            while j >= 0 and target[j]['kind'] in ('stop', 'note', 'think', 'notice'):
                j -= 1
            if j >= 0 and target[j]['kind'] == 'user' and target[j]['text'] == prompt['text']:
                if target is items:
                    n_user -= 1
                target[j:] = [x for x in target[j + 1:] if x['kind'] != 'stop']
            if target is items:
                n_user += 1
                prompt['n'] = n_user
            target.append(prompt)
    return items


def stats(items):
    prompts = [it for it in items if it['kind'] == 'user']
    stamps = [it['ts'] for it in items if it.get('ts')]
    changed = collections.OrderedDict()         # 路径 → [次数, 第一次修改的锚点]
    names = collections.Counter()
    shots = 0
    for it in items:
        for t in it['tools'] if it['kind'] == 'tools' else ():
            names[t['name']] += 1
            shots += t['nimg']
            if t['name'] in EDIT_TOOLS:
                for path in t.get('paths') or ([t['hint']] if t['hint'] else []):
                    changed.setdefault(path, [0, t['u']])[0] += 1
    sent = [it for it in items if it['kind'] == 'sent']
    if sent:
        names['SendUserFile'] += len(sent)
    line = lambda it: it['text'][:160].replace('\n', ' ')
    # 列表里显示“最近在做什么”：取最后一条有内容的提问，跳过“继续”“Try again”这类
    recent = next((it for it in reversed(prompts) if len(it['text'].strip()) >= 12), prompts[-1] if prompts else None)
    return {'n_user': len(prompts), 'n_asst': sum(1 for it in items if it['kind'] == 'asst'),
            'changed': [(path, n, u) for path, (n, u) in changed.items()],
            'n_tools': sum(names.values()), 'tool_counts': names.most_common(),
            'n_shots': shots, 'n_images': sum(len(it['imgs']) for it in prompts),
            'n_sent': sum(len(it['files']) for it in sent),
            'n_compact': sum(1 for it in items if it['kind'] == 'compact'),
            'n_branch': sum(1 for it in items if it['kind'] == 'branch'),
            'first': min(stamps) if stamps else '', 'last': max(stamps) if stamps else '',
            'first_prompt': line(prompts[0]) if prompts else '', 'last_prompt': line(recent) if recent else ''}


def summary(rows):
    """一组回复的用量（index.usage 的行）→ 合计、费用、缓存命中率，按模型和推理强度分组。可以直接转成 JSON。"""
    total, models, efforts = pricing.Tally(), {}, {}
    for r in rows:
        p = pricing.row_parts(r)
        total.add(r, p)
        models.setdefault(r['model'] or '', pricing.Tally()).add(r, p)
        efforts.setdefault(r['effort'] or '', pricing.Tally()).add(r, p)
    out = total.json()
    out['models'] = [dict(t.json(), model=m, name=pricing.model_name(m), priced=bool(pricing.key(m)))
                     for m, t in sorted(models.items(), key=lambda kv: (-kv[1].cost, -kv[1].n))]
    out['efforts'] = [dict(t.json(), effort=e) for e, t in sorted(efforts.items(), key=lambda kv: -kv[1].n)]
    return out


class Session:
    # 两种来源共有的字段：Claude 的会话不填 Codex 才有的几项，反之亦然
    DEFAULTS = dict(src='claude', parent=None, parent_id=None, orphan=False, archived=False, created=0, record_title=None,
                    file_title=None, model='', effort='', permission='', turns=None, branches=(), account='', org='',
                    store='', agent_files=(), version='', origin='', status=None)

    def __init__(self, **kw):
        self.__dict__.update(self.DEFAULTS)
        self.__dict__.update(kw)
        self.status = self.status or {k: '' for k in ('status_category', 'status_detail', 'needs_action')}


def first_line(text, n=80):
    """很长的标题（Codex 拿整条首问当标题）只取第一行，去掉 Markdown 的标题记号。"""
    for line in (text or '').split('\n'):
        line = re.sub(r'^\s*#+\s*', '', line).strip()
        if line:
            return line[:n]
    return ''


def project(cwd):
    # 没选文件夹就开始的会话，应用给它建了个临时目录，名字没有意义
    return '无文件夹' if 'scratch-workspaces' in cwd else (os.path.basename(cwd.rstrip('\\/')) or cwd or '（未知）')


class Catalog:
    def __init__(self, index):
        self.index = index
        self.sources = index.sources
        pricing.configure(self.sources.home)
        self.lock = threading.RLock()
        self.checked = 0
        self.inputs = None
        self.sessions, self.by_page, self.by_cli, self.owner, self.agents, self.accounts = [], {}, {}, {}, {}, {}
        self._merged, self._content = {}, {}

    def refresh(self, progress=None, force=False):
        """与磁盘同步，返回有没有变化。两秒内的重复调用直接跳过（force 不跳过）。"""
        with self.lock:
            if not force and time.time() - self.checked < 2:
                return False
            changed = self.index.sync(progress) > 0
            # 清单、Codex 的线程表、账号线索都没改过时，拿到的就是上次那几个对象，比较起来很快
            inputs = (self.sources.app_sessions(), self.sources.codex_threads(), self.sources.account_hints())
            if changed or inputs != self.inputs:
                self.inputs = inputs
                self._build(*inputs)
                changed = True
            self.checked = time.time()
            return changed

    def _build(self, apps, threads, hints):
        files, codex, agents_of, self.agents = {}, [], collections.defaultdict(list), {}
        for f in self.index.files():
            if f['src'] == 'codex':
                codex.append(f)
            elif is_agent_file(f['path']):     # 子代理的记录不是独立会话，按编号挂到调用它的地方
                self.agents[re.sub(r'^agent-', '', f['cli'])] = f
                agents_of[os.path.basename(os.path.dirname(os.path.dirname(f['path'])))].append(f)
            else:
                files[f['cli']] = f
        raw, used = {}, set()
        for sid, r in apps.items():
            ids = []
            for i in list(r.get('priorCliSessionIds') or []) + [r.get('cliSessionId')]:
                if i and i not in ids:
                    ids.append(i)
            used.update(ids)
            raw[sid] = (r, ids)
        for cli in files:       # 应用清单里没有的记录（终端里跑的、或清单已删除的）各自成一个会话
            if cli not in used:
                raw['file_' + cli] = ({'_orphan': True}, [cli])
        sessions, taken = {}, set()

        def page(key):
            n = 8
            while key[:n] in taken and n < len(key):
                n += 1
            taken.add(key[:n])
            return key[:n]

        for sid in sorted(raw):
            r, ids = raw[sid]
            own = [files[i] for i in ids if i in files]
            if not own:
                continue
            cwd = r.get('cwd') or own[-1]['cwd'] or ''
            status = r.get('postTurnSummary') if isinstance(r.get('postTurnSummary'), dict) else {}
            sessions[sid] = Session(
                id=sid, page=page(re.sub(r'^(local_|file_)', '', sid).replace('-', '')), record_title=r.get('title'),
                file_title=own[-1]['title'], cwd=cwd, proj=project(cwd), archived=bool(r.get('isArchived')),
                created=r.get('createdAt') or 0, parent_id=r.get('forkedFromSessionId'), cli_ids=ids, files=own,
                orphan=bool(r.get('_orphan')), size=sum(f['size'] for f in own),
                agent_files=[a for i in ids for a in agents_of.get(i, ())],
                account=r.get('_account') or '', org=r.get('_org') or own[-1]['org'] or '', store=r.get('_store') or '',
                # 以下只用于“详情”：应用自己记下的设置和最近状态
                model=r.get('model') or '', effort=r.get('effort') or '', permission=r.get('permissionMode') or '',
                turns=r.get('completedTurns'),
                branches=[b.split('\x00')[-1] for b in r.get('writtenBranches') or [] if isinstance(b, str)],
                status={k: str(status.get(k) or '') for k in ('status_category', 'status_detail', 'needs_action')})
        for f in codex:
            ctx = json.loads(f['ctx'] or '{}')
            tid = ctx.get('sid') or f['cli']
            t = threads.get(tid) or {}
            cwd = re.sub(r'^\\\\\?\\', '', ctx.get('cwd') or t.get('cwd') or f['cwd'] or '')     # 线程表里的带着 \\?\ 前缀
            h = tid.replace('-', '')
            sessions['codex_' + tid] = Session(
                # 线程 ID 的开头是时间，挨着建的几个线程开头相同；页面编号取末尾随机的那段
                src='codex', id='codex_' + tid, page=page(h[20:] + h[:20]),
                record_title=t.get('name') or first_line(t.get('title')), cwd=cwd, proj=project(cwd),
                archived=bool(t.get('archived')) or 'archived_sessions' in f['path'], created=t.get('created_at_ms') or 0,
                cli_ids=[tid], files=[f], size=f['size'], account=t.get('creator_account_id') or ctx.get('acct') or '',
                model=t.get('model') or ctx.get('model') or '', effort=t.get('reasoning_effort') or ctx.get('effort') or '',
                permission=t.get('approval_mode') or '', branches=[b for b in [t.get('git_branch') or ctx.get('branch')] if b],
                version=ctx.get('version') or t.get('cli_version') or '', origin=ctx.get('origin') or t.get('originator') or '')
        for s in sessions.values():
            p = sessions.get(s.parent_id)
            s.parent = p if p is not s else None
        self._accounts(sessions.values(), *hints)
        self.sessions = list(sessions.values())
        self.by_page = {s.page: s for s in self.sessions}
        self.owner, self.by_cli = {}, {}
        for s in sorted(self.sessions, key=lambda s: s.created):
            for f in s.files:
                self.owner.setdefault(f['id'], s)
            for i in s.cli_ids:
                self.by_cli.setdefault(i, s)

    def _accounts(self, sessions, emails, names):
        """会话属于哪个账号，账号叫什么。

        应用里的会话，看清单所在的子目录就知道账号。邮箱先看登录信息（emails）；没有的，
        看这个账号的会话记录里写着的邮箱，取出现最多的那个。终端里跑的会话没有清单，直接看记录里的邮箱。"""
        votes = collections.defaultdict(collections.Counter)
        for s in sessions:
            if s.src == 'claude' and s.account:
                for f in s.files:
                    if f['email']:
                        votes[s.account][f['email']] += 1
        email_of = {a: c.most_common(1)[0][0] for a, c in votes.items()}
        email_of.update(emails)
        by_email = {e.lower(): a for a, e in email_of.items()}
        for s in sessions:
            if s.src == 'claude' and not s.account:
                e = next((f['email'] for f in reversed(s.files) if f['email']), '')
                s.account = by_email.get(e.lower(), e) if e else ''
        self.accounts = {}
        for s in sessions:
            a = s.account
            if a and a not in self.accounts:
                email = email_of.get(a) or (a if '@' in a else '')
                self.accounts[a] = {'key': a, 'id': '' if '@' in a else a, 'email': email, 'src': s.src, 'profile': names.get(a, ''),
                                    'name': email.split('@')[0] if email else names.get(a) or a[:8]}

    def account(self, s):
        return self.accounts.get(s.account)

    def lineage(self, s, depth=0):
        base = self.lineage(s.parent, depth + 1) if s.parent and depth < 8 else []
        have = {f['id'] for f in base}
        return base + [f for f in s.files if f['id'] not in have]

    def signature(self, s, agents=True):
        """各份记录读到的位置。默认连子代理的记录也算：子代理在跑时，会话的用量跟着变（对话内容不变）。"""
        return tuple((f['id'], f['off']) for f in self.lineage(s) + (list(s.agent_files) if agents else []))

    def spend(self, s):
        """这个会话自己花的用量，按时间排：各份记录和它调用的子代理里、由它自己的记录编号产生的回复。
        复刻会话里从原会话带来的那段（编号是原会话的）不算，那是原会话的花费。"""
        own = set(s.cli_ids)
        return [r for r in self.index.usage([f['id'] for f in list(s.files) + list(s.agent_files)]) if r['sid'] in own]

    def merged(self, s, depth=0):
        """(记录, 父子关系)：父会话里更早的部分 + 自己的各份记录，去重后按时间排序。

        记录文件只会追加：自己的各份记录只是变长了的话，只读新增的那些行，接在上次的结果后面（会话正在进行时每秒都可能变）。"""
        sig = self.signature(s, agents=False)
        hit = self._merged.get(s.id)
        if hit and hit['sig'] == sig:
            return hit['out'], hit['links']
        read = {f['id']: f['off'] for f in s.files}
        grown = hit and hit['read'].keys() == read.keys() and all(read[k] >= v for k, v in hit['read'].items())
        if grown:
            out, links, seen_u, seen_c = list(hit['out']), dict(hit['links']), hit['seen_u'], hit['seen_c']
            new = self._records(s.files, links, hit['read'])
        else:
            links = {}
            own = self._records(s.files, links)
            base = []
            if s.parent and depth < 8:
                precs, plinks = self.merged(s.parent, depth + 1)
                first = min((r['ts'] for r in own if r['ts']), default='')
                base = [r for r in precs if r['ts'] < first]
                for u, p in plinks.items():
                    links.setdefault(u, p)
            out, seen_u, seen_c, new = [], set(), set(), base + own
        tail = out[-1]['ts'] if out else ''
        for r in new:
            key = (r['kind'], r['ts'], r['raw'])
            if (r['uuid'] and r['uuid'] in seen_u) or key in seen_c:
                continue
            seen_u.add(r['uuid'])
            seen_c.add(key)
            links.setdefault(r['uuid'], r['parent'])
            out.append(r)
        if not grown or any(r['ts'] < tail for r in new):
            out.sort(key=lambda r: r['ts'])
        self._merged[s.id] = {'sig': sig, 'read': read, 'out': out, 'links': links, 'seen_u': seen_u, 'seen_c': seen_c}
        return out, links

    def _records(self, files, links, since=None):
        """各份记录里（since：{文件: 位置} 之后新增的）的记录；只起连接作用的行记进 links。"""
        out = []
        for f in files:
            for row in self.index.rows(f['id'], (since or {}).get(f['id'], 0)):
                if row['kind'] == 'link':
                    links.setdefault(row['uuid'], row['parent'])
                else:
                    out.append({'file': row['file'], 'off': row['off'], 'uuid': row['uuid'], 'parent': row['parent'],
                                'ts': row['ts'] or '', 'sid': row['sid'], 'kind': row['kind'], 'raw': row['data'],
                                'd': json.loads(row['data'])})
        return out

    def content(self, s):
        """一个会话整理好的条目、统计和用量，按文件状态缓存。只有子代理的记录变了时，只重算用量。"""
        with self.lock:
            isig, sig = self.signature(s, agents=False), self.signature(s)
            c = self._content.get(s.id)
            if not c or c['isig'] != isig:
                recs, links = self.merged(s)
                items = assemble(recs, links, set(s.cli_ids), bool(s.parent))
                c = {'isig': isig, 'sig': None, 'items': items, 'nfiles': len(self.lineage(s))}
                c.update(stats(items))
                self._content[s.id] = c
            if c['sig'] != sig:
                rows = self.spend(s)
                c['usage'] = summary(rows)
                # 每次回复的 (时间, 费用, 输出 token)，页面上按轮次加总
                c['spend'] = [(r['ts'], sum(pricing.row_parts(r) or ()), r['out']) for r in rows]
                c['sig'] = sig
            # 标题可以在应用里随时改，不跟着记录文件变，所以每次现取
            c['title'] = (s.record_title or s.file_title or c['first_prompt'][:40] or '（无标题）').replace('\n', ' ')
            return c

    def info(self, s):
        """详情面板用的全部信息，可直接转成 JSON。"""
        c = self.content(s)
        current = s.cli_ids[-1]
        link = lambda x: {'page': x.page, 'title': self.content(x)['title']}
        codex = s.src == 'codex'
        return {
            'src': s.src, 'page': s.page, 'title': c['title'], 'id': None if s.orphan or codex else s.id, 'cli': current,
            'orphan': s.orphan, 'archived': s.archived, 'cwd': s.cwd, 'proj': s.proj,
            'account': self.account(s), 'org': s.org, 'store': s.store, 'version': s.version, 'origin': s.origin,
            'files': [{'id': f['cli'], 'path': f['path'], 'size': f['size'], 'current': f['cli'] == current} for f in s.files],
            'agents': len(s.agent_files),
            'created': s.created or None, 'first': c['first'], 'last': c['last'],
            'model': s.model, 'effort': s.effort, 'permission': s.permission,
            'turns': s.turns, 'branches': s.branches, 'status': s.status if any(s.status.values()) else None,
            'counts': {'prompts': c['n_user'], 'replies': c['n_asst'], 'tools': c['n_tools'], 'shots': c['n_shots'],
                       'images': c['n_images'], 'sent': c['n_sent'], 'changed': len(c['changed']),
                       'compact': c['n_compact'], 'branch': c['n_branch'], 'records': c['nfiles']},
            'tools': c['tool_counts'][:10], 'usage': c['usage'], 'size': s.size,
            'first_prompt': c['first_prompt'], 'last_prompt': c['last_prompt'],
            'parent': link(s.parent) if s.parent else None,
            'children': [link(x) for x in self.sessions if x.parent is s],
            'link': None if s.orphan or codex else 'claude://claude.ai/epitaxy/' + s.id,
            'resume': ('codex resume ' if codex else 'claude --resume ') + current}

    def agent_content(self, agent_id):
        """一个子代理自己的对话，整理成和会话一样的条目。没有这份记录时返回 None。"""
        f = self.agents.get(agent_id)
        if not f:
            return None
        with self.lock:
            sig = (f['id'], f['off'])
            c = self._content.get('agent:' + agent_id)
            if c and c['sig'] == sig:
                return c
            recs = [{'file': r['file'], 'off': r['off'], 'uuid': r['uuid'], 'parent': r['parent'], 'ts': r['ts'] or '',
                     'sid': r['sid'], 'kind': r['kind'], 'd': json.loads(r['data'])}
                    for r in self.index.rows(f['id']) if r['kind'] != 'link']
            items = assemble(recs, {}, set(), False)
            c = {'sig': sig, 'items': items, 'nfiles': 1}
            c.update(stats(items))
            c['title'] = '子代理：' + (c['first_prompt'][:40] or agent_id)
            self._content['agent:' + agent_id] = c
            return c

    def agent_owner(self, agent_id):
        """子代理属于哪个会话：它的记录在 <项目>/<会话的记录编号>/subagents/ 下。"""
        f = self.agents.get(agent_id)
        cli = os.path.basename(os.path.dirname(os.path.dirname(f['path']))) if f else None
        return next((s for s in self.sessions if cli in s.cli_ids), None)

    def find(self, key):
        """按页面编号前缀或标题片段找会话，返回匹配列表。"""
        key = key.strip().lower()
        exact = [s for s in self.sessions if s.page == key or s.id.lower() == key]
        if exact:
            return exact
        return [s for s in self.sessions
                if s.page.startswith(key) or key in self.content(s)['title'].lower()]

    def state(self, s=None):
        """内容指纹：变了就说明磁盘上有新记录。页面据此实时更新。"""
        # 应用里改了标题、归档了，认出了账号，也算有变化
        meta = lambda x: (x.record_title, x.archived, x.status['status_detail'], (self.account(x) or {}).get('name'))
        if s:
            sig = (self.signature(s), meta(s))
        else:
            sig = tuple((x.id, meta(x), tuple((f['id'], f['off']) for f in list(x.files) + list(x.agent_files)))
                        for x in self.sessions)
        return '%08x' % (zlib.crc32(repr(sig).encode('utf-8')) & 0xffffffff)

    def search(self, query, tools=False, per_session=8, src=None):
        """全文搜索 → [{session, n, hits}]，按会话最后活动时间倒序。src 只搜一种来源（claude / codex）。

        空格分开的每个词都要出现在同一条消息里。同一条消息的副本只算一次，记在最早的那个会话名下。
        """
        terms = [t.lower() for t in query.split()]
        if not terms:
            return []
        rows = [r for r in self.index.search(terms, tools) if r['file'] in self.owner
                and (not src or self.owner[r['file']].src == src)]
        rows.sort(key=lambda r: (self.owner[r['file']].created, r['ts'] or ''))
        seen, groups = set(), collections.OrderedDict()
        flat = lambda x: re.sub(r'\s+', ' ', x)
        for r in rows:
            if r['uuid'] in seen:
                continue
            seen.add(r['uuid'])
            if '"meta": 1' in (r['data'] or ''):
                continue
            text = clean_prompt(r['text'] or '') if r['kind'] != 'assistant' else (r['text'] or '')
            tool = (r['tool'] or '') if tools else ''
            low_text, low_tool = text.lower(), tool.lower()
            if not all(t in low_text or t in low_tool for t in terms):
                continue
            u = r['uuid'][:8]
            in_text = [t for t in terms if t in low_text]
            if len(in_text) == len(terms):
                who, anchor, body, term = ('asst' if r['kind'] == 'assistant' else 'user'), 'm-' + u, text, terms[0]
            else:
                term = [t for t in terms if t not in low_text][0]
                who, anchor, body = 'tool', ('t-' if r['kind'] == 'assistant' else 'r-') + u, tool
            i = body.lower().find(term)
            s = self.owner[r['file']]
            g = groups.setdefault(s.id, {'session': s, 'n': 0, 'hits': []})
            g['n'] += 1
            if len(g['hits']) < per_session:
                g['hits'].append({'ts': r['ts'], 'who': who, 'anchor': anchor, 'pre': flat(body[max(0, i - 40):i]),
                                  'hit': body[i:i + len(term)], 'post': flat(body[i + len(term):i + len(term) + 90])})
        out = list(groups.values())
        out.sort(key=lambda g: self.content(g['session'])['last'], reverse=True)
        return out
