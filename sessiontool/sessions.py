"""应用会话 ↔ 记录文件：合并、去重、识别复刻与改写分支，整理成可渲染的条目。

磁盘上的实际情况：
- 一个应用会话可能对应多份 .jsonl（压缩或重启后新建），新文件会带着旧消息的副本（uuid 不变）。
- 复刻出的会话，记录从父会话最近一次压缩处开始；更早的历史只在父会话的文件里。
- 回复进行中追加的消息记在 attachment 行里，不是 user 行。
"""
import collections
import json
import os
import re
import threading
import time

AUTO_CONTINUE = 'I hit my usage limit while you were working'
INTERRUPT = re.compile(r'\[Request interrupted by user[^\]]*\]')
NOTE_PREFIX = ('<task-notification', '<ci-monitor-event')


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

    判据：同一个父节点下有两条以上你亲手发的消息，最晚的一条是现行的，其余各自带着的后续都是旧分支。
    并行工具调用也会产生分叉，但分叉的不是用户消息，不会被误判。
    """
    by = {r['uuid']: r for r in recs if r['uuid']}
    children = collections.defaultdict(list)
    for u, p in links.items():
        if p:
            children[p].append(u)
    dead = {}
    for kids in children.values():
        prompts = [by[k] for k in kids if k in by and is_prompt(by[k])]
        if len(prompts) < 2:
            continue
        prompts.sort(key=lambda r: r['ts'] or '')
        keep = prompt_text(prompts[-1])
        for r in prompts[:-1]:
            if prompt_text(r) == keep:
                continue                    # 原样重发，交给 assemble 里的去重
            stack = [r['uuid']]
            while stack:
                u = stack.pop()
                if u not in dead:
                    dead[u] = r['uuid']
                    stack.extend(children.get(u, ()))
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
            body = clean_prompt(d['b'][0][1])
            if body and not body.startswith(NOTE_PREFIX):
                prompt = {'kind': 'user', 'ts': ts, 'u': u, 'text': body, 'imgs': [], 'queued': True}
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
                        tu.update(res='%s.%d' % (ref, blk[2]), preview=blk[3], size=blk[4], nimg=blk[5], error=blk[6], ru=u)
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
                    tu = {'name': blk[2], 'hint': blk[3], 'use': '%s.%d' % (ref, blk[4]), 'res': None, 'preview': '',
                          'size': 0, 'nimg': 0, 'error': False, 'u': u, 'ru': ''}
                    tools[blk[1]] = tu
                    if target and target[-1]['kind'] == 'tools':
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
    return {'n_user': len(prompts), 'n_asst': sum(1 for it in items if it['kind'] == 'asst'),
            'n_tools': sum(len(it['tools']) for it in items if it['kind'] == 'tools'),
            'n_branch': sum(1 for it in items if it['kind'] == 'branch'),
            'first': min(stamps) if stamps else '', 'last': max(stamps) if stamps else '',
            'first_prompt': prompts[0]['text'][:120].replace('\n', ' ') if prompts else ''}


class Session:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Catalog:
    def __init__(self, index):
        self.index = index
        self.sources = index.sources
        self.lock = threading.RLock()
        self.checked = 0
        self.sessions, self.by_page, self.owner = [], {}, {}
        self._merged, self._content = {}, {}

    def refresh(self, progress=None, force=False):
        """与磁盘同步。两秒内的重复调用直接跳过。"""
        with self.lock:
            if not force and time.time() - self.checked < 2:
                return
            self.index.sync(progress)
            self._build()
            self.checked = time.time()

    def _build(self):
        files = {f['cli']: f for f in self.index.files()}
        raw, used = {}, set()
        for sid, r in self.sources.app_sessions().items():
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
        for sid in sorted(raw):
            r, ids = raw[sid]
            own = [files[i] for i in ids if i in files]
            if not own:
                continue
            short = re.sub(r'^(local_|file_)', '', sid).replace('-', '')
            n = 8
            while short[:n] in taken and n < len(short):
                n += 1
            taken.add(short[:n])
            cwd = r.get('cwd') or own[-1]['cwd'] or ''
            sessions[sid] = Session(
                id=sid, page=short[:n], record_title=r.get('title'), file_title=own[-1]['title'], cwd=cwd,
                proj=os.path.basename(cwd.rstrip('\\/')) or cwd or '（未知）', archived=bool(r.get('isArchived')),
                created=r.get('createdAt') or 0, parent_id=r.get('forkedFromSessionId'), cli_ids=ids, files=own,
                orphan=bool(r.get('_orphan')), parent=None, size=sum(f['size'] for f in own))
        for s in sessions.values():
            p = sessions.get(s.parent_id)
            s.parent = p if p is not s else None
        self.sessions = list(sessions.values())
        self.by_page = {s.page: s for s in self.sessions}
        self.owner = {}
        for s in sorted(self.sessions, key=lambda s: s.created):
            for f in s.files:
                self.owner.setdefault(f['id'], s)

    def lineage(self, s, depth=0):
        base = self.lineage(s.parent, depth + 1) if s.parent and depth < 8 else []
        have = {f['id'] for f in base}
        return base + [f for f in s.files if f['id'] not in have]

    def signature(self, s):
        return tuple((f['id'], f['off']) for f in self.lineage(s))

    def merged(self, s, depth=0):
        """(记录, 父子关系)：父会话里更早的部分 + 自己的各份记录，去重后按时间排序。"""
        sig = self.signature(s)
        hit = self._merged.get(s.id)
        if hit and hit[0] == sig:
            return hit[1], hit[2]
        own, links = [], {}
        for f in s.files:
            for row in self.index.rows(f['id']):
                if row['kind'] == 'link':
                    links.setdefault(row['uuid'], row['parent'])
                else:
                    own.append({'file': row['file'], 'off': row['off'], 'uuid': row['uuid'], 'parent': row['parent'],
                                'ts': row['ts'] or '', 'sid': row['sid'], 'kind': row['kind'], 'raw': row['data'],
                                'd': json.loads(row['data'])})
        base = []
        if s.parent and depth < 8:
            precs, plinks = self.merged(s.parent, depth + 1)
            first = min((r['ts'] for r in own if r['ts']), default='')
            base = [r for r in precs if r['ts'] < first]
            for u, p in plinks.items():
                links.setdefault(u, p)
        out, seen_u, seen_c = [], set(), set()
        for r in base + own:
            key = (r['kind'], r['ts'], r['raw'])
            if (r['uuid'] and r['uuid'] in seen_u) or key in seen_c:
                continue
            seen_u.add(r['uuid'])
            seen_c.add(key)
            links.setdefault(r['uuid'], r['parent'])
            out.append(r)
        out.sort(key=lambda r: r['ts'])
        self._merged[s.id] = (sig, out, links)
        return out, links

    def content(self, s):
        """一个会话整理好的条目和统计，按文件状态缓存。"""
        with self.lock:
            sig = self.signature(s)
            c = self._content.get(s.id)
            if c and c['sig'] == sig:
                return c
            recs, links = self.merged(s)
            items = assemble(recs, links, set(s.cli_ids), bool(s.parent))
            c = {'sig': sig, 'items': items}
            c.update(stats(items))
            c['title'] = (s.record_title or s.file_title or c['first_prompt'][:40] or '（无标题）').replace('\n', ' ')
            c['nfiles'] = len(self.lineage(s))
            self._content[s.id] = c
            return c

    def find(self, key):
        """按页面编号前缀或标题片段找会话，返回匹配列表。"""
        key = key.strip().lower()
        exact = [s for s in self.sessions if s.page == key or s.id.lower() == key]
        if exact:
            return exact
        return [s for s in self.sessions
                if s.page.startswith(key) or key in self.content(s)['title'].lower()]

    def search(self, query, tools=False, per_session=8):
        """全文搜索 → [{session, n, hits}]，按会话最后活动时间倒序。同一条消息的副本只算一次。"""
        rows = [r for r in self.index.search(query, tools) if r['file'] in self.owner]
        rows.sort(key=lambda r: (self.owner[r['file']].created, r['ts'] or ''))
        lq, seen, groups = query.lower(), set(), collections.OrderedDict()
        for r in rows:
            if r['uuid'] in seen:
                continue
            seen.add(r['uuid'])
            data = r['data'] or ''
            if '"meta": 1' in data:
                continue
            text = clean_prompt(r['text'] or '') if r['kind'] != 'assistant' else (r['text'] or '')
            u = r['uuid'][:8]
            i = text.lower().find(lq)
            if i >= 0:
                who, anchor, src = ('asst' if r['kind'] == 'assistant' else 'user'), 'm-' + u, text
            elif tools and (r['tool'] or '').lower().find(lq) >= 0:
                src = r['tool']
                i = src.lower().find(lq)
                who, anchor = 'tool', ('t-' if r['kind'] == 'assistant' else 'r-') + u
            else:
                continue
            s = self.owner[r['file']]
            g = groups.setdefault(s.id, {'session': s, 'n': 0, 'hits': []})
            g['n'] += 1
            if len(g['hits']) < per_session:
                flat = lambda x: re.sub(r'\s+', ' ', x)
                g['hits'].append({'ts': r['ts'], 'who': who, 'anchor': anchor, 'pre': flat(src[max(0, i - 40):i]),
                                  'hit': src[i:i + len(query)], 'post': flat(src[i + len(query):i + len(query) + 90])})
        out = list(groups.values())
        out.sort(key=lambda g: self.content(g['session'])['last'], reverse=True)
        return out
