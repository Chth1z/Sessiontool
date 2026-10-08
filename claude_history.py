#!/usr/bin/env python3
"""把 Claude 桌面应用 / Claude Code 的本地会话记录转成可离线浏览的网页。

用法:
    python claude_history.py            生成/更新全部会话，输出到脚本旁的 claude-history 文件夹
    python claude_history.py --open     生成后用浏览器打开索引页
    python claude_history.py --images   同时导出工具截图（体积大，默认只保留你自己发的图片）
    python claude_history.py --force    忽略缓存，全部重新生成

一个应用会话在磁盘上可能对应多份记录（压缩、重启后会新建文件），复刻的会话只带一部分
之前的历史。本工具按应用自己的会话清单把它们合并回一个完整会话。
只读取记录，不修改它们。无第三方依赖。
"""
import argparse, base64, collections, glob, hashlib, html, json, os, re, sys, webbrowser
from datetime import datetime

VER = 12
HOME = os.path.expanduser('~')
MAX_TOOL_TEXT = 6000
WEEK = '一二三四五六日'

# ---------- 极简 Markdown 渲染 ----------

def inline(s):
    codes = []
    def stash(m):
        codes.append('<code>' + html.escape(m.group(1)) + '</code>')
        return '\x00%d\x00' % (len(codes) - 1)
    def link(m):
        text, url = m.group(1), m.group(2).replace('"', '&quot;')
        if re.match(r'https?://', url):
            return '<a href="%s" target="_blank" rel="noopener">%s</a>' % (url, text)
        return '<span class="flink" title="%s">%s</span>' % (url, text)
    s = re.sub(r'`([^`\n]+)`', stash, s)
    s = html.escape(s, quote=False)
    s = re.sub(r'\[([^\]\n]+)\]\(([^)\s]+)\)', link, s)
    s = re.sub(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])', r'<em>\1</em>', s)
    return re.sub(r'\x00(\d+)\x00', lambda m: codes[int(m.group(1))], s)

LIST = re.compile(r'^(\s*)([-*+]|\d+[.)])\s+(.*)')
TABLE_SEP = re.compile(r'\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?')

def cells(row):
    row = row.strip().replace('\\|', '\x01')
    if row.startswith('|'): row = row[1:]
    if row.endswith('|'): row = row[:-1]
    return [c.strip().replace('\x01', '|') for c in row.split('|')]

def md(text):
    out, para = [], []
    lines = text.replace('\r\n', '\n').split('\n')
    def flush():
        if para:
            out.append('<p>' + '<br>'.join(inline(x) for x in para) + '</p>')
            del para[:]
    i = 0
    while i < len(lines):
        ln = lines[i]; st = ln.strip()
        if st.startswith('```'):
            flush(); buf = []; i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i]); i += 1
            out.append('<pre><code>' + html.escape('\n'.join(buf)) + '</code></pre>'); i += 1
            continue
        if not st:
            flush(); i += 1; continue
        m = re.match(r'(#{1,6})\s+(.*)', st)
        if m:
            flush(); n = min(len(m.group(1)) + 2, 6)
            out.append('<h%d>%s</h%d>' % (n, inline(m.group(2)), n)); i += 1; continue
        if re.fullmatch(r'(-{3,}|\*{3,}|_{3,})', st):
            flush(); out.append('<hr>'); i += 1; continue
        if '|' in st and i + 1 < len(lines) and TABLE_SEP.fullmatch(lines[i + 1].strip() or 'x'):
            flush(); head = cells(st); i += 2; rows = []
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                rows.append(cells(lines[i])); i += 1
            t = '<div class="tw"><table><thead><tr>' + ''.join('<th>%s</th>' % inline(c) for c in head) + '</tr></thead><tbody>'
            for r in rows:
                t += '<tr>' + ''.join('<td>%s</td>' % inline(c) for c in r) + '</tr>'
            out.append(t + '</tbody></table></div>'); continue
        m = LIST.match(ln)
        if m:
            flush(); ordered = m.group(2)[0].isdigit(); buf = []
            start = re.sub(r'\D', '', m.group(2)) if ordered else ''
            while i < len(lines):
                m2 = LIST.match(lines[i])
                if m2: buf.append([len(m2.group(1).expandtabs(4)), m2.group(3)])
                elif lines[i].strip() and lines[i][:1] in ' \t': buf[-1][1] += '\n' + lines[i].strip()
                else: break
                i += 1
            base = min(b[0] for b in buf)
            tag = 'ol start="%s"' % start if ordered else 'ul'
            out.append('<%s>' % tag + ''.join(
                '<li style="margin-left:%.1fem">%s</li>' % ((ind - base) // 2 * 1.2, inline(t).replace('\n', '<br>'))
                for ind, t in buf) + '</%s>' % tag[:2])
            continue
        if st.startswith('>'):
            flush(); buf = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i])); i += 1
            out.append('<blockquote>' + md('\n'.join(buf)) + '</blockquote>'); continue
        para.append(st); i += 1
    flush()
    return '\n'.join(out)

# ---------- 读取：应用的会话清单 + 磁盘上的记录文件 ----------

def store_dirs():
    """应用保存会话清单的位置。Windows 商店版把 AppData 重定向到 Packages 下，两处都找。"""
    c = []
    for base in (os.environ.get('APPDATA'), os.path.join(HOME, 'Library', 'Application Support'), os.path.join(HOME, '.config')):
        if base: c.append(os.path.join(base, 'Claude', 'claude-code-sessions'))
    la = os.environ.get('LOCALAPPDATA')
    if la: c += glob.glob(os.path.join(la, 'Packages', 'Claude_*', 'LocalCache', 'Roaming', 'Claude', 'claude-code-sessions'))
    return [d for d in c if os.path.isdir(d)]

def load_records():
    recs = {}
    for d in store_dirs():
        for p in glob.glob(os.path.join(d, '**', 'local_*.json'), recursive=True):
            try:
                with open(p, encoding='utf-8') as f: r = json.load(f)
            except Exception: continue
            if not isinstance(r, dict) or not r.get('sessionId') or not r.get('cliSessionId'): continue
            old = recs.get(r['sessionId'])
            if not old or (r.get('lastActivityAt') or 0) >= (old.get('lastActivityAt') or 0): recs[r['sessionId']] = r
    return recs

def clean(s):
    s = re.sub(r'<system-reminder>.*?</system-reminder>', '', s, flags=re.S)
    s = re.sub(r'<local-command-(stdout|stderr|caveat)>.*?</local-command-\1>', '', s, flags=re.S)
    return s.strip()

def cut(s, n=MAX_TOOL_TEXT):
    return s if len(s) <= n else s[:n] + '\n…（已截断，共 %d 字符）' % len(s)

def tool_hint(inp):
    if not isinstance(inp, dict): return ''
    for k in ('description', 'file_path', 'command', 'pattern', 'query', 'url', 'skill', 'prompt'):
        if inp.get(k): return str(inp[k]).replace('\n', ' ')[:100]
    return ''

class Images:
    def __init__(self, out_dir):
        self.dir = os.path.join(out_dir, 'img')
    def save(self, block):
        src = block.get('source') or {}
        data = src.get('data')
        if src.get('type') != 'base64' or not isinstance(data, str): return None
        ext = re.sub(r'\W', '', (src.get('media_type') or 'image/png').split('/')[-1].replace('jpeg', 'jpg'))
        name = hashlib.sha1(data.encode('ascii', 'ignore')).hexdigest()[:16] + '.' + ext
        path = os.path.join(self.dir, name)
        if not os.path.exists(path):
            os.makedirs(self.dir, exist_ok=True)
            try:
                with open(path, 'wb') as f: f.write(base64.b64decode(data))
            except Exception: return None
        return name

def parse_file(path, images, tool_images):
    """一份 .jsonl → 精简后的消息列表（文字保留，图片落盘或计数，工具输出截断）。"""
    recs = []; title = None; cwd = None; last_ts = ''
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try: d = json.loads(line)
            except Exception: continue
            t = d.get('type')
            if t == 'custom-title': title = d.get('customTitle') or title; continue
            if t not in ('user', 'assistant') or d.get('isSidechain'): continue
            c = (d.get('message') or {}).get('content')
            if isinstance(c, str): c = [{'type': 'text', 'text': c}]
            if not isinstance(c, list): continue
            cwd = cwd or d.get('cwd')
            ts = d.get('timestamp') or last_ts; last_ts = ts
            blocks = []
            for b in c:
                if not isinstance(b, dict): continue
                bt = b.get('type')
                if bt == 'text':
                    if (b.get('text') or '').strip(): blocks.append(('text', b['text']))
                elif bt == 'image':
                    p = images.save(b)
                    if p: blocks.append(('img', p))
                elif bt == 'thinking':
                    if (b.get('thinking') or '').strip(): blocks.append(('think', b['thinking'].strip()))
                elif bt == 'tool_use':
                    inp = b.get('input')
                    blocks.append(('use', b.get('id'), b.get('name') or '?', tool_hint(inp),
                                   cut(json.dumps(inp, ensure_ascii=False, indent=2), 4000)))
                elif bt == 'tool_result':
                    rc = b.get('content'); rt = []; imgs = []; nimg = 0
                    if isinstance(rc, str): rt.append(rc)
                    for rb in rc if isinstance(rc, list) else []:
                        if not isinstance(rb, dict): continue
                        if rb.get('type') == 'text': rt.append(rb.get('text', ''))
                        elif rb.get('type') == 'image':
                            p = images.save(rb) if tool_images else None
                            if p: imgs.append(p)
                            else: nimg += 1
                    blocks.append(('res', b.get('tool_use_id'), cut('\n'.join(rt)), tuple(imgs), nimg, bool(b.get('is_error'))))
            if blocks:
                recs.append({'uuid': d.get('uuid'), 'ts': ts, 'sid': d.get('sessionId'), 'role': t,
                             'meta': bool(d.get('isMeta')), 'compact': bool(d.get('isCompactSummary')), 'blocks': blocks})
    return {'recs': recs, 'title': title, 'cwd': cwd}

class Library:
    def __init__(self, root, images, tool_images):
        self.files = {os.path.splitext(os.path.basename(p))[0]: p for p in glob.glob(os.path.join(root, '*', '*.jsonl'))}
        self.records = load_records()
        self.images, self.tool_images = images, tool_images
        self.parsed, self.memo = {}, {}
        used = set()
        for r in self.records.values(): used.update(self.own_ids(r))
        for cid in self.files:          # 应用清单里没有的记录（终端里跑的、或清单已删除的）单独成会话
            if cid not in used:
                self.records['file_' + cid] = {'sessionId': 'file_' + cid, 'cliSessionId': cid, '_orphan': True}

    def own_ids(self, r):
        ids = []
        for i in list(r.get('priorCliSessionIds') or []) + [r.get('cliSessionId')]:
            if i and i not in ids: ids.append(i)
        return ids

    def own_files(self, r):
        return [self.files[i] for i in self.own_ids(r) if i in self.files]

    def parent(self, r):
        p = r.get('forkedFromSessionId')
        return self.records.get(p) if p and p != r['sessionId'] else None

    def lineage_files(self, r, depth=0):
        p = self.parent(r)
        base = self.lineage_files(p, depth + 1) if p and depth < 8 else []
        return base + [f for f in self.own_files(r) if f not in base]

    def load(self, path):
        if path not in self.parsed:
            print('  读取 %s (%.1f MB)' % (os.path.basename(path)[:8], os.path.getsize(path) / 1048576), flush=True)
            self.parsed[path] = parse_file(path, self.images, self.tool_images)
        return self.parsed[path]

    def merged(self, r, depth=0):
        """一个应用会话的完整消息：父会话里更早的部分 + 自己的各份记录，去重后按时间排序。"""
        sid = r['sessionId']
        if sid in self.memo: return self.memo[sid]
        own = [x for f in self.own_files(r) for x in self.load(f)['recs']]
        base = []
        p = self.parent(r)
        if p and depth < 8:
            # 复刻的记录从最近一次压缩处开始，自带到复刻点为止的内容；更早的部分只在父会话里
            first = min([x['ts'] for x in own if x['ts']] or [''])
            base = [x for x in self.merged(p, depth + 1) if x['ts'] < first]
        out, seen_u, seen_c = [], set(), set()
        for x in base + own:
            ck = (x['role'], x['ts'], hash(repr(x['blocks'])))
            if (x['uuid'] and x['uuid'] in seen_u) or ck in seen_c: continue
            seen_u.add(x['uuid']); seen_c.add(ck); out.append(x)
        out.sort(key=lambda x: x['ts'])
        self.memo[sid] = out
        return out

def assemble(recs, own_ids, forked):
    items, tools, n_user = [], {}, 0
    marked = not forked
    for x in recs:
        if not marked and x['sid'] in own_ids:
            marked = True
            if items: items.append({'kind': 'fork', 'ts': x['ts']})
        ts = x['ts']
        if x['role'] == 'user':
            texts, imgs = [], []
            for b in x['blocks']:
                if b[0] == 'text': texts.append(b[1])
                elif b[0] == 'img': imgs.append(b[1])
                elif b[0] == 'res':
                    tu = tools.get(b[1])
                    if tu: tu['result'], tu['imgs'], tu['nimg'], tu['error'] = b[2], list(b[3]), b[4], b[5]
            if x['meta']: continue
            body = clean('\n\n'.join(texts))
            if not body and not imgs: continue
            if re.fullmatch(r'\[Request interrupted by user[^\]]*\]', body): items.append({'kind': 'stop', 'ts': ts})
            elif x['compact']: items.append({'kind': 'summary', 'ts': ts, 'text': body})
            elif body.startswith(('<task-notification', '<ci-monitor-event')): items.append({'kind': 'note', 'ts': ts, 'text': body})
            else:
                # 发出后被中断、应用重启会话又原样重发的同一条消息，只保留后一条
                j = len(items) - 1
                while j >= 0 and items[j]['kind'] in ('stop', 'note', 'think'): j -= 1
                if j >= 0 and items[j]['kind'] == 'user' and items[j]['text'] == body:
                    items[j:] = [y for y in items[j + 1:] if y['kind'] != 'stop']
                    n_user -= 1
                n_user += 1
                items.append({'kind': 'user', 'ts': ts, 'text': body, 'imgs': imgs, 'n': n_user})
        else:
            for b in x['blocks']:
                if b[0] == 'text': items.append({'kind': 'asst', 'ts': ts, 'text': b[1].strip()})
                elif b[0] == 'think': items.append({'kind': 'think', 'ts': ts, 'text': b[1]})
                elif b[0] == 'use':
                    tu = {'name': b[2], 'hint': b[3], 'input': b[4], 'result': None, 'error': False, 'imgs': [], 'nimg': 0}
                    tools[b[1]] = tu
                    if items and items[-1]['kind'] == 'tools': items[-1]['tools'].append(tu)
                    else: items.append({'kind': 'tools', 'ts': ts, 'tools': [tu]})
    return items

# ---------- 输出 ----------

CSS = """
:root{--bg:#fbfaf7;--fg:#1f1e1c;--mut:#77736b;--line:#e4e0d6;--user:#f0ece1;--acc:#b4552d;--code:#f1eee6;--hit:#fff3b0}
@media(prefers-color-scheme:dark){:root{--bg:#1b1a18;--fg:#e9e6df;--mut:#9a958b;--line:#35322d;--user:#2a2824;--acc:#e08a63;--code:#26241f;--hit:#5a4a12}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
a{color:var(--acc)}main{max-width:900px;margin:0 auto;padding:24px 16px 80px;min-width:0;flex:1}
h1{font-size:22px;margin:0 0 4px}.meta{color:var(--mut);font-size:13px;margin-bottom:20px}
.layout{display:flex}nav{position:sticky;top:0;align-self:flex-start;width:270px;flex:none;height:100vh;overflow:auto;padding:16px 12px;border-right:1px solid var(--line);font-size:13px}
nav a{display:block;padding:4px 6px;border-radius:6px;color:var(--fg);text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
nav a:hover{background:var(--user)}nav .back{color:var(--acc);margin-bottom:8px}nav small{color:var(--mut)}nav .d{color:var(--mut);font-size:11px;margin:10px 6px 2px}
@media(max-width:1000px){nav{display:none}}
.msg{margin:18px 0;scroll-margin-top:12px}.msg>header{font-size:12px;color:var(--mut);margin-bottom:4px}.msg>header b{color:var(--fg);font-size:13px}
.user .body{background:var(--user);border-radius:12px;padding:10px 14px}
.body p{margin:.5em 0}.body h3,.body h4,.body h5,.body h6{margin:1em 0 .3em;font-size:16px}.body h3{font-size:18px}
pre{background:var(--code);padding:10px 12px;border-radius:8px;overflow:auto;font:12.5px/1.5 Consolas,"Cascadia Mono",monospace;white-space:pre-wrap;word-break:break-word}
code{background:var(--code);padding:1px 4px;border-radius:4px;font:.9em Consolas,"Cascadia Mono",monospace}pre code{padding:0;background:none}
.tw{overflow:auto}table{border-collapse:collapse;margin:.6em 0;font-size:14px}th,td{border:1px solid var(--line);padding:4px 10px;text-align:left;vertical-align:top}
blockquote{margin:.5em 0;padding-left:12px;border-left:3px solid var(--line);color:var(--mut)}hr{border:0;border-top:1px solid var(--line)}
details{margin:8px 0;font-size:13px}summary{cursor:pointer;color:var(--mut)}details.tools,details.fold{border-left:2px solid var(--line);padding-left:10px}
details.tool{margin:4px 0 4px 8px}.err{color:#c0392b}.flink{border-bottom:1px dotted var(--mut)}
img.pic{max-width:320px;max-height:240px;border:1px solid var(--line);border-radius:6px;margin:4px 6px 0 0}
.day,.forkline{display:flex;align-items:center;gap:12px;color:var(--mut);font-size:12px;margin:28px 0 8px}.day:before,.day:after,.forkline:before,.forkline:after{content:"";flex:1;border-top:1px solid var(--line)}
.stop{color:var(--mut);font-size:12px;margin:10px 0;text-align:center}.forkline{color:var(--acc)}.forkline:before,.forkline:after{border-color:var(--acc)}
.bar{display:flex;gap:8px;margin:12px 0;flex-wrap:wrap}input,button,select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
input{flex:1;min-width:200px}button{cursor:pointer}
.idx{width:100%}.idx td{border-width:0 0 1px;padding:8px 10px}.idx th{border-width:0 0 2px;color:var(--mut);font-weight:500;font-size:12px;white-space:nowrap}
.idx small{color:var(--mut);display:block}.idx td.n{white-space:nowrap;color:var(--mut);font-size:13px}
.tag{display:inline-block;font-size:11px;padding:0 6px;border:1px solid var(--line);border-radius:10px;color:var(--mut);margin-left:6px;vertical-align:middle}
mark{background:var(--hit);color:inherit;border-radius:3px}.hit{box-shadow:-3px 0 0 var(--hit)}.cur{box-shadow:-3px 0 0 var(--acc)}
.find{position:fixed;right:16px;bottom:16px;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:6px 8px;display:flex;gap:6px;align-items:center;font-size:13px;box-shadow:0 2px 12px rgba(0,0,0,.15)}
"""

def head(title):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'
            + title + '</title><style>' + CSS + '</style>')

SESSION_JS = """<script>
function tg(q){var d=[].slice.call(document.querySelectorAll(q));var o=!d.some(function(x){return x.open});d.forEach(function(x){x.open=o})}
(function(){var m=/[#&]q=([^&]+)/.exec(location.hash);if(!m)return;var v=decodeURIComponent(m[1]).toLowerCase();
var hits=[].filter.call(document.querySelectorAll('main .msg, main details.fold'),function(e){return e.textContent.toLowerCase().indexOf(v)>=0});
if(!hits.length)return;var i=0,bar=document.createElement('div');bar.className='find';
bar.innerHTML='<span></span><button>\\u2191</button><button>\\u2193</button>';var lab=bar.firstChild;
function go(d){hits[i].classList.remove('cur');i=(i+d+hits.length)%hits.length;var h=hits[i];h.classList.add('cur');if(h.tagName==='DETAILS')h.open=true;
h.scrollIntoView({block:'start'});lab.textContent='\\u201c'+v+'\\u201d '+(i+1)+' / '+hits.length}
bar.children[1].onclick=function(){go(-1)};bar.children[2].onclick=function(){go(1)};document.body.appendChild(bar);
hits.forEach(function(h){h.classList.add('hit')});go(0)})();
</script></html>"""

INDEX_JS = """<script src="search.js"></script><script>
var C=window.CORPUS||{},L={},q=document.getElementById('q'),pj=document.getElementById('pj'),ar=document.getElementById('ar');
function low(id){return L[id]||(L[id]=(C[id]||'').toLowerCase())}
function esc(s){return s.replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function run(){var raw=q.value.trim(),v=raw.toLowerCase(),p=pj.value,n=0;
[].forEach.call(document.querySelectorAll('tbody tr'),function(r){
var id=r.dataset.id,a=r.querySelector('a'),sn=r.querySelector('.sn'),ok=(!p||r.dataset.p===p)&&(ar.checked||!r.dataset.a),i=-1;
if(ok&&v){i=low(id).indexOf(v);ok=i>=0||r.dataset.t.indexOf(v)>=0}
r.hidden=!ok;if(ok)n++;a.href=a.dataset.h+(v?'#q='+encodeURIComponent(raw):'');
if(ok&&v&&i>=0){var c=C[id],s=Math.max(0,i-30);sn.innerHTML='\\u2026'+esc(c.slice(s,i))+'<mark>'+esc(c.slice(i,i+v.length))+'</mark>'+esc(c.slice(i+v.length,i+v.length+80))+'\\u2026';sn.hidden=false}else sn.hidden=true});
document.getElementById('cnt').textContent=n}
q.oninput=pj.onchange=ar.onchange=run;run();
</script></html>"""

def esc(s): return html.escape(str(s), quote=True)

def local(iso):
    try: return datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone()
    except Exception: return None

def fmt(iso, f='%Y-%m-%d %H:%M'):
    t = local(iso or '')
    return t.strftime(f) if t else ''

def pics(names):
    return ''.join('<a href="../img/%s" target="_blank"><img class="pic" loading="lazy" src="../img/%s"></a>' % (p, p) for p in names)

def render_session(s):
    body, toc, day = [], [], None
    for it in s['items']:
        k = it['kind']; t = local(it['ts'] or '')
        if t and t.date() != day and k in ('user', 'asst', 'tools'):
            day = t.date(); label = '%s 周%s' % (t.strftime('%Y-%m-%d'), WEEK[t.weekday()])
            body.append('<div class="day">%s</div>' % label); toc.append('<div class="d">%s</div>' % label)
        if k == 'user':
            toc.append('<a href="#u%d" title="%s"><small>%s</small> %s</a>' % (
                it['n'], esc(it['text'][:300]), fmt(it['ts'], '%H:%M'), esc(it['text'][:40].replace('\n', ' '))))
            body.append('<section class="msg user" id="u%d"><header><b>你</b> · %s · <a href="#u%d">#%d</a></header><div class="body">%s%s</div></section>'
                        % (it['n'], fmt(it['ts']), it['n'], it['n'], md(it['text']), pics(it['imgs'])))
        elif k == 'asst':
            body.append('<section class="msg asst"><header><b>Claude</b> · %s</header><div class="body">%s</div></section>' % (fmt(it['ts']), md(it['text'])))
        elif k == 'fork':
            body.append('<div class="forkline">以上来自原会话 · 从这里开始是复刻后的内容</div>')
            toc.append('<div class="d">—— 复刻点 ——</div>')
        elif k == 'stop':
            body.append('<div class="stop">— 你中断了这次回复 · %s —</div>' % fmt(it['ts'], '%H:%M'))
        elif k == 'summary':
            body.append('<details class="fold"><summary>上下文压缩摘要 · %s</summary><div class="body">%s</div></details>' % (fmt(it['ts']), md(it['text'])))
        elif k == 'note':
            body.append('<details class="fold"><summary>系统通知 · %s</summary><pre>%s</pre></details>' % (fmt(it['ts']), esc(cut(it['text'], 3000))))
        elif k == 'think':
            body.append('<details class="fold think"><summary>思考过程</summary><div class="body">%s</div></details>' % md(it['text']))
        elif k == 'tools':
            cnt = collections.Counter(t['name'] for t in it['tools'])
            label = '、'.join('%s×%d' % (n, c) if c > 1 else n for n, c in cnt.most_common())
            inner = []
            for t in it['tools']:
                res = ''
                if t['result']: res += '<pre class="%s">%s</pre>' % ('err' if t['error'] else '', esc(t['result']))
                res += pics(t['imgs'])
                if t['nimg']: res += '<p><small>（%d 张截图未导出，加 --images 重新生成可查看）</small></p>' % t['nimg']
                inner.append('<details class="tool"><summary><code>%s</code> %s%s</summary><pre>%s</pre>%s</details>'
                             % (esc(t['name']), esc(t['hint']), ' <span class="err">失败</span>' if t['error'] else '', esc(t['input']), res))
            body.append('<details class="tools"><summary>工具调用 %d 次：%s</summary>%s</details>' % (len(it['tools']), esc(label), ''.join(inner)))
    r = s['row']
    extra = ''
    if r['fork_of']: extra += '　·　复刻自 <a href="%s.html">%s</a>' % (r['fork_of'][0], esc(r['fork_of'][1]))
    if r['nfiles'] > 1: extra += '　·　由 %d 份记录合并' % r['nfiles']
    return head(esc(r['title'])) + ('<div class="layout"><nav><a class="back" href="../index.html">← 全部会话</a>%s</nav>'
            '<main><h1>%s</h1><div class="meta">%s　·　%s → %s　·　你 %d 条 / Claude %d 段%s</div>'
            '<div class="bar"><button onclick="tg(\'details.tools,details.tool\')">展开/收起全部工具调用</button>'
            '<button onclick="tg(\'details.think\')">展开/收起思考过程</button></div>%s</main></div>'
            ) % (''.join(toc), esc(r['title']), esc(r['cwd']), fmt(r['first']), fmt(r['last']), r['n_user'], r['n_asst'], extra, '\n'.join(body)) + SESSION_JS

def render_index(rows):
    trs = []; projects = sorted(set(r['proj'] for r in rows))
    for r in rows:
        tags = ''
        if r['fork_of']: tags += '<span class="tag">复刻</span>'
        if r['archived']: tags += '<span class="tag">已归档</span>'
        if r['orphan']: tags += '<span class="tag">不在应用列表中</span>'
        sub = esc(r['first_prompt'])
        if r['fork_of']: sub = '复刻自「%s」　' % esc(r['fork_of'][1]) + sub
        trs.append('<tr data-id="%s" data-p="%s" data-t="%s" data-a="%s"><td><a href="s/%s.html" data-h="s/%s.html">%s</a>%s<small>%s</small><small class="sn" hidden></small></td>'
                   '<td class="n">%s</td><td class="n">%s</td><td class="n">%d</td><td class="n">%.1f MB</td></tr>'
                   % (r['page'], esc(r['proj']), esc(r['title'].lower()), '1' if r['archived'] else '', r['page'], r['page'], esc(r['title']), tags, sub,
                      esc(r['proj']), fmt(r['last']), r['n_user'], r['size'] / 1048576))
    opts = '<option value="">全部项目</option>' + ''.join('<option>%s</option>' % esc(p) for p in projects)
    return head('Claude 会话记录') + ('<main><h1>Claude 会话记录</h1>'
            '<div class="meta">显示 <span id="cnt">%d</span> / %d 个会话 · 生成于 %s · 再次运行脚本即可更新</div>'
            '<div class="bar"><input id="q" placeholder="搜索标题或对话内容（全文）…" autofocus><select id="pj">%s</select>'
            '<label><input type="checkbox" id="ar" checked style="flex:none;min-width:0"> 含已归档</label></div>'
            '<table class="idx"><thead><tr><th>会话</th><th>项目</th><th>最后活动</th><th>提问</th><th>记录大小</th></tr></thead><tbody>%s</tbody></table></main>'
            ) % (len(rows), len(rows), datetime.now().strftime('%Y-%m-%d %H:%M'), opts, '\n'.join(trs)) + INDEX_JS

def main():
    ap = argparse.ArgumentParser(description='把 Claude 本地会话记录转成可离线浏览的网页')
    ap.add_argument('--root', default=os.path.join(HOME, '.claude', 'projects'), help='会话记录目录（默认 ~/.claude/projects）')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'claude-history'), help='输出文件夹')
    ap.add_argument('--images', action='store_true', help='同时导出工具截图')
    ap.add_argument('--force', action='store_true', help='忽略缓存全部重新生成')
    ap.add_argument('--open', action='store_true', help='完成后打开索引页')
    a = ap.parse_args()
    sdir = os.path.join(a.out, 's'); os.makedirs(sdir, exist_ok=True)
    cache_path = os.path.join(a.out, 'cache.json')
    try:
        with open(cache_path, encoding='utf-8') as f: cache = json.load(f)
        if cache.get('ver') != VER: cache = {}
    except Exception: cache = {}
    old = cache.get('sessions', {})
    lib = Library(a.root, Images(a.out), a.images)

    pages, taken = {}, set()            # 短文件名，避免 Windows 260 字符路径上限
    for sid in sorted(lib.records):
        raw = re.sub(r'^(local_|file_)', '', sid).replace('-', ''); n = 8
        while raw[:n] in taken and n < len(raw): n += 1
        pages[sid] = raw[:n]; taken.add(raw[:n])

    new, rows = {}, []
    todo = sorted(lib.records.values(), key=lambda r: r.get('createdAt') or 0)
    for n, r in enumerate(todo, 1):
        sid = r['sessionId']; own = lib.own_files(r)
        if not own: continue
        p = lib.parent(r)
        files = lib.lineage_files(r)
        key = [a.images, r.get('title'), bool(r.get('isArchived')), pages[sid], pages.get(p['sessionId']) if p else None,
               [[os.path.basename(f), os.path.getmtime(f), os.path.getsize(f)] for f in files]]
        page = os.path.join(sdir, pages[sid] + '.html')
        c = old.get(sid)
        if c and c['key'] == key and os.path.exists(page) and not a.force:
            new[sid] = c; rows.append(c['row']); continue
        print('[%d/%d] %s' % (n, len(todo), r.get('title') or sid), flush=True)
        items = assemble(lib.merged(r), set(lib.own_ids(r)), bool(p))
        if not items: continue
        prompts = [it['text'] for it in items if it['kind'] == 'user']
        stamps = [it['ts'] for it in items if it['ts']]
        title = r.get('title') or lib.load(own[-1])['title'] or (prompts[0][:40] if prompts else '（无标题）')
        cwd = r.get('cwd') or lib.load(own[-1])['cwd'] or ''
        row = {'page': pages[sid], 'title': title.replace('\n', ' '), 'cwd': cwd, 'proj': os.path.basename(cwd.rstrip('\\/')) or cwd,
               'first': min(stamps) if stamps else '', 'last': max(stamps) if stamps else '',
               'n_user': len(prompts), 'n_asst': sum(1 for it in items if it['kind'] == 'asst'),
               'size': sum(os.path.getsize(f) for f in own), 'nfiles': len(files), 'archived': bool(r.get('isArchived')), 'orphan': bool(r.get('_orphan')),
               'fork_of': [pages[p['sessionId']], p.get('title') or '原会话'] if p else None,
               'first_prompt': prompts[0][:90].replace('\n', ' ') if prompts else ''}
        with open(page, 'w', encoding='utf-8') as f: f.write(render_session({'items': items, 'row': row}))
        corpus = re.sub(r'\s+', ' ', ' '.join(it['text'] for it in items if it['kind'] in ('user', 'asst')))
        imgs = sorted(set(i for it in items for i in it.get('imgs', [])) | set(i for it in items if it['kind'] == 'tools' for t in it['tools'] for i in t['imgs']))
        new[sid] = {'key': key, 'row': row, 'corpus': corpus, 'imgs': imgs}
        rows.append(row)

    rows.sort(key=lambda r: r['last'], reverse=True)
    with open(os.path.join(a.out, 'search.js'), 'w', encoding='utf-8') as f:
        f.write('window.CORPUS=' + json.dumps({v['row']['page']: v['corpus'] for v in new.values()}, ensure_ascii=False).replace('</', '<\\/') + ';')
    index = os.path.join(a.out, 'index.html')
    with open(index, 'w', encoding='utf-8') as f: f.write(render_index(rows))
    with open(cache_path, 'w', encoding='utf-8') as f: json.dump({'ver': VER, 'sessions': new}, f, ensure_ascii=False)

    keep = set(v['row']['page'] + '.html' for v in new.values())      # 清掉本工具以前生成、现已无用的页面和图片
    for f in os.listdir(sdir):
        if f.endswith('.html') and f not in keep: os.remove(os.path.join(sdir, f))
    used = set(i for v in new.values() for i in v['imgs'])
    if os.path.isdir(os.path.join(a.out, 'img')):
        for f in os.listdir(os.path.join(a.out, 'img')):
            if f not in used: os.remove(os.path.join(a.out, 'img', f))

    print('完成：%d 个会话 → %s' % (len(rows), index))
    if not lib.records or all(r.get('_orphan') for r in lib.records.values()):
        print('提示：没有找到应用的会话清单，已按单个记录文件分别显示（不会合并）。')
    if os.name == 'nt' and len(os.path.join(sdir, 'x' * 8 + '.html')) > 240:
        print('注意：当前文件夹路径太深，Windows 下部分页面可能打不开，建议把整个工具移到更短的路径（如 D:\\ClaudeHistory）。')
    if a.open: webbrowser.open('file:///' + index.replace('\\', '/'))

if __name__ == '__main__':
    main()
