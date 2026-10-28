"""账号与多份会话清单（multi-claude）、Codex 的记录、用量和费用、总的统计、实时更新用到的接口。"""
import base64
import json
import os
import socket
import sqlite3

from sessiontool import pricing, render, stats
from sessiontool.details import load_image, load_tool
from sessiontool.sessions import Catalog
from test_core import PNG, Case, asst, ts, user

TID = '01a181a5-33c8-7153-aeed-e07609968ed2'


def reply(uuid, parent, mid, text, n, sid, model='claude-opus-5-5', out=100, cw1h=500, effort='max', **extra):
    usage = {'input_tokens': 10, 'output_tokens': out, 'cache_read_input_tokens': 1000, 'cache_creation_input_tokens': cw1h,
             'cache_creation': {'ephemeral_1h_input_tokens': cw1h, 'ephemeral_5m_input_tokens': 0},
             'server_tool_use': {'web_search_requests': 0}, 'output_tokens_details': {'thinking_tokens': 7}}
    return asst(uuid, parent, text, n, sid, effort=effort, **dict(extra, message={
        'role': 'assistant', 'id': mid, 'model': model, 'content': [{'type': 'text', 'text': text}], 'usage': usage}))


def context(uuid, parent, n, sid, email=None, org=None):
    a = {'type': 'session_context', 'context': {'userEmail': "The user's email address is %s. Use it only to identify." % email}} \
        if email else {'type': 'credential_org', 'organizationUuid': org}
    return {'type': 'attachment', 'uuid': uuid, 'parentUuid': parent, 'timestamp': ts(n), 'sessionId': sid, 'attachment': a}


def cx(n, typ, payload):
    return {'timestamp': ts(n), 'type': typ, 'payload': payload}


def tokens(total, inp, cached, out):
    usage = {'input_tokens': inp, 'cached_input_tokens': cached, 'output_tokens': out, 'reasoning_output_tokens': 3,
             'total_tokens': total}
    return {'type': 'token_count', 'info': {'total_token_usage': dict(usage, total_tokens=total), 'last_token_usage': usage}}


class StoreCase(Case):
    def manifest(self, store, acct, org, sid, cli, **extra):
        d = os.path.join(store, acct, org)
        os.makedirs(d, exist_ok=True)
        r = {'sessionId': sid, 'cliSessionId': cli, 'title': sid, 'cwd': 'C:\\work\\proj', 'createdAt': 1, 'lastActivityAt': 1}
        r.update(extra)
        with open(os.path.join(d, sid + '.json'), 'w', encoding='utf-8') as f:
            json.dump(r, f)

    def open_with(self, stores, profile=None):
        if profile:
            with open(os.path.join(self.tmp.name, 'claude.json'), 'w', encoding='utf-8') as f:
                json.dump(profile, f)
        self.app = None
        from sessiontool.server import App
        from sessiontool.sources import Sources
        self.app = App(Sources(root=self.root, stores=stores, home=os.path.join(self.tmp.name, 'home'),
                               codex=os.path.join(self.tmp.name, 'codex'), profile=os.path.join(self.tmp.name, 'claude.json')))
        self.app.catalog.refresh(force=True)
        return self.app.catalog


class AccountTest(StoreCase):
    def test_accounts_come_from_the_store_layout_logins_and_transcripts(self):
        main, work = os.path.join(self.tmp.name, 'main'), os.path.join(self.tmp.name, 'work')
        self.write('aaaa1111', [user('u1', None, '第一个', 1, 'aaaa1111'), context('c1', 'u1', 2, 'aaaa1111', email='a@example.com'),
                                context('c2', 'c1', 3, 'aaaa1111', org='org-a')])
        self.write('bbbb2222', [user('u1', None, '第二个', 4, 'bbbb2222')])
        self.write('cccc3333', [user('u1', None, '终端里的', 5, 'cccc3333'), context('c1', 'u1', 6, 'cccc3333', email='b@example.com')])
        self.manifest(main, 'acct-a', 'org-a', 'local_s1', 'aaaa1111', lastActivityAt=10)
        # multi-claude 的配置是从普通应用复制来的：同一个会话两边都有，取最近活动的那份
        self.manifest(work, 'acct-a', 'org-a', 'local_s1', 'aaaa1111', lastActivityAt=5)
        self.manifest(work, 'acct-b', 'org-b', 'local_s2', 'bbbb2222', lastActivityAt=7)
        cat = self.open_with([(main, ''), (work, 'work')], {'oauthAccount': {'accountUuid': 'acct-b', 'emailAddress': 'b@example.com'}})
        by = {s.id: s for s in cat.sessions}
        self.assertEqual(sorted(by), ['file_cccc3333', 'local_s1', 'local_s2'])
        self.assertEqual((by['local_s1'].account, by['local_s1'].org, by['local_s1'].store), ('acct-a', 'org-a', ''))
        self.assertEqual((by['local_s2'].account, by['local_s2'].store), ('acct-b', 'work'))
        self.assertEqual(by['file_cccc3333'].account, 'acct-b')        # 记录里写着的邮箱认出了是哪个账号
        self.assertEqual(cat.accounts['acct-a']['name'], 'a')
        self.assertEqual((cat.accounts['acct-b']['name'], cat.accounts['acct-b']['email']), ('b', 'b@example.com'))
        info = json.loads(json.dumps(cat.info(by['local_s2'])))
        self.assertEqual((info['account']['email'], info['store']), ('b@example.com', 'work'))
        page = self.app.index_html()
        self.assertIn('data-acct="acct-a"', page)
        self.assertIn('<i></i>b</span>', page)                          # 标题旁的账号标签
        status, body, _ = self.serve()('/s/' + by['local_s1'].page)
        self.assertIn('class="acct"', body.decode())


class CodexTest(StoreCase):
    def rollout(self, lines, name=TID):
        d = os.path.join(self.tmp.name, 'codex', 'sessions', '2026', '01', '01')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'rollout-2026-01-01T00-00-00-%s.jsonl' % name), 'a', encoding='utf-8', newline='\n') as f:
            for r in lines:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def build(self):
        img = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
        patch = '*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** Add File: src/b.py\n+z\n*** End Patch'
        self.rollout([
            cx(0, 'session_meta', {'id': TID, 'cwd': 'C:\\work\\cxproj', 'originator': 'codex_cli_rs', 'cli_version': '0.21.0',
                                   'creator_account_id': 'acct-x', 'git': {'branch': 'main'}}),
            cx(1, 'response_item', {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': '<environment_context>\n  <cwd>C:\\work</cwd>\n</environment_context>'}]}),
            cx(1, 'response_item', {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': '把测试修好'}, {'type': 'input_image', 'image_url': img}]}),
            cx(1, 'event_msg', {'type': 'user_message', 'message': '把测试修好'}),
            cx(2, 'turn_context', {'cwd': 'C:\\work\\cxproj', 'model': 'gpt-5-codex', 'effort': 'high'}),
            cx(3, 'response_item', {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': '**先看测试**'}],
                                    'encrypted_content': 'xx'}),
            cx(4, 'response_item', {'type': 'function_call', 'name': 'shell', 'call_id': 'call_1',
                                    'arguments': json.dumps({'command': ['bash', '-lc', 'pytest -q'], 'workdir': 'C:\\work'})}),
            cx(5, 'response_item', {'type': 'function_call_output', 'call_id': 'call_1',
                                    'output': json.dumps({'output': '1 failed', 'metadata': {'exit_code': 1}})}),
            cx(5, 'event_msg', tokens(1050, 1000, 800, 50)),
            cx(5, 'event_msg', tokens(1050, 1000, 800, 50)),         # 同一次回复的事件记了两遍
            cx(6, 'response_item', {'type': 'custom_tool_call', 'name': 'apply_patch', 'call_id': 'call_2', 'input': patch}),
            cx(7, 'response_item', {'type': 'custom_tool_call_output', 'call_id': 'call_2', 'output': 'Success'}),
            cx(8, 'response_item', {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '测试修好了。'}]}),
            cx(8, 'event_msg', tokens(3150, 2000, 1500, 100)),
            cx(9, 'response_item', {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '再跑一次'}]}),
            cx(10, 'event_msg', {'type': 'turn_aborted', 'reason': 'interrupted'})])
        self.write('aaaa1111', [user('u1', None, 'Claude 这边也修好', 1, 'aaaa1111')])
        return self.open()

    def test_rollout_becomes_a_session_like_claude_ones(self):
        cat = self.build()
        s = [x for x in cat.sessions if x.src == 'codex'][0]
        c = cat.content(s)
        self.assertEqual((s.page, s.proj, s.model, s.effort, s.version), ('e0760996', 'cxproj', 'gpt-5-codex', 'high', '0.21.0'))
        self.assertEqual(c['title'], '把测试修好')
        self.assertEqual([it['kind'] for it in c['items']], ['user', 'think', 'tools', 'asst', 'user', 'stop'])
        prompt = c['items'][0]
        self.assertEqual(load_image(self.app.index, prompt['imgs'][0]), (PNG, 'image/png'))
        shell, patch = c['items'][2]['tools']
        self.assertEqual((shell['name'], shell['hint'], shell['error'], shell['preview']), ('shell', 'pytest -q', True, '1 failed'))
        self.assertEqual((patch['name'], patch['hint']), ('apply_patch', 'src/a.py'))
        self.assertEqual([p for p, _, _ in c['changed']], ['src/a.py', 'src/b.py'])
        d = load_tool(self.app.index, self.app.sources, shell['use'], shell['res'])
        self.assertEqual((d['input']['command'], d['result'], d['error']), (['bash', '-lc', 'pytest -q'], '1 failed', True))
        u = c['usage']
        self.assertEqual((u['n'], u['input'], u['cache_read'], u['output']), (2, 700, 2300, 150))
        self.assertAlmostEqual(u['cost'], (700 * 1.25 + 2300 * 0.125 + 150 * 10) / 1e6, places=6)
        info = cat.info(s)
        self.assertEqual((info['resume'], info['link'], info['id']), ('codex resume ' + TID, None, None))
        page = render.session_page(s, c, render.ServerMode(), info=info)
        self.assertIn('<b>Codex</b>', page)
        self.assertEqual([g['session'].src for g in cat.search('修好')], ['codex', 'claude'])
        self.assertEqual([g['session'].src for g in cat.search('修好', src='claude')], ['claude'])
        self.assertIn('codex', render.session_markdown(s, c).lower())

    def test_thread_names_archive_and_the_logged_in_email(self):
        db = os.path.join(self.tmp.name, 'codex', 'state_5.sqlite')
        os.makedirs(os.path.dirname(db), exist_ok=True)
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE threads(id TEXT, title TEXT, name TEXT, archived INT, model TEXT, creator_account_id TEXT)')
        con.execute('INSERT INTO threads VALUES(?,?,?,?,?,?)', (TID, '# 很长的首问\n第二行', None, 1, 'gpt-6.1-sol', 'acct-x'))
        con.commit()
        con.close()
        claims = base64.urlsafe_b64encode(json.dumps({'email': 'me@example.com', 'https://api.openai.com/auth': {
            'chatgpt_account_id': 'acct-x'}}).encode()).decode().rstrip('=')
        with open(os.path.join(self.tmp.name, 'codex', 'auth.json'), 'w', encoding='utf-8') as f:
            json.dump({'tokens': {'id_token': 'h.%s.s' % claims, 'access_token': 'secret'}}, f)
        cat = self.build()
        s = [x for x in cat.sessions if x.src == 'codex'][0]
        self.assertEqual((cat.content(s)['title'], s.archived, s.model), ('很长的首问', True, 'gpt-6.1-sol'))
        self.assertEqual(cat.account(s)['name'], 'me')

    def test_rollout_read_in_pieces_gives_the_same_result(self):
        cat = self.build()
        s = [x for x in cat.sessions if x.src == 'codex'][0]
        before = [it['kind'] for it in cat.content(s)['items']]
        self.rollout([cx(11, 'response_item', {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '又跑了一次'}]}),
                      cx(12, 'event_msg', tokens(4000, 800, 0, 50))])
        cat.refresh(force=True)
        s = [x for x in cat.sessions if x.src == 'codex'][0]
        c = cat.content(s)
        self.assertEqual([it['kind'] for it in c['items']], before + ['asst'])
        self.assertEqual(c['usage']['n'], 3)
        fresh = Catalog(self.app.index)               # 增量合并的结果和从头合并的一样
        fresh.refresh(force=True)
        self.assertEqual([(it['kind'], it.get('text')) for it in fresh.content(fresh.by_page[s.page])['items']],
                         [(it['kind'], it.get('text')) for it in c['items']])


class UsageTest(StoreCase):
    def build(self):
        self.write('pppp0001', [user('p1', None, '原会话的问题', 1, 'pppp0001'),
                                reply('p2', 'p1', 'msg_p', '原会话的回答', 2, 'pppp0001', cw1h=0)])
        self.write('ffff0002', [user('p1', None, '原会话的问题', 1, 'pppp0001'),
                                reply('p2', 'p1', 'msg_p', '原会话的回答', 2, 'pppp0001', cw1h=0),
                                user('f1', 'p2', '复刻里的问题', 10, 'ffff0002'),
                                reply('f2', 'f1', 'msg_f', '复刻里的回答', 11, 'ffff0002', effort='high')])
        sub = os.path.join(self.proj, 'ffff0002', 'subagents')
        os.makedirs(sub)
        with open(os.path.join(sub, 'agent-x1.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
            for r in (user('a1', None, '去查', 12, 'ffff0002', isSidechain=True),
                      reply('a2', 'a1', 'msg_a', '查到了', 13, 'ffff0002', model='claude-haiku-5-5', isSidechain=True)):
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        self.session('local_parent', 'pppp0001')
        self.session('local_fork', 'ffff0002', forkedFromSessionId='local_parent')
        app_dir = os.path.dirname(self.store)
        with open(os.path.join(app_dir, 'plan-usage-history.json'), 'w', encoding='utf-8') as f:
            json.dump({'version': 2, 'samples': [{'t': 1, 'org': 'org-z', 'u': {'fh': 10, 'sd': 20}},
                                                 {'t': 2, 'org': 'org-z', 'u': {'fh': 30, 'sd': 40}}]}, f)
        return self.open()

    def test_a_fork_pays_for_its_own_replies_and_its_subagents(self):
        cat = self.build()
        _, fork = self.content(cat, 'local_fork')
        _, parent = self.content(cat, 'local_parent')
        u = fork['usage']
        self.assertEqual((u['n'], parent['usage']['n']), (2, 1))      # 复刻点之前的那次回复算原会话的
        opus = (10 * 4 + 100 * 20 + 1000 * 0.2 + 500 * 8) / 1e6
        haiku = (10 * 0.1 + 100 * 0.5 + 1000 * 0.01 + 500 * 0.2) / 1e6
        self.assertAlmostEqual(u['cost'], opus + haiku, places=6)
        self.assertEqual({m['name']: m['n'] for m in u['models']}, {'Opus 5.5': 1, 'Haiku 5.5': 1})
        self.assertEqual({e['effort']: e['n'] for e in u['efforts']}, {'high': 1, 'max': 1})
        self.assertAlmostEqual(u['rate'], 2000 / (20 + 2000 + 1000))
        self.assertEqual(u['thinking'], 14)
        s = cat.by_page[[x for x in cat.sessions if x.id == 'local_fork'][0].page]
        page = render.session_page(s, fork, render.ServerMode(), info=cat.info(s))
        self.assertIn(render.money(u['cost']), page)

    def test_totals_count_each_reply_once(self):
        cat = self.build()
        d = stats.compute(cat)
        self.assertEqual(d['total']['n'], 3)
        self.assertEqual(sorted(m['name'] for m in d['models']), ['Haiku 5.5', 'Opus 5.5'])
        self.assertEqual(d['days'][0]['d'], '2026-01-01')
        self.assertEqual(sum(day['n'] for day in d['days']), 3)
        self.assertEqual(d['active_days'], 1)
        self.assertEqual(sum(map(sum, d['hours'])), 3)
        self.assertEqual(d['prompts'], 2)
        self.assertEqual([(q['org'], q['five_hour'], q['seven_day']) for q in d['quota']], [('org-z', 30, 40)])
        self.assertEqual(stats.compute(cat, src='codex')['total']['n'], 0)
        self.assertEqual(stats.compute(cat, days=7)['total']['n'], 0)       # 记录都在 2026-01-01


class PricingTest(StoreCase):
    def test_model_ids_and_tiers(self):
        self.assertEqual(pricing.key('claude-opus-4-1-20250805'), 'claude-opus-4-1')
        self.assertEqual(pricing.key('claude-opus-4-20250514'), 'claude-opus-4')
        self.assertEqual(pricing.key('claude-fable-5-1[1m]'), 'claude-fable-5-1')
        self.assertEqual(pricing.key('us.anthropic.claude-sonnet-4-5-20250929-v1:0'), 'claude-sonnet-4-5')
        self.assertEqual(pricing.key('gpt-5-codex'), 'gpt-5-codex')
        self.assertIsNone(pricing.key('claude-opus-4-9'))
        self.assertEqual([pricing.model_name(m) for m in ('claude-opus-5-5', 'claude-3-5-haiku-20241022', 'claude-opus-4-20250514', 'gpt-6.1-sol')],
                         ['Opus 5.5', 'Haiku 3.5', 'Opus 4', 'gpt-6.1-sol'])
        small = pricing.parts('claude-haiku-5-5', '', 1000, 0, 0, 0, 0, 0)
        big = pricing.parts('claude-haiku-5-5', '', 150000, 0, 0, 0, 0, 0)
        self.assertAlmostEqual(big[0] / 150, small[0] * 5)              # 提示词超过 10 万 token 换一档
        self.assertAlmostEqual(sum(pricing.parts('claude-opus-5-5', 'fast', 0, 1000, 0, 0, 0, 0)), 1000 * 40 / 1e6)
        self.assertEqual(pricing.parts('claude-opus-5-5', '', 0, 0, 0, 0, 0, 3)[4], 0.03)
        home = os.path.join(self.tmp.name, 'prices')
        os.makedirs(home)
        with open(os.path.join(home, 'prices.json'), 'w', encoding='utf-8') as f:
            json.dump({'my-model': [1, 2, 0.1]}, f)
        try:
            pricing.configure(home)
            self.assertEqual(pricing.parts('my-model', '', 1e6, 1e6, 1e6, 1e6, 0, 0)[:4], (1, 2, 0.1, 1))
        finally:
            pricing.configure(os.path.join(self.tmp.name, 'none'))


class LiveTest(StoreCase):
    def test_blocks_endpoint_sends_only_what_changed(self):
        self.write('aaaa1111', [user('u1', None, '第一轮', 1, 'aaaa1111'), asst('a1', 'u1', '答一', 2, 'aaaa1111'),
                                user('u2', 'a1', '第二轮', 3, 'aaaa1111'), asst('a2', 'u2', '答二', 4, 'aaaa1111')])
        cat = self.open()
        s = cat.sessions[0]
        get = self.serve()
        port = self.port

        def post(keys):
            import http.client
            con = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            con.request('POST', '/api/blocks', json.dumps({'page': s.page, 'keys': keys}),
                        {'Host': '127.0.0.1:%d' % port, 'Content-Type': 'application/json'})
            r = con.getresponse()
            body = json.loads(r.read())
            con.close()
            return body

        first = post([])
        self.assertEqual((first['start'], first['count'], len(first['blocks'])), (0, 3, 3))
        keys = [b.split('data-k="')[1][:8] for b in first['blocks']]
        self.assertEqual(post(keys)['blocks'], [])
        self.write('aaaa1111', [user('u3', 'a2', '第三轮', 5, 'aaaa1111')], mode='a')
        cat.refresh(force=True)
        later = post(keys)
        self.assertEqual((later['start'], later['count'], len(later['blocks'])), (3, 4, 1))
        self.assertIn('第三轮', later['blocks'][0])
        s = cat.by_page[s.page]                     # 同步以后会话对象是新建的
        self.assertEqual(later['sig'], cat.state(s))
        self.assertIn('第三轮', later['toc'])
        # 事件流一连上就报当前的指纹
        sock = socket.create_connection(('127.0.0.1', port), timeout=10)
        sock.sendall(('GET /api/live?page=%s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n' % (s.page, port)).encode())
        data = b''
        while b'\n\n' not in data.split(b'\r\n\r\n', 1)[-1]:
            data += sock.recv(4096)
        sock.close()
        self.assertIn(b'text/event-stream', data)
        self.assertIn(('event: hello\ndata: {"sig": "%s"}' % cat.state(s)).encode(), data)
        self.assertEqual(get('/stats')[0], 200)
        d = json.loads(get('/api/stats?days=0')[1])
        self.assertEqual((d['prompts'], d['range']['from']), (3, '2026-01-01'))
        self.assertEqual(get('/api/live?page=nope')[0], 404)
