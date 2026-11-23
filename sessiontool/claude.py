"""Claude Code / 桌面应用的会话记录：~/.claude/projects/<项目>/<会话>.jsonl（及子代理 subagents/*.jsonl）。

与 codex.py、gemini.py 保持统一的适配器形态：
- file_cli(path)：从路径提取会话/子代理编号；
- parse_record / usage / parse_line：解析消息块、附件队列、系统事件、文件元信息与 token 用量；
- content(d)：按需取工具详情与图片时返回原始 content 列表。
"""
import json
import os
import re

from .util import flatten_result, is_base64_image, tool_hint

LOCAL_IMAGE = re.compile(r'\[Image: source: ([^\]\r\n]+\.(?:png|jpe?g|gif|webp))\]', re.I)
EMAIL = re.compile(r'([\w.+-]+@[\w-]+(?:\.[\w-]+)+)')
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')


def file_cli(path):
    return os.path.splitext(os.path.basename(path))[0]


def is_agent_file(path):
    """子代理的记录放在 <会话>/subagents/ 下，一个子代理一个文件。"""
    return os.path.basename(os.path.dirname(path)) == 'subagents'


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
        content_val = msg.get('content')
        if isinstance(content_val, str):
            content_val = [{'type': 'text', 'text': content_val}]
        if not isinstance(content_val, list):
            return link
        blocks, texts, tools = [], [], []
        for i, b in enumerate(content_val):
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
            data['mid'] = msg['id']
            data['model'] = msg.get('model') or ''
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


def usage(d):
    """助手消息那一行上的用量。一次回复拆成多行时每行都带同一份，统计时按消息编号去重。"""
    msg = d.get('message') or {}
    if d.get('type') != 'assistant' or not msg.get('id') or msg.get('model') == '<synthetic>' or d.get('isApiErrorMessage'):
        return None
    u = msg.get('usage') or {}
    n = lambda x: int(x or 0) if isinstance(x, (int, float)) else 0
    cw = n(u.get('cache_creation_input_tokens'))
    cw1h = min(cw, n((u.get('cache_creation') or {}).get('ephemeral_1h_input_tokens')))
    return {'mid': msg['id'], 'model': msg.get('model') or '', 'effort': d.get('effort') or d.get('perTurnEffort') or '',
            'speed': u.get('speed') or '', 'inp': n(u.get('input_tokens')), 'out': n(u.get('output_tokens')),
            'cr': n(u.get('cache_read_input_tokens')), 'cw5': cw - cw1h, 'cw1h': cw1h,
            'web': n((u.get('server_tool_use') or {}).get('web_search_requests')),
            'think': n((u.get('output_tokens_details') or {}).get('thinking_tokens'))}


def content(d):
    """普通消息的内容在 message.content；回复进行中追加的消息在 attachment.prompt。"""
    return (d.get('message') or {}).get('content') or (d.get('attachment') or {}).get('prompt')


def update_meta(d, ctx, meta):
    """收集行上的文件级元信息（入口、版本、标题、目录、邮箱、组织），就地更新 ctx 和 meta。"""
    t = d.get('type')
    for k in ('entrypoint', 'version'):
        if isinstance(d.get(k), str) and d[k]:
            ctx.setdefault(k, d[k])
    if d.get('sessionKind') in ('bg', 'daemon', 'daemon-worker'):
        ctx.setdefault('kind', d['sessionKind'])
    if t == 'agent-name' and 'agentName' in d:
        ctx['agent_name'] = str(d.get('agentName') or '').strip()
    elif t == 'custom-title' and 'customTitle' in d:
        ctx['custom_title'] = str(d.get('customTitle') or '').strip()
    elif t == 'ai-title' and 'aiTitle' in d:
        ctx['ai_title'] = str(d.get('aiTitle') or '').strip()
    elif t == 'summary' and 'summary' in d:
        ctx['summary'] = str(d.get('summary') or '').strip()
    elif t == 'history-suppression':
        ctx['suppressed'] = 1
    elif t == 'relocated' and isinstance(d.get('relocatedCwd'), str) and d['relocatedCwd']:
        meta['cwd'] = d['relocatedCwd']
    elif t == 'attachment':
        a = d.get('attachment') or {}
        if a.get('type') == 'session_context':
            m = EMAIL.search(str((a.get('context') or {}).get('userEmail') or ''))
            if m:
                meta['email'] = m.group(1)
        elif a.get('type') == 'credential_org' and a.get('organizationUuid'):
            meta['org'] = a['organizationUuid']
    if not meta.get('cwd') and d.get('cwd'):
        meta['cwd'] = d['cwd']


def finalize_meta(ctx, meta, last_ts):
    meta['title'] = ctx.get('agent_name') or ctx.get('custom_title') or ctx.get('ai_title') or ctx.get('summary') or None
