"""Codex 的会话记录：~/.codex/sessions/年/月/日/rollout-<时间>-<线程 ID>.jsonl，一行一个事件。

整理成和 Claude Code 记录一样的形状（kind + 块列表），后面的合并、渲染、搜索、按需取内容都不必分两套：
- 读模型实际看到的那一路（response_item）：用户和助手的消息、推理摘要、工具调用和输出；
- event_msg 大多是给界面的副本，只取用量（token_count）和中断（turn_aborted）；
- turn_context 记着当前的模型和推理强度，之后的用量都记在它们名下。
新版本的模型写一段 JavaScript（exec 工具）去调别的工具，这时按它实际调的工具起名、取提示。
"""
import json
import re

CALLS = ('function_call', 'custom_tool_call', 'local_shell_call', 'web_search_call', 'tool_search_call', 'image_generation_call')
OUTPUTS = ('function_call_output', 'custom_tool_call_output', 'tool_search_output')
# 应用塞进用户消息的上下文：整段是一个标签（<environment_context>…</environment_context>、<permissions instructions>…</permissions instructions>）、AGENTS.md、命令前缀提示、图片前后的标记
INJECTED = re.compile(r'\s*<([\w-]+(?:\s+instructions)?)(?:\s[^>]*)?>.*</\1>\s*', re.S)
AGENTS = re.compile(r'\s*# AGENTS\.md instructions for ')
APPROVED_PREFIX = re.compile(r'\s*Approved command prefix saved:')
IMAGE_TAG = re.compile(r'\s*</?image\b[^>]*>\s*')
PATCH_FILE = re.compile(r'\*\*\* (?:Add|Update|Delete) File: ([^\r\n"\'`\\]+)')
JS_CMD = re.compile(r'\bcmd\s*:\s*"((?:[^"\\\n]|\\.)*)"')
JS_TOOL = re.compile(r'\btools\.(\w+)\s*\(')
SHELL_FLAGS = ('-lc', '-c', '-Command', '-command', '/c', '/C')


def injected(text):
    return bool(INJECTED.fullmatch(text) or AGENTS.match(text) or APPROVED_PREFIX.match(text) or IMAGE_TAG.fullmatch(text))


def data_image(url):
    """data:image/png;base64,… → Claude 形状的图片块。网址、本地路径不认。"""
    m = re.match(r'data:(image/[\w.+-]+);base64,', url if isinstance(url, str) else '')
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': m.group(1), 'data': url[m.end():]}} if m else None


def item(c):
    """消息或工具输出里的一项 → Claude 形状的块，下标不变。"""
    if not isinstance(c, dict):
        return {'type': '?'}
    t = c.get('type')
    if t in ('input_text', 'output_text', 'text'):
        return {'type': 'text', 'text': c.get('text') or ''}
    if t in ('input_image', 'image'):
        return data_image(c.get('image_url')) or {'type': 'text', 'text': ''}
    return {'type': t or '?'}


def call(p):
    """工具调用 → (名字, 输入)。"""
    t = p.get('type')
    if t == 'function_call':
        raw = p.get('arguments')
        try:
            inp = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            inp = raw
        return p.get('name') or 'function', inp if isinstance(inp, dict) else {'arguments': inp}
    if t == 'custom_tool_call':
        return p.get('name') or 'tool', {'input': p.get('input') if isinstance(p.get('input'), str) else json.dumps(p.get('input'))}
    if t == 'local_shell_call':
        a = p.get('action') or {}
        return 'shell', {'command': a.get('command'), 'workdir': a.get('working_directory')}
    if t == 'web_search_call':
        a = p.get('action') or {}
        return 'web_search', {'query': a.get('query') or ' '.join(a.get('queries') or []) or a.get('url') or ''}
    return t, {k: v for k, v in p.items() if k not in ('type', 'id', 'status', 'call_id', 'encrypted_content')}


def output(p):
    """工具输出 → (Claude 形状的 content：文字或块列表, 是否失败)。
    老版本 shell 的输出是一段 JSON：{"output": …, "metadata": {"exit_code": …}}。"""
    out = p.get('output')
    if isinstance(out, str):
        try:
            j = json.loads(out) if out[:1] == '{' else None
        except ValueError:
            j = None
        if isinstance(j, dict) and isinstance(j.get('output'), str):
            return j['output'], (j.get('metadata') or {}).get('exit_code') not in (0, None)
        return out, False
    if isinstance(out, list):
        return [item(c) for c in out], False
    if isinstance(out, dict):
        body = out.get('content', out.get('output'))
        return (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)), out.get('success') is False
    return '', False


def shell_line(cmd):
    """['bash', '-lc', 'ls -la'] → 'ls -la'。"""
    if isinstance(cmd, list):
        if len(cmd) >= 3 and cmd[-2] in SHELL_FLAGS:
            return str(cmd[-1])
        return ' '.join(str(x) for x in cmd)
    return str(cmd or '')


def describe(name, inp):
    """工具调用 → (显示的名字, 一行提示, 改到的文件)。"""
    from .index import tool_hint
    code = inp.get('input') if isinstance(inp.get('input'), str) else ''
    paths = list(dict.fromkeys(p.strip() for p in PATCH_FILE.findall(code)))
    first = lambda s: s.strip().split('\n')[0][:120]
    if name == 'apply_patch':
        return name, paths[0] if paths else first(code), paths
    if name == 'exec' and code:
        if paths:
            return 'apply_patch', paths[0], paths
        m = JS_CMD.search(code)
        if m:
            try:
                cmd = json.loads('"%s"' % m.group(1))
            except ValueError:
                cmd = m.group(1)
            return 'exec_command', first(cmd), []
        tools = JS_TOOL.findall(code)
        return (tools[0] if tools else name), first(code), []
    if name in ('shell', 'shell_command', 'local_shell', 'container.exec'):
        return name, first(shell_line(inp.get('command'))), []
    if name == 'update_plan' and isinstance(inp.get('plan'), list):
        doing = [s.get('step') for s in inp['plan'] if isinstance(s, dict) and s.get('status') == 'in_progress']
        return name, first(doing[0] if doing else '%d 步' % len(inp['plan'])), []
    return name, tool_hint(inp), []


def content(d):
    """一行记录 → Claude 形状的 content 列表（下标和原记录一一对应），按需取工具详情和图片时用。"""
    p = d.get('payload') if d.get('type') == 'response_item' else None
    if not isinstance(p, dict):
        return None
    t = p.get('type')
    if t == 'message':
        return [item(c) for c in p.get('content') or []]
    if t in CALLS:
        name, inp = call(p)
        return [{'type': 'tool_use', 'id': p.get('call_id') or p.get('id'), 'name': name, 'input': inp}]
    if t in OUTPUTS:
        body, error = output(p)
        return [{'type': 'tool_result', 'tool_use_id': p.get('call_id'), 'content': body, 'is_error': error}]
    return None


def token_usage(p, ctx):
    """token_count 事件 → 一次回复的用量。OpenAI 的输入数里含了读、写缓存的部分，这里拆开；输出数里含推理。
    同一次回复的事件可能记两遍：编号用会话至今的累计总数，重复的自然合并。"""
    info = p.get('info') or {}
    last, total = info.get('last_token_usage') or {}, info.get('total_token_usage') or {}
    n = lambda x: int(x) if isinstance(x, (int, float)) else 0
    if not last or not n(total.get('total_tokens')):
        return None
    inp, cr, cw = n(last.get('input_tokens')), n(last.get('cached_input_tokens')), n(last.get('cache_write_input_tokens'))
    return {'mid': 'codex:%s:%d' % (ctx.get('sid') or '', n(total.get('total_tokens'))), 'model': ctx.get('model') or '',
            'effort': ctx.get('effort') or '', 'speed': ctx.get('speed') or '', 'inp': max(0, inp - cr - cw),
            'out': n(last.get('output_tokens')), 'cr': cr, 'cw5': cw, 'cw1h': 0, 'web': 0,
            'think': n(last.get('reasoning_output_tokens'))}


def parse_line(d, ctx):
    """一行 → ([(kind, data, text, tool)], 用量或 None)。ctx 是这个文件的上下文（线程 ID、目录、当前的模型……），
    跨行、跨次增量读取都保留着。"""
    t, p = d.get('type'), d.get('payload')
    if t == 'thread_name':
        name = (p.get('thread_name') if isinstance(p, dict) else None) or d.get('thread_name')
        if isinstance(name, str):
            ctx['title'] = name.strip()
        return [], None
    if not isinstance(p, dict):
        return [], None
    if t == 'session_meta':
        git = p.get('git') if isinstance(p.get('git'), dict) else {}
        for k, v in (('sid', p.get('id')), ('cwd', p.get('cwd')), ('version', p.get('cli_version')), ('origin', p.get('originator')),
                     ('source', p.get('source')), ('acct', p.get('creator_account_id')), ('provider', p.get('model_provider')),
                     ('branch', git.get('branch'))):
            if isinstance(v, str) and v:
                ctx.setdefault(k, v)            # 只认第一份：分叉出来的记录会带上原线程的 session_meta
        return [], None
    if t == 'turn_context':
        mode = (p.get('collaboration_mode') or {}).get('settings') or {}
        ctx['model'] = p.get('model') or mode.get('model') or ctx.get('model') or ''
        ctx['effort'] = p.get('effort') or mode.get('reasoning_effort') or ctx.get('effort') or ''
        tier = p.get('service_tier') if 'service_tier' in p else mode.get('service_tier')
        if tier is not None:
            ctx['speed'] = 'fast' if tier in ('fast', 'priority') else ''
        if isinstance(p.get('cwd'), str):
            ctx.setdefault('cwd', p['cwd'])
        return [], None
    if t == 'compacted':
        msg = p.get('message') if isinstance(p.get('message'), str) else ''
        recs = [('compact', {'trigger': None, 'pre': None, 'post': None}, '', '')]
        if msg.strip():
            recs.append(('user', {'b': [['text', msg]], 'compact': 1}, '', ''))
        return recs, None
    if t == 'event_msg':
        if p.get('type') == 'token_count':
            return [], token_usage(p, ctx)
        if p.get('type') == 'turn_aborted':
            return [('user', {'b': [['text', '[Request interrupted by user]']]}, '', '')], None
        return [], None
    if t != 'response_item':
        return [], None
    pt, model = p.get('type'), ctx.get('model') or ''
    if pt == 'message' and p.get('role') in ('user', 'assistant'):
        role, blocks, texts = p['role'], [], []
        for i, c in enumerate(p.get('content') or []):
            if not isinstance(c, dict):
                continue
            if c.get('type') in ('input_text', 'output_text', 'text'):
                s = c.get('text') or ''
                if s.strip() and not (role == 'user' and injected(s)):
                    blocks.append(['text', s])
                    texts.append(s)
            elif c.get('type') == 'input_image' and data_image(c.get('image_url')):
                blocks.append(['img', i])
        if not blocks:
            return [], None
        return [(role, {'b': blocks} if role == 'user' else {'b': blocks, 'model': model}, '\n'.join(texts), '')], None
    if pt == 'reasoning':
        texts = [s.get('text') for s in p.get('summary') or [] if isinstance(s, dict) and s.get('text')]
        texts += [s.get('text') for s in p.get('content') or [] if isinstance(s, dict) and s.get('text')]
        return ([('assistant', {'b': [['think', '\n\n'.join(texts)]], 'model': model}, '', '')] if texts else []), None
    if pt in CALLS:
        name, inp = call(p)
        shown, hint, paths = describe(name, inp)
        blk = ['use', p.get('call_id') or p.get('id'), shown, hint, 0, {'paths': paths} if paths else None]
        return [('assistant', {'b': [blk], 'model': model}, '',
                 '%s %s %s' % (shown, hint, json.dumps(inp, ensure_ascii=False)[:3000]))], None
    if pt in OUTPUTS:
        body, error = output(p)
        if isinstance(body, list):
            text = '\n'.join(c.get('text') or '' for c in body if c.get('type') == 'text')
            images = [j for j, c in enumerate(body) if c.get('type') == 'image']
        else:
            text, images = body, []
        return [('user', {'b': [['res', p.get('call_id'), 0, text[:300], len(text), images, error, [], None]]}, '',
                 text[:6000])], None
    return [], None
