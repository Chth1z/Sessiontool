"""用临时目录里的合成记录验证：增量索引、合并、复刻、改写分支、搜索、按需取内容、HTTP 服务。"""
import base64
import http.client
import json
import os
import tempfile
import threading
import unittest

from sessiontool import render
from sessiontool.details import load_image, load_tool
from sessiontool.export import export_html, export_markdown
from sessiontool.server import App, make_server
from sessiontool.sources import Sources

PNG = b'\x89PNG\r\n\x1a\nfake-image-bytes'


def ts(n):
    return '2026-01-01T00:%02d:%02d.000Z' % divmod(n, 60)


def user(uuid, parent, content, n, sid, **extra):
    d = {'type': 'user', 'uuid': uuid, 'parentUuid': parent, 'timestamp': ts(n), 'sessionId': sid, 'cwd': 'C:\\work\\proj',
         'message': {'role': 'user', 'content': content}}
    d.update(extra)
    return d


def asst(uuid, parent, content, n, sid, **extra):
    if isinstance(content, str):
        content = [{'type': 'text', 'text': content}]
    d = {'type': 'assistant', 'uuid': uuid, 'parentUuid': parent, 'timestamp': ts(n), 'sessionId': sid,
         'message': {'role': 'assistant', 'content': content}}
    d.update(extra)
    return d


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = os.path.join(self.tmp.name, 'projects')
        self.store = os.path.join(self.tmp.name, 'store')
        self.proj = os.path.join(self.root, 'C--work-proj')
        os.makedirs(self.proj)
        os.makedirs(self.store)
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.index.close()
        self.tmp.cleanup()

    def write(self, cli, records, mode='w'):
        with open(os.path.join(self.proj, cli + '.jsonl'), mode, encoding='utf-8', newline='\n') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def session(self, sid, cli, prior=(), **extra):
        d = {'sessionId': sid, 'cliSessionId': cli, 'priorCliSessionIds': list(prior), 'title': sid, 'cwd': 'C:\\work\\proj',
             'createdAt': len(os.listdir(self.store))}
        d.update(extra)
        with open(os.path.join(self.store, sid + '.json'), 'w', encoding='utf-8') as f:
            json.dump(d, f)

    def open(self):
        if self.app:
            self.app.index.close()
        self.app = App(Sources(root=self.root, stores=[self.store], home=os.path.join(self.tmp.name, 'home')))
        self.app.catalog.refresh(force=True)
        return self.app.catalog

    def content(self, cat, sid):
        s = [x for x in cat.sessions if x.id == sid][0]
        return s, cat.content(s)

    @staticmethod
    def texts(items, kind):
        return [it['text'] for it in items if it['kind'] == kind]


class IndexTest(Case):
    def test_incremental_sync_reads_only_new_complete_lines(self):
        self.write('aaaa1111', [user('u1', None, '第一条', 1, 'aaaa1111'), asst('a1', 'u1', '回复一', 2, 'aaaa1111')])
        cat = self.open()
        idx = self.app.index
        fid = idx.files()[0]['id']
        self.assertEqual(len(idx.rows(fid)), 2)
        path = os.path.join(self.proj, 'aaaa1111.jsonl')
        half = json.dumps(user('u3', 'u2', '写到一半', 4, 'aaaa1111'), ensure_ascii=False)
        with open(path, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(user('u2', 'a1', '第二条', 3, 'aaaa1111'), ensure_ascii=False) + '\n' + half[:30])
        self.assertEqual(idx.sync(), 1)
        self.assertEqual([r['uuid'] for r in idx.rows(fid)], ['u1', 'a1', 'u2'])
        with open(path, 'a', encoding='utf-8', newline='\n') as f:
            f.write(half[30:] + '\n')
        idx.sync()
        self.assertEqual([r['uuid'] for r in idx.rows(fid)], ['u1', 'a1', 'u2', 'u3'])
        self.assertEqual(idx.sync(), 0)

    def test_rewritten_file_is_reparsed_from_scratch(self):
        self.write('aaaa1111', [user('u1', None, '旧内容旧内容旧内容', 1, 'aaaa1111')])
        self.open()
        idx = self.app.index
        self.write('aaaa1111', [user('x1', None, '完全不同的新内容，而且更长一些', 1, 'aaaa1111'), asst('x2', 'x1', '好', 2, 'aaaa1111')])
        idx.sync()
        self.assertEqual([r['uuid'] for r in idx.rows(idx.files()[0]['id'])], ['x1', 'x2'])


class MergeTest(Case):
    def test_prior_and_current_files_merge_into_one_session(self):
        self.write('aaaa1111', [user('u1', None, '你好', 1, 'aaaa1111'), asst('a1', 'u1', '在', 2, 'aaaa1111'),
                                user('u2', 'a1', '问题', 3, 'aaaa1111'),
                                user('s1', 'u2', '[Request interrupted by user]', 4, 'aaaa1111')])
        # 重启后的新文件带着旧消息的副本（uuid 不变），并把被中断的那条原样重发了一遍
        self.write('bbbb2222', [user('u1', None, '你好', 1, 'bbbb2222'), asst('a1', 'u1', '在', 2, 'bbbb2222'),
                                user('u2b', 'a1', '问题', 5, 'bbbb2222'), asst('a2', 'u2b', '答案', 6, 'bbbb2222')])
        self.session('local_s1', 'bbbb2222', prior=['aaaa1111'])
        cat = self.open()
        self.assertEqual(len(cat.sessions), 1)
        s, c = self.content(cat, 'local_s1')
        self.assertEqual(self.texts(c['items'], 'user'), ['你好', '问题'])
        self.assertEqual(self.texts(c['items'], 'asst'), ['在', '答案'])
        self.assertEqual((c['nfiles'], c['n_user']), (2, 2))

    def test_unlisted_transcript_becomes_its_own_session(self):
        self.write('cccc3333', [user('u1', None, '终端里的会话', 1, 'cccc3333')])
        cat = self.open()
        self.assertTrue(cat.sessions[0].orphan)
        self.assertEqual(cat.content(cat.sessions[0])['title'], '终端里的会话')

    def test_fork_gets_earlier_history_from_parent_and_a_marker(self):
        self.write('pppp0001', [user('p1', None, '最早的问题', 1, 'pppp0001'), asst('p2', 'p1', '最早的回答', 2, 'pppp0001'),
                                user('p3', 'p2', '压缩后的问题', 10, 'pppp0001'), asst('p4', 'p3', '压缩后的回答', 11, 'pppp0001'),
                                user('p5', 'p4', '复刻之后父会话才有的', 30, 'pppp0001')])
        # 复刻的记录从压缩处开始，只带 p3、p4 的副本
        self.write('ffff0002', [user('p3', None, '压缩后的问题', 10, 'pppp0001'), asst('p4', 'p3', '压缩后的回答', 11, 'pppp0001'),
                                user('f1', 'p4', '复刻里的新问题', 20, 'ffff0002'), asst('f2', 'f1', '复刻里的回答', 21, 'ffff0002')])
        self.session('local_parent', 'pppp0001')
        self.session('local_fork', 'ffff0002', forkedFromSessionId='local_parent')
        cat = self.open()
        s, c = self.content(cat, 'local_fork')
        self.assertEqual(self.texts(c['items'], 'user'), ['最早的问题', '压缩后的问题', '复刻里的新问题'])
        kinds = [it['kind'] for it in c['items']]
        self.assertEqual(kinds.count('fork'), 1)
        self.assertLess(kinds.index('fork'), len(kinds) - 2)
        self.assertEqual(kinds[kinds.index('fork') + 1], 'user')
        _, parent = self.content(cat, 'local_parent')
        self.assertEqual(len(self.texts(parent['items'], 'user')), 3)

    def test_rewound_message_goes_into_a_collapsed_branch(self):
        self.write('aaaa1111', [user('u1', None, '开头', 1, 'aaaa1111'), asst('a1', 'u1', '好的', 2, 'aaaa1111'),
                                user('u2', 'a1', '旧问法', 3, 'aaaa1111'), asst('a2', 'u2', '旧回答', 4, 'aaaa1111'),
                                user('u3', 'a1', '新问法', 5, 'aaaa1111'), asst('a3', 'u3', '新回答', 6, 'aaaa1111')])
        s, c = self.content(self.open(), 'file_aaaa1111')
        self.assertEqual(self.texts(c['items'], 'user'), ['开头', '新问法'])
        branch = [it for it in c['items'] if it['kind'] == 'branch']
        self.assertEqual(len(branch), 1)
        self.assertEqual(self.texts(branch[0]['items'], 'user') + self.texts(branch[0]['items'], 'asst'), ['旧问法', '旧回答'])
        self.assertEqual(c['n_user'], 2)

    def test_parallel_tool_calls_are_not_mistaken_for_branches(self):
        use = lambda i: [{'type': 'tool_use', 'id': 't%d' % i, 'name': 'Bash', 'input': {'command': 'echo %d' % i}}]
        res = lambda i: [{'type': 'tool_result', 'tool_use_id': 't%d' % i, 'content': 'out %d' % i}]
        self.write('aaaa1111', [user('u1', None, '跑两个命令', 1, 'aaaa1111'),
                                asst('a1', 'u1', use(1), 2, 'aaaa1111'), asst('a2', 'a1', use(2), 2, 'aaaa1111'),
                                user('r1', 'a1', res(1), 3, 'aaaa1111'), user('r2', 'a2', res(2), 3, 'aaaa1111'),
                                asst('a3', 'r2', '都跑完了', 4, 'aaaa1111')])
        s, c = self.content(self.open(), 'file_aaaa1111')
        self.assertEqual(c['n_branch'], 0)
        tools = [t for it in c['items'] if it['kind'] == 'tools' for t in it['tools']]
        self.assertEqual([t['preview'] for t in tools], ['out 1', 'out 2'])

    def test_message_queued_during_a_reply_is_shown(self):
        queued = lambda uuid, prompt, mode, origin, n: {
            'type': 'attachment', 'uuid': uuid, 'parentUuid': 'a1', 'timestamp': ts(n), 'sessionId': 'aaaa1111',
            'attachment': {'type': 'queued_command', 'prompt': prompt, 'commandMode': mode, 'origin': origin}}
        self.write('aaaa1111', [user('u1', None, '开始', 1, 'aaaa1111'), asst('a1', 'u1', '进行中', 2, 'aaaa1111'),
                                queued('q1', '顺便把这个也做了', 'prompt', {'kind': 'human'}, 3),
                                queued('q2', '<task-notification>x</task-notification>', 'task-notification', {'kind': 'task-notification'}, 4)])
        s, c = self.content(self.open(), 'file_aaaa1111')
        prompts = [it for it in c['items'] if it['kind'] == 'user']
        self.assertEqual([p['text'] for p in prompts], ['开始', '顺便把这个也做了'])
        self.assertTrue(prompts[1]['queued'])

    def test_machine_text_is_separated_from_what_you_typed(self):
        self.write('aaaa1111', [
            user('u1', None, '真正的问题<system-reminder>机器加的</system-reminder>\n[Image: source: C:\\x\\1.png]', 1, 'aaaa1111'),
            user('u2', 'u1', 'I hit my usage limit while you were working, but it has reset now.', 2, 'aaaa1111'),
            user('u3', 'u2', '<task-notification>done</task-notification>', 3, 'aaaa1111', origin={'kind': 'task-notification'}),
            user('u4', 'u3', '只给模型看的', 4, 'aaaa1111', isMeta=True),
            asst('a1', 'u4', "You've hit your session limit", 5, 'aaaa1111', isApiErrorMessage=True)])
        s, c = self.content(self.open(), 'file_aaaa1111')
        self.assertEqual(self.texts(c['items'], 'user'), ['真正的问题'])
        self.assertEqual([it['kind'] for it in c['items']], ['user', 'auto', 'note', 'notice'])


class SearchAndDetailsTest(Case):
    def build(self):
        img = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': base64.b64encode(PNG).decode()}}
        os.makedirs(os.path.join(self.proj, 'aaaa1111', 'tool-results'))
        self.saved = os.path.join(self.proj, 'aaaa1111', 'tool-results', 'big.txt')
        with open(self.saved, 'w', encoding='utf-8') as f:
            f.write('完整的长输出' * 100)
        self.secret = os.path.join(self.tmp.name, 'secret.txt')
        with open(self.secret, 'w', encoding='utf-8') as f:
            f.write('不该被读到')
        self.write('aaaa1111', [
            user('u1', None, [{'type': 'text', 'text': '看这张图里的蓝鲸'}, img], 1, 'aaaa1111'),
            asst('a1', 'u1', [{'type': 'text', 'text': '图里是一头蓝鲸。'},
                              {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'grep -r 独角兽 .'}}], 2, 'aaaa1111'),
            user('r1', 'a1', [{'type': 'tool_result', 'tool_use_id': 't1', 'content': [
                {'type': 'text', 'text': '<persisted-output>\nFull output saved to: %s\n\nPreview: 找到独角兽' % self.saved}, img]}], 3, 'aaaa1111'),
            asst('a2', 'r1', [{'type': 'tool_use', 'id': 't2', 'name': 'Read', 'input': {'file_path': 'x'}}], 4, 'aaaa1111'),
            user('r2', 'a2', [{'type': 'tool_result', 'tool_use_id': 't2', 'content': 'Full output saved to: %s' % self.secret, 'is_error': True}], 5, 'aaaa1111')])
        # 复刻的文件里有同一批消息的副本
        self.write('ffff0002', [user('u1', None, [{'type': 'text', 'text': '看这张图里的蓝鲸'}, img], 1, 'aaaa1111'),
                                user('f1', 'u1', '复刻后又问了蓝鲸', 9, 'ffff0002')])
        self.session('local_a', 'aaaa1111')
        self.session('local_f', 'ffff0002', forkedFromSessionId='local_a')
        return self.open()

    def test_search_counts_copied_messages_once_and_can_include_tools(self):
        cat = self.build()
        groups = {g['session'].id: g for g in cat.search('蓝鲸')}
        self.assertEqual(groups['local_a']['n'], 2)
        self.assertEqual(groups['local_f']['n'], 1)
        self.assertEqual(groups['local_a']['hits'][0]['anchor'], 'm-u1')
        self.assertEqual(cat.search('独角兽'), [])
        hit = cat.search('独角兽', tools=True)[0]['hits']
        self.assertEqual(sorted(h['anchor'] for h in hit), ['r-r1', 't-a1'])
        self.assertEqual(cat.search('100%'), [])
        # 多个词：每个都要出现在同一条消息里
        self.assertEqual(sum(g['n'] for g in cat.search('蓝鲸 复刻')), 1)
        self.assertEqual(cat.search('蓝鲸 独角兽'), [])
        self.assertEqual(cat.search('   '), [])

    def test_forks_are_listed_under_their_parent_and_state_tracks_new_records(self):
        cat = self.build()
        entries = self.app.entries()
        self.assertEqual([(s.id, depth) for s, _, depth, _ in entries], [('local_a', 0), ('local_f', 1)])
        self.assertEqual(entries[0][3], entries[1][1]['last'])      # 家族按最近活动的成员排序
        state = lambda: (cat.state(), cat.state(cat.by_page[entries[0][0].page]), cat.state(cat.by_page[entries[1][0].page]))
        before = state()
        self.write('ffff0002', [user('f2', 'f1', '又来一条', 12, 'ffff0002')], mode='a')
        cat.refresh(force=True)
        after = state()
        self.assertNotEqual(after[0], before[0])
        self.assertEqual(after[1], before[1])       # 原会话没有新记录
        self.assertNotEqual(after[2], before[2])

    def test_changed_files_are_summarised(self):
        edit = lambda i, path: [{'type': 'tool_use', 'id': 'e%d' % i, 'name': 'Edit', 'input': {'file_path': path, 'old_string': 'a', 'new_string': 'b'}}]
        long_path = 'C:/work/proj/' + 'deep/' * 30 + 'file.py'
        self.write('eeee0001', [user('u1', None, '改一下', 1, 'eeee0001'),
                                asst('a1', 'u1', edit(1, long_path), 2, 'eeee0001'), asst('a2', 'a1', edit(2, long_path), 3, 'eeee0001'),
                                asst('a3', 'a2', [{'type': 'tool_use', 'id': 'b1', 'name': 'Bash', 'input': {'command': 'ls'}}], 4, 'eeee0001')])
        s, c = self.content(self.open(), 'file_eeee0001')
        self.assertEqual(c['changed'], [(long_path, 2, 'a1')])
        page = render.session_page(s, c, render.ServerMode())
        self.assertIn('修改过 1 个文件', page)
        self.assertIn('href="#t-a1"', page)

    def test_images_and_full_tool_output_load_on_demand(self):
        cat = self.build()
        s, c = self.content(cat, 'local_a')
        prompt = [it for it in c['items'] if it['kind'] == 'user'][0]
        self.assertEqual(load_image(self.app.index, prompt['imgs'][0]), (PNG, 'image/png'))
        t1, t2 = [t for it in c['items'] if it['kind'] == 'tools' for t in it['tools']]
        d = load_tool(self.app.index, self.app.sources, t1['use'], t1['res'])
        self.assertEqual(d['input'], {'command': 'grep -r 独角兽 .'})
        self.assertIn('找到独角兽', d['result'])
        self.assertTrue(d['full'].startswith('完整的长输出'))
        self.assertEqual(load_image(self.app.index, d['images'][0]), (PNG, 'image/png'))
        # 记录里写着的路径如果不在 tool-results 目录下，不读
        d2 = load_tool(self.app.index, self.app.sources, t2['use'], t2['res'])
        self.assertIsNone(d2['full'])
        self.assertTrue(d2['error'])
        self.assertIsNone(load_image(self.app.index, '999.0.0'))
        self.assertIsNone(load_image(self.app.index, 'x.y.z'))

    def test_export_is_self_contained(self):
        cat = self.build()
        s, c = self.content(cat, 'local_a')
        page = export_html(cat, s)
        self.assertIn('grep -r 独角兽', page)
        self.assertIn('data:image/png;base64,', page)
        self.assertNotIn('/api/tool', page)
        self.assertNotIn('/static/', page)
        self.assertIn('看这张图里的蓝鲸', export_markdown(cat, s))

    def test_http_server(self):
        cat = self.build()
        httpd = make_server(self.app, 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        def get(path, host=None):
            con = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            con.request('GET', path, headers={'Host': host or '127.0.0.1:%d' % port})
            r = con.getresponse()
            body = r.read()
            con.close()
            return r.status, body, r

        try:
            s, c = self.content(cat, 'local_a')
            status, body, _ = get('/')
            self.assertEqual(status, 200)
            self.assertIn('local_a', body.decode())
            status, body, r = get('/s/' + s.page)
            self.assertEqual(status, 200)
            self.assertIn('图里是一头蓝鲸', body.decode())
            self.assertIn("script-src 'self'", r.getheader('Content-Security-Policy'))
            t1 = [t for it in c['items'] if it['kind'] == 'tools' for t in it['tools']][0]
            status, body, _ = get('/api/tool?u=%s&r=%s' % (t1['use'], t1['res']))
            tool = json.loads(body)
            self.assertEqual(tool['input']['command'], 'grep -r 独角兽 .')
            self.assertEqual(get(tool['images'][0])[1], PNG)
            found = json.loads(get('/api/search?q=%E8%93%9D%E9%B2%B8')[1])
            self.assertEqual(found['total'], 3)
            self.assertEqual(get('/export/%s.md' % s.page)[0], 200)
            self.assertEqual(get('/s/nope')[0], 404)
            self.assertEqual(get('/local?p=' + self.secret.replace('\\', '/'))[0], 404)
            self.assertEqual(get('/', host='evil.example.com')[0], 403)
            self.assertEqual(json.loads(get('/api/state?page=' + s.page)[1])['sig'], cat.state(s))
            self.assertEqual(get('/static/theme.js')[0], 200)
            self.assertEqual(get('/static/../server.py')[0], 404)
        finally:
            httpd.shutdown()
            httpd.server_close()


class MarkdownTest(unittest.TestCase):
    def test_html_in_messages_is_escaped(self):
        out = render.md('<script>alert(1)</script> **粗** `a<b` [x](javascript:alert(1)) [ok](https://example.com/?a=1&b=2)')
        self.assertNotIn('<script>', out)
        self.assertNotIn('href="javascript', out)
        self.assertIn('<strong>粗</strong>', out)
        self.assertIn('<code>a&lt;b</code>', out)
        self.assertIn('href="https://example.com/?a=1&amp;b=2"', out)

    def test_blocks(self):
        out = render.md('## 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n1. 一\n2. 二\n\n```\n<pre>\n```\n> 引用')
        for part in ('<h4>标题</h4>', '<td>2</td>', '<ol start="1">', '&lt;pre&gt;', '<blockquote>'):
            self.assertIn(part, out)


if __name__ == '__main__':
    unittest.main()
