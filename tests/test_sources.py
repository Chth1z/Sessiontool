"""账号与多份会话清单（multi-claude）、Codex 与 Gemini 的记录、用量和费用、总的统计、实时更新用到的接口。"""
import base64
import json
import os
import socket
import sqlite3

from sessiontool import gemini, pricing, render, stats
from sessiontool.details import load_image, load_tool
from sessiontool.export import export_html
from sessiontool.sessions import Catalog
from test_core import PNG, Case, asst, ts, user

TID = '01a181a5-33c8-7153-aeed-e07609968ed2'
GID = '71727329-fc51-4de2-a5e8-1805a6dcf1df'
GSUB = 'aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb'
GCLI = 'cccccccc-2222-4333-8444-dddddddddddd'


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
                               codex=os.path.join(self.tmp.name, 'codex'), gemini=os.path.join(self.tmp.name, 'gemini'),
                               profile=os.path.join(self.tmp.name, 'claude.json')))
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
        self.assertIn('details class="menu acct-dd" id="ac"', page)
        self.assertIn('class="modes" data-page="list"', page)
        self.assertLess(page.index('id="ac"'), page.index('id="pj"'))
        self.assertLess(page.index('id="pj"'), page.index('id="ar"'))
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
        self.assertIn('<details class="fold think" open>', page)
        self.assertIn('<main><div class="page">', page)
        idx_html = self.app.index_html()
        self.assertIn('class="seg srcs"', idx_html)
        self.assertIn('class="src-all" data-s="all"', idx_html)
        self.assertIn('<div class="side-h">账号</div><details class="menu acct-dd" id="ac">', idx_html)
        self.assertIn('<main><div class="page">', idx_html)
        stats_html = render.stats_page(cat.sessions)
        self.assertIn('class="modes" data-page="stats"', stats_html)
        self.assertIn('<details class="menu acct-dd" id="acct">', stats_html)
        self.assertNotIn('<select id="acct">', stats_html)
        self.assertIn('<main><div class="page">', stats_html)
        self.assertIn('id="digest"', stats_html)
        self.assertNotIn('side-note', stats_html)
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

    def test_codex_titles_injected_context_and_fast_tier(self):
        tid2 = '01a181a5-33c8-7153-aeed-e07609968ed3'
        codex_dir = os.path.join(self.tmp.name, 'codex')
        os.makedirs(codex_dir, exist_ok=True)
        with open(os.path.join(codex_dir, 'session_index.jsonl'), 'w', encoding='utf-8') as f:
            f.write(json.dumps({'id': TID, 'thread_name': '索引里的自定义标题'}) + '\n')
        db = os.path.join(codex_dir, 'state_5.sqlite')
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE threads(id TEXT, title TEXT, name TEXT, archived INT)')
        # SQLite 里的 name 是空字符串时不能盖掉 session_index.jsonl 里的非空名字；注入文本也不能拿来当标题
        con.execute('INSERT INTO threads VALUES(?,?,?,?)',
                    (TID, '<permissions instructions>\nallow all\n</permissions instructions>', '', 0))
        con.execute('INSERT INTO threads VALUES(?,?,?,?)',
                    (tid2, '<permissions instructions>\nsandbox\n</permissions instructions>', '', 0))
        con.commit()
        con.close()
        self.rollout([
            cx(0, 'session_meta', {'id': TID, 'cwd': 'C:\\work\\cxproj'}),
            cx(1, 'response_item', {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': '<permissions instructions>\nallow all\n</permissions instructions>'}]}),
            cx(2, 'response_item', {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'Approved command prefix saved: `git status`'}]}),
            cx(3, 'response_item', {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '/model'}]}),
            cx(4, 'response_item', {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '修复标题显示'}]}),
            cx(5, 'turn_context', {'cwd': 'C:\\work\\cxproj', 'model': 'gpt-6-astra', 'effort': 'high', 'service_tier': 'priority'}),
            cx(6, 'event_msg', tokens(1100, 1000, 800, 100))], name=TID)
        self.rollout([
            cx(0, 'session_meta', {'id': tid2, 'cwd': 'C:\\work\\cxproj'}),
            cx(1, 'response_item', {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': '<permissions instructions>\nsandbox\n</permissions instructions>'}]}),
            cx(2, 'response_item', {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '/status'}]}),
            cx(3, 'response_item', {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '真正的提问内容'}]})],
            name=tid2)
        cat = self.open()
        by = {s.id: s for s in cat.sessions}
        c1, c2 = cat.content(by['codex_' + TID]), cat.content(by['codex_' + tid2])
        self.assertEqual((c1['title'], c1['first_prompt']), ('索引里的自定义标题', '修复标题显示'))
        self.assertEqual(self.texts(c1['items'], 'user'), ['/model', '修复标题显示'])
        # gpt-6-astra 在 priority (fast) 档位下按 2 倍计价：(200*10 + 800*1 + 100*50) * 2 / 1e6
        self.assertAlmostEqual(c1['usage']['cost'], (200 * 10 + 800 * 1 + 100 * 50) * 2 / 1e6, places=8)
        self.assertEqual((c2['title'], c2['first_prompt']), ('真正的提问内容', '真正的提问内容'))
        self.rollout([{'timestamp': ts(4), 'type': 'thread_name', 'payload': {'thread_name': '流式改名'}}], name=tid2)
        cat.refresh(force=True)
        self.assertEqual(cat.content({s.id: s for s in cat.sessions}['codex_' + tid2])['title'], '流式改名')


class GeminiTest(StoreCase):
    def gwrite(self, cid, steps, flavor='antigravity', mode='w'):
        logs = os.path.join(self.tmp.name, 'gemini', flavor, 'brain', cid, '.system_generated', 'logs')
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, 'transcript_full.jsonl'), mode, encoding='utf-8', newline='\n') as f:
            for r in steps:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def gdb(self, flavor, rows, fts_rows=()):
        db = os.path.join(self.tmp.name, 'gemini', flavor, 'conversation_summaries.db')
        os.makedirs(os.path.dirname(db), exist_ok=True)
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE conversation_summaries(conversation_id TEXT PRIMARY KEY, title TEXT, preview TEXT, '
                    'workspace_uris TEXT, project_id TEXT, status TEXT, source TEXT, agent_name TEXT, '
                    'parent_conversation_id TEXT, nesting_depth INT, killed INT)')
        con.executemany('INSERT INTO conversation_summaries VALUES(?,?,?,?,?,?,?,?,?,?,?)', rows)
        con.execute('CREATE TABLE conversations_fts(conversation_id TEXT, archived INT)')
        con.executemany('INSERT INTO conversations_fts VALUES(?,?)', fts_rows)
        con.commit()
        con.close()

    def build(self):
        ag_root = os.path.join(self.tmp.name, 'gemini', 'antigravity')
        pic_u = os.path.join(ag_root, 'brain', GID, 'user_pic.png')
        pic_t = os.path.join(ag_root, 'brain', GID, 'shot.png')
        os.makedirs(os.path.dirname(pic_u), exist_ok=True)
        for p in (pic_u, pic_t):
            with open(p, 'wb') as f:
                f.write(PNG)
        outside = os.path.join(self.tmp.name, 'outside.png')
        with open(outside, 'wb') as f:
            f.write(PNG)
        pic_u_uri = 'file:///' + pic_u.replace('\\', '/').lstrip('/')
        self.gwrite(GID, [
            {'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE', 'created_at': ts(1),
             'content': '<USER_REQUEST>\n帮我把 Gemini 接入进来\n</USER_REQUEST>\n'
                        '<ADDITIONAL_METADATA>\nThe current local time is: 2026-11-23.\n</ADDITIONAL_METADATA>\n'
                        '<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection` from None to Gemini 3.8 Flash (High).\n</USER_SETTINGS_CHANGE>',
             'media': [{'mime_type': 'image/png', 'uri': pic_u_uri}, {'mime_type': 'image/png', 'uri': outside}]},
            {'step_index': 1, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(2),
             'input_tokens': 1000, 'cache_read_tokens': 2000, 'output_tokens': 100,
             'thinking': '先看文件并调用子代理',
             'tool_calls': [
                 {'name': 'edit_file', 'args': {'Path': 'd:\\work\\gmproj\\app.py', 'Target': 'a', 'Replacement': 'b'}},
                 {'name': 'run_command', 'args': {'CommandLine': 'pytest -q', 'toolSummary': '运行测试'}},
                 {'name': 'invoke_subagent', 'args': {'Role': 'Code Researcher', 'TypeName': 'research', 'Prompt': '查一下'}}]},
            {'step_index': 2, 'source': 'MODEL', 'type': 'GENERIC', 'status': 'DONE', 'created_at': ts(3),
             'content': 'Created At: 2026-11-23T21:00:00+08:00\nCompleted At: 2026-11-23T21:00:01+08:00\nEdited app.py'},
            {'step_index': 3, 'source': 'MODEL', 'type': 'GENERIC', 'status': 'ERROR', 'created_at': ts(4),
             'content': 'Created At: 2026-11-23T21:00:01+08:00\nCompleted At: 2026-11-23T21:00:02+08:00\n1 failed',
             'error': 'exit code 1', 'media': [{'mime_type': 'image/png', 'uri': pic_t}]},
            {'step_index': 4, 'source': 'MODEL', 'type': 'GENERIC', 'status': 'DONE', 'created_at': ts(5),
             'content': 'Created At: 2026-11-23T21:00:02+08:00\nCompleted At: 2026-11-23T21:00:03+08:00\nLaunched subagent conversationId: %s' % GSUB},
            {'step_index': 5, 'source': 'SYSTEM', 'type': 'SYSTEM_MESSAGE', 'status': 'DONE', 'created_at': ts(6),
             'content': 'The following is a <SYSTEM_MESSAGE>\n子代理已完成\n</SYSTEM_MESSAGE>'},
            {'step_index': 6, 'source': 'SYSTEM', 'type': 'CHECKPOINT', 'status': 'DONE', 'created_at': ts(7),
             'content': '压缩后的上下文摘要'},
            {'step_index': 7, 'source': 'SYSTEM', 'type': 'ERROR_MESSAGE', 'status': 'ERROR', 'created_at': ts(8),
             'error': '网络短暂抖动'},
            {'step_index': 8, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(9),
             'model': 'gemini-4-neon-xhigh', 'input_tokens': 500, 'cache_read_tokens': 10000, 'output_tokens': 200,
             'content': 'Gemini 已经接好了。'},
        ])
        self.gwrite(GSUB, [
            {'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE', 'created_at': ts(5),
             'content': '<USER_REQUEST>\n子代理查一下配置\n</USER_REQUEST>'},
            {'step_index': 1, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(6),
             'model': 'gemini-4-hydrogen-tiered-high', 'input_tokens': 400, 'cache_read_tokens': 1000, 'output_tokens': 80,
             'content': '子代理发现关键线索'},
        ])
        self.gwrite(GCLI, [
            {'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE', 'created_at': ts(10),
             'content': '<USER_REQUEST>\n命令行跑一次\n</USER_REQUEST>'},
            {'step_index': 1, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(11),
             'model': 'gemini-4-neon-high', 'input_tokens': 100, 'cache_read_tokens': 0, 'output_tokens': 20,
             'content': '命令行完成'},
        ], flavor='antigravity-cli')
        self.gdb('antigravity-cli', [
            (GID, '', '', '', '', '', '', '', '', 0, 0),
        ])
        self.gdb('antigravity', [
            (GID, '接入 Gemini 支持', '', json.dumps(['file:///d%3A/work/gmproj']), 'p-main', 'CASCADE_RUN_STATUS_IDLE', '', '', '', 0, 0),
            (GSUB, 'Subagent research', '', '', '', 'CASCADE_RUN_STATUS_IDLE', '', 'research', GID, 1, 0),
            (GCLI, 'CLI 归档会话', '', json.dumps(['file:///d%3A/work/cli']), 'default-cli-project', 'CASCADE_RUN_STATUS_IDLE',
             'CORTEX_TRAJECTORY_SOURCE_CLI', '', '', 0, 0),
        ], fts_rows=[(GID, 0), (GCLI, 1)])
        # 同时放一个 Claude 和一个 Codex 会话，验证三来源并存
        self.write('aaaa1111', [user('u1', None, 'Claude 这边接入', 1, 'aaaa1111')])
        d = os.path.join(self.tmp.name, 'codex', 'sessions', '2026', '01', '01')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'rollout-2026-01-01T00-00-00-%s.jsonl' % TID), 'w', encoding='utf-8', newline='\n') as f:
            for r in (cx(0, 'session_meta', {'id': TID, 'cwd': 'C:\\work\\cxproj'}),
                      cx(1, 'response_item', {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Codex 这边接入'}]})):
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        return self.open()

    def test_antigravity_transcripts_subagents_images_and_three_sources(self):
        cat = self.build()
        gms = {s.cli_ids[0]: s for s in cat.sessions if s.src == 'gemini'}
        self.assertEqual(sorted(gms), sorted([GID, GCLI]))              # 子代理不列作顶层会话
        s, cli_s = gms[GID], gms[GCLI]
        c = cat.content(s)
        self.assertEqual((s.proj, s.archived, s.origin, s.model, s.effort), ('gmproj', False, 'antigravity', 'gemini-4-neon', 'xhigh'))
        self.assertEqual((cli_s.proj, cli_s.archived, cli_s.origin), ('cli', True, 'antigravity-cli'))
        self.assertEqual(c['title'], '接入 Gemini 支持')
        self.assertEqual(c['first_prompt'], '帮我把 Gemini 接入进来')
        self.assertEqual([it['kind'] for it in c['items']], ['user', 'think', 'tools', 'note', 'compact', 'summary', 'notice', 'asst'])
        # 用户图片在 ~/.gemini 内允许读取，目录外的图片拒绝读取
        prompt = c['items'][0]
        self.assertEqual(load_image(self.app.index, prompt['imgs'][0]), (PNG, 'image/png'))
        self.assertIsNone(load_image(self.app.index, prompt['imgs'][1]))
        # 工具调用配对、修改过的文件、失败输出、截图与子代理链接
        ed, cmd, sub_call = c['items'][2]['tools']
        self.assertEqual((ed['name'], ed['hint'], ed['preview']), ('edit_file', 'd:\\work\\gmproj\\app.py', 'Edited app.py'))
        self.assertEqual([p for p, _, _ in c['changed']], ['d:\\work\\gmproj\\app.py'])
        self.assertEqual((cmd['name'], cmd['hint'], cmd['error'], cmd['nimg']), ('run_command', '运行测试', True, 1))
        self.assertEqual(sub_call['agent'], GSUB)
        d = load_tool(self.app.index, self.app.sources, cmd['use'], cmd['res'])
        self.assertTrue(d['error'])
        self.assertIn('1 failed', d['result'])
        self.assertIn('exit code 1', d['result'])
        self.assertEqual(load_image(self.app.index, d['images'][0]), (PNG, 'image/png'))
        # 用量包含主会话两步（老版本由 USER_SETTINGS_CHANGE 补出的 3.8 Flash + 4 Neon）以及子代理的 4 Hydrogen
        u = c['usage']
        self.assertEqual((u['n'], u['input'], u['cache_read'], u['output']), (3, 1900, 13000, 380))
        expected = ((1000 * 1.5 + 2000 * 0.15 + 100 * 7.5)
                    + (500 * 3 + 10000 * 0.15 + 200 * 15)
                    + (400 * 1.5 + 1000 * 0.075 + 80 * 7.5)) / 1e6
        self.assertAlmostEqual(u['cost'], expected, places=7)
        self.assertEqual({m['name'] for m in u['models']}, {'Gemini 3.8 Flash', 'Gemini 4 Neon', 'Gemini 4 Hydrogen'})
        self.assertEqual({e['effort'] for e in u['efforts']}, {'high', 'xhigh'})
        # 详情、子代理页、独立导出、搜索与统计
        info = cat.info(s)
        self.assertEqual((info['resume'], info['link'], info['id']), ('agy --conversation ' + GID, None, None))
        self.assertEqual(info['subagents'], [{'id': GSUB, 'name': 'research'}])
        self.assertEqual(cat.search('子代理发现关键线索'), [])          # 子代理不混进主搜索
        self.assertEqual([g['session'].src for g in cat.search('接入', src='gemini')], ['gemini'])
        st = stats.compute(cat, src='gemini')
        self.assertEqual((st['sessions'], st['total']['n'], st['quota']), (2, 4, []))
        page = render.session_page(s, c, render.ServerMode(cat.agents), info=info)
        self.assertIn('<b>Gemini</b>', page)
        self.assertIn('data-src="gemini"', page)
        self.assertIn('href="/agent/%s"' % GSUB, page)
        self.assertIn('Gemini', render.session_markdown(s, c))
        exported = export_html(cat, s, images=True)
        self.assertIn('data:image/png;base64,', exported)
        self.assertNotIn('/static/', exported)
        idx_html = self.app.index_html()
        self.assertIn('class="seg srcs s3"', idx_html)
        self.assertIn('data-s="gemini"', idx_html)
        self.assertIn('data-g="', idx_html)
        # HTTP 接口：子代理页、搜索与统计按 src=gemini 筛选
        get = self.serve()
        status, body, _ = get('/agent/' + GSUB)
        self.assertEqual(status, 200)
        self.assertIn('子代理发现关键线索', body.decode())
        self.assertIn('<b>Gemini</b>', body.decode())
        self.assertEqual(json.loads(get('/api/stats?src=gemini&days=0')[1])['total']['n'], 4)
        self.assertEqual(json.loads(get('/api/search?q=%E6%8E%A5%E5%85%A5&src=gemini')[1])['total'], 1)
        # 增量追加后刷新
        self.gwrite(GID, [{'step_index': 9, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE',
                           'created_at': ts(12), 'content': '<USER_REQUEST>\n再来一轮\n</USER_REQUEST>'}], mode='a')
        self.assertTrue(cat.refresh(force=True))
        self.assertEqual(self.texts(cat.content(cat.by_page[s.page])['items'], 'user'), ['帮我把 Gemini 接入进来', '再来一轮'])

    def test_uri_and_model_parsing(self):
        self.assertEqual(gemini.parse_model('gemini-4-neon-xhigh'), ('gemini-4-neon', 'xhigh'))
        self.assertEqual(gemini.parse_model('gemini-4-hydrogen-tiered-high'), ('gemini-4-hydrogen', 'high'))
        self.assertEqual(gemini.parse_model('gemini-4-argon-trial'), ('gemini-4-argon', ''))
        self.assertEqual(gemini.parse_model('gemini-4-argon-e'), ('gemini-4-argon', ''))
        self.assertEqual(gemini.parse_model('gemini-3.8-flash-n'), ('gemini-3.8-flash', ''))
        self.assertEqual(gemini.parse_model('gemini-3.8-flash-tiered'), ('gemini-3.8-flash', ''))
        self.assertEqual(gemini.parse_model('Gemini 3.8 Flash (High)'), ('gemini-3.8-flash', 'high'))
        self.assertEqual(gemini.parse_model('Claude Opus 5.5 (High)'), ('claude-opus-5-5', 'high'))
        self.assertEqual(gemini.parse_model('None'), ('', ''))
        p = gemini.uri_to_path('file:///d%3A/Github/Sessiontool')
        self.assertTrue(p.lower().replace('\\', '/').endswith('d:/github/sessiontool'))
        self.assertFalse(p.startswith('\\d:') or p.startswith('/d:'))

    def test_conv_db_gen_metadata_recovers_model_tokens_and_thinking(self):
        def varint(n):
            out = bytearray()
            while True:
                b = n & 0x7f
                n >>= 7
                out.append(b | (0x80 if n else 0))
                if not n:
                    return bytes(out)

        def f_varint(fn, n):
            return varint((fn << 3) | 0) + varint(n)

        def f_bytes(fn, data):
            if isinstance(data, str):
                data = data.encode('utf-8')
            return varint((fn << 3) | 2) + varint(len(data)) + data

        def gen_blob(steps, raw_model, label, inp, out_tok, cr, think):
            usage = f_varint(2, inp) + f_varint(3, out_tok) + f_varint(5, cr) + f_varint(9, think)
            inner = f_bytes(4, usage) + (f_bytes(19, raw_model) if raw_model else b'') + (f_bytes(21, label) if label else b'')
            packed = b''.join(varint(s) for s in steps)
            return f_bytes(1, inner) + f_bytes(2, packed)

        cid = '33333333-3333-4333-8333-333333333333'
        # transcript_full.jsonl 里既没有 model（步骤 1）也没有 token 字段（步骤 2）
        self.gwrite(cid, [
            {'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE', 'created_at': ts(1),
             'content': '<USER_REQUEST>\n用 gen_metadata 补齐\n</USER_REQUEST>'},
            {'step_index': 1, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(2),
             'input_tokens': 1000, 'cache_read_tokens': 2000, 'output_tokens': 300, 'content': '第一步'},
            {'step_index': 2, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(3),
             'content': '第二步'},
        ])
        cdb = os.path.join(self.tmp.name, 'gemini', 'antigravity', 'conversations', cid + '.db')
        os.makedirs(os.path.dirname(cdb), exist_ok=True)
        con = sqlite3.connect(cdb)
        con.execute('CREATE TABLE gen_metadata(idx INT PRIMARY KEY, data BLOB)')
        con.execute('INSERT INTO gen_metadata VALUES(0, ?)',
                    (gen_blob([1], 'gemini-3.8-flash-tiered', '', 1000, 300, 2000, 180),))
        con.execute('INSERT INTO gen_metadata VALUES(1, ?)',
                    (gen_blob([2], 'gemini-4-argon-trial', 'Gemini 4 Argon (High)', 500, 120, 4000, 90),))
        con.commit()
        con.close()
        cat = self.open()
        s = [x for x in cat.sessions if x.cli_ids[0] == cid][0]
        u = cat.content(s)['usage']
        self.assertEqual((u['n'], u['unpriced'], u['thinking']), (2, 0, 270))
        self.assertEqual({m['name'] for m in u['models']}, {'Gemini 3.8 Flash', 'Gemini 4 Argon'})
        self.assertEqual((s.model, s.effort), ('gemini-4-argon', 'high'))

    def test_empty_stubs_skipped_and_unknown_projects_and_models_handled(self):
        # Claude 空占位文件（仅含 file-history-snapshot）和 Codex 仅含 session_meta 的空文件不生成空会话
        self.write('stub0001', [{'type': 'file-history-snapshot', 'messageId': 'x'}])
        d = os.path.join(self.tmp.name, 'codex', 'sessions', '2026', '01', '01')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'rollout-2026-01-01T00-00-00-%s.jsonl' % TID), 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(cx(0, 'session_meta', {'id': TID, 'cwd': 'C:\\work\\empty'})) + '\n')
        # Antigravity：一个无 workspace 但绑定 config/projects 自定义项目，一个完全无文件夹且含未记录模型的回复
        g_proj, g_free = '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'
        self.gwrite(g_proj, [
            {'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE', 'created_at': ts(1),
             'content': '<USER_REQUEST>\n带项目配置\n</USER_REQUEST>'},
            {'step_index': 1, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(2),
             'model': 'gemini-4-neon-xhigh', 'input_tokens': 100, 'cache_read_tokens': 0, 'output_tokens': 10, 'content': '好'},
        ])
        self.gwrite(g_free, [
            {'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE', 'created_at': ts(3),
             'content': '<USER_REQUEST>\n没选文件夹的提问\n</USER_REQUEST>'},
            {'step_index': 1, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(4),
             'input_tokens': 100, 'cache_read_tokens': 0, 'output_tokens': 10, 'content': '回复'},
            {'step_index': 2, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(5),
             'model': 'brand-new-model-9', 'input_tokens': 50, 'cache_read_tokens': 0, 'output_tokens': 5, 'content': '新模型'},
        ])
        self.gdb('antigravity', [
            (g_proj, '项目内对话', '', '', 'proj-custom', 'CASCADE_RUN_STATUS_IDLE', '', '', '', 0, 0),
            (g_free, '随手一问', '', '', 'builtin-playground', 'CASCADE_RUN_STATUS_IDLE', '', '', '', 0, 0),
        ])
        pdir = os.path.join(self.tmp.name, 'gemini', 'config', 'projects')
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, 'proj-custom.json'), 'w', encoding='utf-8') as f:
            json.dump({'id': 'proj-custom', 'name': '我的自定义项目', 'projectResources': {}}, f, ensure_ascii=False)
        cat = self.open()
        self.assertEqual(len(cat.sessions), 2)
        by = {s.cli_ids[0]: s for s in cat.sessions}
        self.assertEqual(by[g_proj].proj, '我的自定义项目')
        self.assertEqual(by[g_free].proj, '无文件夹')
        st = stats.compute(cat, src='gemini')
        self.assertEqual(st['favorite']['name'], 'Gemini 4 Neon')       # 优先有名字的模型，且空模型不占彩色槽位
        by_m = {m['model']: m for m in st['models']}
        self.assertEqual(by_m['']['name'], '未记录模型')
        self.assertEqual(by_m['']['slot'], stats.SLOTS)
        self.assertEqual(st['total']['unpriced_models'], ['brand-new-model-9'])
        self.assertEqual(cat.content(by[g_free])['usage']['unpriced_models'], ['brand-new-model-9'])

    def test_stats_slots_are_scoped_per_source(self):
        # 其他来源占满 10 个高花费模型时，切到 Claude 视图后 Claude 自己的模型仍应各自获得独立槽位而非归入“其他”
        steps = []
        for i in range(12):
            steps.append({'step_index': i, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'created_at': ts(i + 1),
                          'model': 'gemini-4-neon' if i == 0 else 'custom-big-model-%d' % i,
                          'input_tokens': 100000, 'cache_read_tokens': 0, 'output_tokens': 100000, 'content': 'ok'})
        self.gwrite(GID, [{'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE',
                           'created_at': ts(0), 'content': '<USER_REQUEST>\n高消耗\n</USER_REQUEST>'}] + steps)
        self.write('aaaa1111', [
            user('u1', None, '问一', 1, 'aaaa1111'),
            reply('a1', 'u1', 'm1', '答一', 2, 'aaaa1111', model='claude-opus-5-5', out=10),
            reply('a2', 'a1', 'm2', '答二', 3, 'aaaa1111', model='claude-fable-5-2', out=10),
            reply('a3', 'a2', 'm3', '答三', 4, 'aaaa1111', model='claude-haiku-5-5', out=10),
        ])
        cat = self.open()
        st = stats.compute(cat, src='claude')
        self.assertEqual(set(st['slots']), {'Opus 5.5', 'Fable 5.2', 'Haiku 5.5'})
        self.assertTrue(all(m['slot'] < len(st['slots']) for m in st['models']))

    def test_gemini_login_account_and_unified_formatting(self):
        # 1) 从 app_storage.json 读取登录邮箱，且与同邮箱 Claude 未登记会话不互相覆盖
        gdir = os.path.join(self.tmp.name, 'gemini')
        os.makedirs(gdir, exist_ok=True)
        with open(os.path.join(gdir, 'app_storage.json'), 'w', encoding='utf-8') as f:
            json.dump({'agy.onboarding.lastLoginUsername': 'shared@example.com'}, f)
        self.gwrite(GID, [{'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE',
                           'created_at': ts(1), 'content': '<USER_REQUEST>\n测试账号\n</USER_REQUEST>'}])
        self.write('aaaa1111', [
            {'type': 'attachment', 'uuid': 'att1', 'parentUuid': None, 'timestamp': ts(1), 'sessionId': 'aaaa1111',
             'attachment': {'type': 'session_context', 'context': {'userEmail': 'shared@example.com'}}},
            user('u1', 'att1', 'Claude 同邮箱测试', 2, 'aaaa1111'),
            asst('a1', 'u1', '好', 3, 'aaaa1111'),
        ])
        cat = self.open()
        by_src = {s.src: s for s in cat.sessions}
        self.assertEqual(by_src['gemini'].account, 'gemini:shared@example.com')
        self.assertEqual(cat.account(by_src['gemini'])['name'], 'shared')
        self.assertEqual(cat.account(by_src['gemini'])['id'], '')
        self.assertEqual(cat.account(by_src['claude'])['src'], 'claude')
        self.assertNotEqual(by_src['claude'].account, by_src['gemini'].account)
        idx_html = self.app.index_html()
        self.assertIn('data-acct="gemini:shared@example.com"', idx_html)
        self.assertIn('class="badge cl srcb">Claude</span>', idx_html)
        self.assertIn('class="badge gm srcb">Gemini</span>', idx_html)
        # 2) 无 app_storage.json 时回退到 antigravity-cli/cli.log
        os.remove(os.path.join(gdir, 'app_storage.json'))
        cli_log = os.path.join(gdir, 'antigravity-cli', 'cli.log')
        os.makedirs(os.path.dirname(cli_log), exist_ok=True)
        with open(cli_log, 'w', encoding='utf-8') as f:
            f.write('I1115 22:57:22 applyAuthResult: email=cliuser@example.com, authMethod=consumer\n')
        cat.refresh(force=True)
        gs = [s for s in cat.sessions if s.src == 'gemini'][0]
        self.assertEqual(gs.account, 'gemini:cliuser@example.com')
        self.assertEqual(cat.account(gs)['email'], 'cliuser@example.com')
        # 3) 金额小数位：>= $0.01 与 $0.00 统一千分位 + 两位小数，仅 (0, 0.01) 保留三位
        self.assertEqual(render.money(None), '—')
        self.assertEqual(render.money(0), '$0.00')
        self.assertEqual(render.money(0.004), '$0.004')
        self.assertEqual(render.money(1.5), '$1.50')
        self.assertEqual(render.money(858.82), '$858.82')
        self.assertEqual(render.money(1162.45), '$1,162.45')
        self.assertEqual(render.money(12345.6), '$12,345.60')


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
        self.assertEqual(pricing.key('claude-fable-5-2'), 'claude-fable-5-2')
        self.assertEqual(pricing.key('claude-mythos-5-2'), 'claude-mythos-5-2')
        self.assertEqual(pricing.key('claude-fable-5-1[1m]'), 'claude-fable-5-1')
        self.assertEqual(pricing.key('us.anthropic.claude-sonnet-4-5-20250929-v1:0'), 'claude-sonnet-4-5')
        self.assertEqual(pricing.key('gpt-5-codex'), 'gpt-5-codex')
        self.assertEqual(pricing.key('gpt-6-astra'), 'gpt-6-astra')
        self.assertEqual(pricing.key('gpt6astra'), 'gpt-6-astra')
        self.assertEqual(pricing.key('gpt-6.2-astra'), 'gpt-6.2-astra')
        self.assertEqual(pricing.key('gpt62astra'), 'gpt-6.2-astra')
        self.assertEqual(pricing.key('gpt-6.2-sol'), 'gpt-6.2-sol')
        self.assertEqual(pricing.key('gpt-6.1-terra'), 'gpt-6.1-terra')
        self.assertEqual(pricing.key('gpt-6-luna'), 'gpt-6-luna')
        self.assertEqual(pricing.key('gpt-5.4'), 'gpt-5.4')
        self.assertEqual(pricing.key('gpt-5.3-codex'), 'gpt-5.3-codex')
        self.assertEqual(pricing.key('gpt-6-astra-2026-10-01'), 'gpt-6-astra')
        self.assertEqual(pricing.key('global.openai.gpt-6-astra'), 'gpt-6-astra')
        self.assertEqual(pricing.parts('claude-fable-5-2', '', 100000, 10000, 100000, 0, 0, 0)[:3], (0.8, 0.4, 0.02))
        self.assertEqual(pricing.parts('claude-fable-5-2', 'fast', 100000, 10000, 100000, 0, 0, 0)[:3], (1.6, 0.8, 0.04))
        self.assertEqual(pricing.parts('claude-sonnet-5-5', '', 100000, 10000, 100000, 0, 0, 0)[:3], (0.2, 0.1, 0.01))
        self.assertEqual(pricing.parts('gpt-6.2-astra', '', 100000, 10000, 100000, 0, 0, 0)[:3], (0.8, 0.4, 0.04))
        self.assertEqual(pricing.parts('gpt-6.2-astra', '', 200000, 10000, 100000, 0, 0, 0)[:3], (3.2, 0.6, 0.08))
        self.assertEqual(pricing.parts('gpt-6.2-astra', 'fast', 100000, 10000, 100000, 0, 0, 0)[:3], (1.6, 0.8, 0.08))
        self.assertEqual(pricing.parts('gpt-6.2-sol', '', 100000, 10000, 100000, 0, 0, 0)[:3], (0.2, 0.1, 0.01))
        self.assertEqual(pricing.parts('gpt-6.1-terra', '', 100000, 10000, 100000, 0, 0, 0)[:3], (0.1, 0.05, 0.005))
        self.assertEqual(pricing.parts('gpt6astra', '', 100000, 10000, 100000, 0, 0, 0)[:3], (1.0, 0.5, 0.1))
        self.assertEqual(pricing.parts('gpt-6-astra', '', 200000, 10000, 100000, 0, 0, 0)[:3], (4.0, 0.75, 0.2))
        self.assertEqual(pricing.parts('gpt-6-astra', 'fast', 100000, 10000, 100000, 0, 0, 0)[:3], (2.0, 1.0, 0.2))
        self.assertIsNone(pricing.key('claude-opus-4-9'))
        self.assertEqual([pricing.model_name(m) for m in ('claude-fable-5-2', 'claude-opus-5-5', 'claude-3-5-haiku-20241022', 'claude-opus-4-20250514', 'gpt-6.1-sol',
                                                          'gemini-4-neon', 'gemini-4-hydrogen-tiered-high', 'gemini-3.8-flash', 'gemini-2.5-flash-lite')],
                         ['Fable 5.2', 'Opus 5.5', 'Haiku 3.5', 'Opus 4', 'gpt-6.1-sol',
                          'Gemini 4 Neon', 'Gemini 4 Hydrogen', 'Gemini 3.8 Flash', 'Gemini 2.5 Flash-Lite'])
        self.assertEqual(pricing.key('gemini-4-neon-xhigh'), 'gemini-4-neon')
        self.assertEqual(pricing.key('gemini-4-hydrogen-tiered-high'), 'gemini-4-hydrogen')
        self.assertEqual(pricing.key('google.gemini-3.1-pro-preview'), 'gemini-3.1-pro')
        self.assertEqual(pricing.parts('gemini-4-neon', '', 100000, 10000, 100000, 0, 0, 0)[:3], (0.3, 0.15, 0.015))
        self.assertEqual(pricing.parts('gemini-3.1-pro', '', 150000, 10000, 100000, 0, 0, 0)[:3], (0.6, 0.18, 0.04))
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
