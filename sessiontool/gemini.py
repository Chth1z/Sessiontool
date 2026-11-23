"""Gemini（Antigravity 应用与 CLI）的会话记录：
~/.gemini/antigravity/brain/<会话 ID>/.system_generated/logs/transcript_full.jsonl（及 antigravity-cli 下同结构），
一行一个步骤（USER_INPUT、PLANNER_RESPONSE、GENERIC、SYSTEM_MESSAGE、CHECKPOINT、ERROR_MESSAGE）。

整理成和 Claude Code 记录一样的形状（kind + 块列表），后面的合并、渲染、搜索、按需取内容与统计复用同一套：
- USER_INPUT：去掉外层 <USER_REQUEST>、<ADDITIONAL_METADATA>、<USER_SETTINGS_CHANGE> 包装，并从模型切换说明里补齐老版本缺失的模型和推理强度；
- PLANNER_RESPONSE：思考过程、回复正文、工具调用，以及本次请求的 token 用量（input_tokens 已不含 cache_read_tokens）；
- GENERIC：工具调用的输出与截图，按顺序配对到前面未完结的工具调用，并识别 invoke_subagent / swarm 产生的子代理编号；
- SYSTEM_MESSAGE：子代理回报与后台通知，归入系统通知；CHECKPOINT 归入上下文压缩与摘要；ERROR_MESSAGE 归入提示行。
"""
import json
import os
import re
import sqlite3
from urllib.parse import unquote, urlsplit
from urllib.request import pathname2url

USER_REQ = re.compile(r'<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>', re.S)
USER_META = re.compile(r'\s*<(ADDITIONAL_METADATA|USER_SETTINGS_CHANGE)\b[^>]*>.*?</\1>\s*', re.S)
MODEL_SET = re.compile(r'changed setting `Model Selection` from .*? to ([^\n]+?)(?:\.(?:\s|$)|$)')
SYS_WRAP = re.compile(r'^The following is a <SYSTEM_MESSAGE>\s*(.*?)\s*</SYSTEM_MESSAGE>\s*$', re.S)
STEP_TS = re.compile(r'^(?:(?:Created|Completed) At: [^\r\n]*\r?\n)+')
UUID_RE = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I)
EFFORTS = frozenset(('minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'thinking'))
EDIT_ARGS = {
    'edit_file': ('Path',),
    'write_file': ('Path',),
    'write_to_file': ('TargetFile', 'Path'),
    'replace_file_content': ('TargetFile', 'Path'),
    'multi_replace_file_content': ('TargetFile', 'Path'),
}
HINT_BY_TOOL = {
    'read_file': ('Path',),
    'view_file': ('AbsolutePath', 'Path'),
    'list_dir': ('DirectoryPath', 'Path'),
    'run_command': ('toolSummary', 'CommandLine'),
    'grep_search': ('Query', 'SearchPath'),
    'find_by_name': ('Pattern', 'SearchDirectory'),
    'search_web': ('query',),
    'read_url_content': ('Url', 'url'),
    'invoke_subagent': ('Role', 'TypeName', 'Prompt'),
    'update_focus': ('focus',),
    'webview_browser': ('toolSummary', 'url', 'Url'),
}
EXTRA_HINTS = ('toolSummary', 'Description', 'Path', 'TargetFile', 'AbsolutePath', 'DirectoryPath',
               'CommandLine', 'Query', 'Pattern', 'Prompt', 'Url')


def conv_id(path):
    """…/brain/<会话 ID>/.system_generated/logs/transcript_full.jsonl → 会话 ID。"""
    p = os.path.normpath(path)
    parts = p.split(os.sep)
    if len(parts) >= 4 and parts[-2] == 'logs' and parts[-3] == '.system_generated':
        return parts[-4]
    return os.path.splitext(os.path.basename(p))[0]


def uri_to_path(uri):
    """file:///d%3A/path 或普通本地路径 → 规范化路径。"""
    if not isinstance(uri, str) or not uri.strip():
        return ''
    s = uri.strip()
    if s.lower().startswith('file://'):
        u = urlsplit(s)
        path = unquote(u.path or '')
        if u.netloc and u.netloc.lower() != 'localhost':
            path = '//' + u.netloc + path
        if re.match(r'^/[A-Za-z]:[\\/]', path):
            path = path[1:]
        return os.path.normpath(path)
    return os.path.normpath(s)


def parse_model(raw):
    """模型标识或设置里的显示名 → (归一化模型 ID, 推理强度)。

    - gemini-4-neon-xhigh → ('gemini-4-neon', 'xhigh')
    - gemini-4-hydrogen-tiered-high → ('gemini-4-hydrogen', 'high')
    - Gemini 4 Neon (XHigh) → ('gemini-4-neon', 'xhigh')
    - Claude Opus 5.5 (High) → ('claude-opus-5-5', 'high')
    """
    s = (raw or '').strip()
    if not s or s.lower() == 'none':
        return '', ''
    effort = ''
    m = re.match(r'^(.+?)\s*\(([^()]+)\)\s*$', s)
    if m:
        s = m.group(1).strip()
        tail = m.group(2).strip().lower()
        if tail in EFFORTS:
            effort = tail
    low = s.lower()
    if ' ' in low:
        if low.startswith('claude '):
            low = low.replace('.', '-')
        low = re.sub(r'\s+', '-', low)
    parts = low.split('-')
    if not effort and len(parts) >= 2 and parts[-1] in EFFORTS:
        effort = parts.pop()
    while len(parts) >= 2 and parts[-1] in ('tiered', 'trial'):
        parts.pop()
    if parts and parts[0] == 'gemini' and len(parts) >= 4 and len(parts[-1]) == 1 and parts[-1].isalpha():
        parts.pop()
    return '-'.join(parts), effort


def _pb_varint(buf, i):
    v = shift = 0
    n = len(buf)
    while i < n:
        b = buf[i]
        i += 1
        v |= (b & 0x7f) << shift
        if not (b & 0x80):
            return v, i
        shift += 7
    return v, i


def _pb_fields(buf):
    """极简 Protobuf wire-format 解码，只提取字段编号、线型和值，不依赖第三方库。"""
    i, n, out = 0, len(buf), []
    while i < n:
        tag, i = _pb_varint(buf, i)
        fn, wt = tag >> 3, tag & 7
        if not fn:
            break
        if wt == 0:
            v, i = _pb_varint(buf, i)
            out.append((fn, 0, v))
        elif wt == 1:
            if i + 8 > n:
                break
            out.append((fn, 1, buf[i:i + 8]))
            i += 8
        elif wt == 2:
            ln, i = _pb_varint(buf, i)
            if i + ln > n:
                break
            out.append((fn, 2, buf[i:i + ln]))
            i += ln
        elif wt == 5:
            if i + 4 > n:
                break
            out.append((fn, 5, buf[i:i + 4]))
            i += 4
        else:
            break
    return out


def decode_gen_meta(buf):
    """解析 conversations/<id>.db 中 gen_metadata.data → (首步骤号, 模型 ID, 推理强度, inp, out, cr, think) 或 None。"""
    if not isinstance(buf, (bytes, bytearray)) or not buf:
        return None
    steps, inner = [], None
    for fn, wt, val in _pb_fields(buf):
        if fn == 2 and wt == 2:
            i, n = 0, len(val)
            while i < n:
                v, i = _pb_varint(val, i)
                steps.append(v)
        elif fn == 2 and wt == 0:
            steps.append(val)
        elif fn == 1 and wt == 2:
            inner = val
    if not steps or not inner:
        return None
    raw_model = label = ''
    inp = out_tok = cr = think = 0
    for fn, wt, val in _pb_fields(inner):
        if fn == 19 and wt == 2:
            raw_model = val.decode('utf-8', 'ignore')
        elif fn == 21 and wt == 2:
            label = val.decode('utf-8', 'ignore')
        elif fn == 4 and wt == 2:
            for ufn, uwt, uval in _pb_fields(val):
                if uwt == 0:
                    if ufn == 2:
                        inp = uval
                    elif ufn == 3:
                        out_tok = uval
                    elif ufn == 5:
                        cr = uval
                    elif ufn == 9:
                        think = uval
    m_lbl, e_lbl = parse_model(label)
    m_raw, e_raw = parse_model(raw_model)
    model = m_lbl or m_raw
    effort = e_lbl or e_raw
    return steps[0], model, effort, inp, out_tok, cr, think


def conv_db_path(transcript_path):
    """…/<base>/brain/<cid>/.system_generated/logs/transcript_full.jsonl → …/<base>/conversations/<cid>.db。"""
    p = os.path.normpath(transcript_path)
    parts = p.split(os.sep)
    if len(parts) >= 5 and parts[-2] == 'logs' and parts[-3] == '.system_generated' and parts[-5] == 'brain':
        base = os.sep.join(parts[:-5]) or os.sep
        return os.path.join(base, 'conversations', parts[-4] + '.db')
    return ''


def conv_gen_meta(transcript_path):
    """只读打开同会话的 conversations/<cid>.db，返回 {step_index: (model, effort, inp, out, cr, think)}。"""
    db = conv_db_path(transcript_path)
    if not db or not os.path.isfile(db):
        return {}
    out = {}
    try:
        con = sqlite3.connect('file:%s?mode=ro' % pathname2url(db), uri=True, timeout=1)
        try:
            for (data,) in con.execute('SELECT data FROM gen_metadata'):
                rec = decode_gen_meta(data)
                if rec:
                    out[rec[0]] = rec[1:]
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    return out


def strip_timestamps(text):
    return STEP_TS.sub('', text or '').strip()


def clean_user(text):
    """从 USER_INPUT 正文里抽出用户实际输入，同时从 USER_SETTINGS_CHANGE 提取模型和推理强度。"""
    s = text or ''
    model, effort = '', ''
    for m in MODEL_SET.finditer(s):
        pm, pe = parse_model(m.group(1))
        if pm:
            model, effort = pm, pe
    req = USER_REQ.search(s)
    if req:
        body = req.group(1).strip()
    else:
        body = USER_META.sub('', s).strip()
    return body, model, effort


def media_blocks(media):
    """media 数组 → 图片块列表（按需由 details.load_image 从磁盘安全读取）。"""
    out = []
    for m in media or ():
        if not isinstance(m, dict):
            continue
        mime = str(m.get('mime_type') or '').lower()
        path = uri_to_path(m.get('uri'))
        if mime.startswith('image/') and path:
            out.append({'type': 'image', 'source': {'type': 'file', 'media_type': mime, 'path': path}})
    return out


def describe(name, args):
    """工具调用 → (一行提示, 改到的文件列表)。"""
    from .index import tool_hint
    if not isinstance(args, dict):
        return str(args or '')[:120], []
    first = lambda s, lim=120: str(s).replace('\n', ' ').strip()[:lim]
    if name in EDIT_ARGS:
        paths = [str(args[k]).strip() for k in EDIT_ARGS[name] if isinstance(args.get(k), str) and args[k].strip()]
        return (first(paths[0], 400) if paths else tool_hint(args)), paths
    if name == 'swarm':
        bits = [str(args.get(k)).strip() for k in ('action', 'name', 'title', 'brief') if args.get(k)]
        return first(' '.join(bits)), []
    if name == 'update_steps' and isinstance(args.get('steps'), list):
        doing = [x.get('title') for x in args['steps'] if isinstance(x, dict) and x.get('status') == 'in_progress' and x.get('title')]
        return first(doing[0] if doing else '%d 步' % len(args['steps'])), []
    if name == 'ask_question' and isinstance(args.get('questions'), list):
        qs = [q.get('question') for q in args['questions'] if isinstance(q, dict) and q.get('question')]
        if qs:
            return first(qs[0]), []
    for k in HINT_BY_TOOL.get(name, ()):
        if args.get(k):
            return first(args[k], 400 if k in ('Path', 'AbsolutePath', 'DirectoryPath', 'TargetFile') else 120), []
    for k in EXTRA_HINTS:
        if args.get(k):
            return first(args[k], 400 if k in ('Path', 'AbsolutePath', 'DirectoryPath', 'TargetFile') else 120), []
    return tool_hint(args), []


def generic_body(d):
    """GENERIC 步骤 → (文字, 图片块列表, 是否失败)。"""
    text = strip_timestamps(d.get('content') or '')
    err_msg = str(d.get('error') or '').strip()
    if err_msg and err_msg not in text:
        text = (text + '\n' + err_msg).strip() if text else err_msg
    is_error = bool(err_msg) or d.get('status') == 'ERROR'
    return text, media_blocks(d.get('media')), is_error


def content(d):
    """一行记录 → Claude 形状的 content 列表（下标和索引登记的一一对应），按需取工具详情和图片时用。"""
    t = d.get('type')
    if t == 'USER_INPUT':
        return media_blocks(d.get('media'))
    if t == 'PLANNER_RESPONSE':
        out = []
        for i, tc in enumerate(d.get('tool_calls') or ()):
            if not isinstance(tc, dict):
                out.append({'type': '?'})
                continue
            args = tc.get('args')
            inp = args if isinstance(args, dict) else ({'args': args} if args is not None else {})
            out.append({'type': 'tool_use', 'id': 's%s.%d' % (d.get('step_index', 0), i),
                        'name': tc.get('name') or 'tool', 'input': inp})
        return out
    if t == 'GENERIC':
        text, imgs, is_error = generic_body(d)
        body = ([{'type': 'text', 'text': text}] + imgs) if imgs else text
        return [{'type': 'tool_result', 'tool_use_id': '', 'content': body, 'is_error': is_error}]
    return None


def token_usage(d, ctx, step_key, gm=None):
    """PLANNER_RESPONSE / CHECKPOINT 上的用量。Antigravity 的 input_tokens 已不含 cache_read_tokens；
    若 jsonl 缺少用量或思考 token，从同会话 conversations/<id>.db 的 gen_metadata 补齐。"""
    n = lambda x: int(x) if isinstance(x, (int, float)) and x > 0 else 0
    inp, cr, out = n(d.get('input_tokens')), n(d.get('cache_read_tokens')), n(d.get('output_tokens'))
    think = 0
    if gm:
        if not (inp or cr or out):
            inp, out, cr = n(gm[2]), n(gm[3]), n(gm[4])
        think = n(gm[5])
    if not (inp or cr or out):
        return None
    return {'mid': 'gemini:%s:%s' % (ctx.get('sid') or '', step_key), 'model': ctx.get('model') or '',
            'effort': ctx.get('effort') or '', 'speed': '', 'inp': inp, 'out': out,
            'cr': cr, 'cw5': 0, 'cw1h': 0, 'web': 0, 'think': think}


def parse_line(d, ctx, gen_meta=None):
    """一行 → ([(kind, data, text, tool)], 用量或 None)。ctx 在同一文件的多行与增量读取间保留。"""
    t = d.get('type')
    step = d.get('step_index')
    step_key = step if step is not None else ctx.get('seq', 0)
    ctx['seq'] = ctx.get('seq', 0) + 1
    gm = gen_meta.get(step) if gen_meta and step is not None else None

    if t == 'USER_INPUT':
        ctx['pending'] = []
        body, model, effort = clean_user(d.get('content'))
        if model:
            ctx['model'] = model
        if effort:
            ctx['effort'] = effort
        blocks = [['text', body]] if body else []
        for i in range(len(media_blocks(d.get('media')))):
            blocks.append(['img', i])
        if not blocks:
            return [], None
        return [('user', {'b': blocks}, body, '')], None

    if t == 'PLANNER_RESPONSE':
        pm, pe = parse_model(d.get('model')) if d.get('model') else ('', '')
        if gm:
            gm_m, gm_e = gm[0], gm[1]
            if not pm and gm_m:
                pm = gm_m
            if not pe and gm_e:
                pe = gm_e
        if pm:
            prev_m = ctx.get('model') or ''
            ctx['model'] = pm
            if pe:
                ctx['effort'] = pe
            elif prev_m and prev_m != pm:
                ctx['effort'] = ''
        elif pe:
            ctx['effort'] = pe
        model = ctx.get('model') or ''
        blocks, texts, tools = [], [], []
        thinking = (d.get('thinking') or '').strip()
        if thinking:
            blocks.append(['think', thinking])
        body = (d.get('content') or '').strip()
        if body:
            blocks.append(['text', body])
            texts.append(body)
        pending = ctx.setdefault('pending', [])
        for i, tc in enumerate(d.get('tool_calls') or ()):
            if not isinstance(tc, dict):
                continue
            name = tc.get('name') or 'tool'
            args = tc.get('args')
            inp = args if isinstance(args, dict) else ({'args': args} if args is not None else {})
            cid = 's%s.%d' % (step_key, i)
            hint, paths = describe(name, inp)
            pending.append([cid, name])
            blocks.append(['use', cid, name, hint, i, {'paths': paths} if paths else None])
            tools.append('%s %s %s' % (name, hint, json.dumps(inp, ensure_ascii=False)[:3000]))
        use = token_usage(d, ctx, step_key, gm)
        if not blocks:
            return [], use
        return [('assistant', {'b': blocks, 'model': model}, '\n'.join(texts), '\n'.join(tools))], use

    if t == 'GENERIC':
        text, imgs, is_error = generic_body(d)
        pending = ctx.get('pending') or []
        if pending:
            cid, tool_name = pending.pop(0)
            agent = None
            if tool_name in ('invoke_subagent', 'swarm'):
                m = UUID_RE.search(text)
                if m:
                    agent = m.group(0).lower()
            img_idx = list(range(1, 1 + len(imgs)))
            return [('user', {'b': [['res', cid, 0, text[:300], len(text), img_idx, is_error, [], agent]]}, '',
                     text[:6000])], None
        if text:
            return [('user', {'b': [['text', text]], 'origin': 'task-notification'}, '', '')], None
        return [], None

    if t == 'SYSTEM_MESSAGE':
        raw = (d.get('content') or '').strip()
        m = SYS_WRAP.match(raw)
        body = (m.group(1) if m else raw).strip()
        if not body:
            return [], None
        return [('user', {'b': [['text', body]], 'origin': 'task-notification'}, '', '')], None

    if t == 'CHECKPOINT':
        recs = [('compact', {'trigger': 'auto', 'pre': None, 'post': None}, '', '')]
        body = (d.get('content') or '').strip()
        if body:
            recs.append(('user', {'b': [['text', body]], 'compact': 1}, '', ''))
        return recs, token_usage(d, ctx, step_key, gm)

    if t == 'ERROR_MESSAGE':
        parts = [str(x).strip() for x in (d.get('error'), d.get('content')) if x and str(x).strip()]
        msg = '：'.join(dict.fromkeys(parts))
        if not msg:
            return [], None
        return [('assistant', {'b': [['text', msg]], 'synthetic': 1}, '', '')], None

    return [], None
