"""按 API 价格估算 token 用量的费用；模型的显示名。

价格是每百万 token 的美元数，五项依次是：输入、输出、读取缓存、写入缓存（保留 5 分钟）、写入缓存（保留 1 小时）。
订阅用户不按 token 付费，这里算的是“同样的用量按 API 计价要多少钱”。

在索引目录（默认 ~/.sessiontool）放一个 prices.json 可以补充或改写，格式相同：
{"模型": [输入, 输出, 读缓存, 写缓存5分钟, 写缓存1小时]}，只写前三项时写缓存按输入价算。
"""
import functools
import json
import os
import re

# Anthropic 官方价目（2026-11）。写缓存：保留 5 分钟是输入价的 1.25 倍，1 小时是 2 倍
CLAUDE = {
    'claude-fable-5-2': (8, 40, 0.2, 10, 16),
    'claude-mythos-5-2': (8, 40, 0.2, 10, 16),
    'claude-fable-5-1': (10, 50, 0.25, 12.5, 20),
    'claude-mythos-5-1': (10, 50, 0.25, 12.5, 20),
    'claude-fable-5': (10, 50, 1, 12.5, 20),
    'claude-opus-5-5': (4, 20, 0.2, 5, 8),
    'claude-opus-5': (5, 25, 0.5, 6.25, 10),
    'claude-opus-4-8': (5, 25, 0.5, 6.25, 10),
    'claude-opus-4-7': (5, 25, 0.5, 6.25, 10),
    'claude-opus-4-6': (5, 25, 0.5, 6.25, 10),
    'claude-opus-4-5': (5, 25, 0.5, 6.25, 10),
    'claude-opus-4-1': (15, 75, 1.5, 18.75, 30),
    'claude-opus-4': (15, 75, 1.5, 18.75, 30),
    'claude-sonnet-5-5': (2, 10, 0.1, 2.5, 4),
    'claude-sonnet-5': (2, 10, 0.2, 2.5, 4),
    'claude-sonnet-4-6': (3, 15, 0.3, 3.75, 6),
    'claude-sonnet-4-5': (3, 15, 0.3, 3.75, 6),
    'claude-sonnet-4': (3, 15, 0.3, 3.75, 6),
    'claude-3-7-sonnet': (3, 15, 0.3, 3.75, 6),
    'claude-haiku-5-5': (0.1, 0.5, 0.01, 0.125, 0.2),
    'claude-haiku-4-5': (1, 5, 0.1, 1.25, 2),
    'claude-3-5-haiku': (0.8, 4, 0.08, 1, 1.6),
}
# OpenAI（Codex 用的模型）官方价目（2026-11）：GPT-6.1/6.2 写缓存 30 分钟为输入价 1.25 倍、12 小时为 2.5 倍；
# GPT-5 与早期模型不单收写缓存费用，按输入价计
OPENAI = {
    'gpt-6.2-astra': (8, 40, 0.4, 10, 20),
    'gpt-6.2-sol': (2, 10, 0.1, 2.5, 5),
    'gpt-6.1-sol': (2, 10, 0.1, 2.5, 5),
    'gpt-6.1-terra': (1, 5, 0.05, 1.25, 2.5),
    'gpt-6-astra': (10, 50, 1, 10, 10),
    'gpt-6-sol': (2, 10, 0.2, 2, 2),
    'gpt-6-luna': (0.1, 0.5, 0.01, 0.1, 0.1),
    'gpt-5.4': (2.5, 15, 0.25, 2.5, 2.5),
    'gpt-5.4-mini': (0.75, 4.5, 0.075, 0.75, 0.75),
    'gpt-5.4-nano': (0.2, 1.25, 0.02, 0.2, 0.2),
    'gpt-5.3-codex': (1.75, 14, 0.175, 1.75, 1.75),
    'gpt-5.3-chat': (1.75, 14, 0.175, 1.75, 1.75),
    'gpt-5.2': (1.75, 14, 0.175, 1.75, 1.75),
    'gpt-5.1-codex-max': (1.25, 10, 0.125, 1.25, 1.25),
    'gpt-5.1-codex-mini': (0.25, 2, 0.025, 0.25, 0.25),
    'gpt-5.1-codex': (1.25, 10, 0.125, 1.25, 1.25),
    'gpt-5.1': (1.25, 10, 0.125, 1.25, 1.25),
    'gpt-5-codex': (1.25, 10, 0.125, 1.25, 1.25),
    'gpt-5-mini': (0.25, 2, 0.025, 0.25, 0.25),
    'gpt-5-nano': (0.05, 0.4, 0.005, 0.05, 0.05),
    'gpt-5': (1.25, 10, 0.125, 1.25, 1.25),
    'codex-mini-latest': (1.5, 6, 0.375, 1.5, 1.5),
    'o4-mini': (1.1, 4.4, 0.275, 1.1, 1.1),
    'o3': (2, 8, 0.5, 2, 2),
    'gpt-4.1': (2, 8, 0.5, 2, 2),
}
# Google Gemini 官方价目（2026-11 标准价）。Gemini 4 隐式缓存读取按输入价的 5% 计；不单收写缓存费用，按输入价计
GEMINI = {
    'gemini-4-neon': (3, 15, 0.15, 3, 3),
    'gemini-4-argon': (4, 20, 0.2, 4, 4),
    'gemini-4-carbon': (4, 20, 0.2, 4, 4),
    'gemini-4-hydrogen': (1.5, 7.5, 0.075, 1.5, 1.5),
    'gemini-3.8-flash': (1.5, 7.5, 0.15, 1.5, 1.5),
    'gemini-3.7-flash': (1.5, 7.5, 0.15, 1.5, 1.5),
    'gemini-3.5-flash-lite': (0.3, 2.5, 0.03, 0.3, 0.3),
    'gemini-3.1-pro': (2, 12, 0.2, 2, 2),
    'gemini-3.1-flash-lite': (0.25, 1.5, 0.025, 0.25, 0.25),
    'gemini-3-pro': (2, 12, 0.2, 2, 2),
    'gemini-3-flash': (0.5, 3, 0.05, 0.5, 0.5),
    'gemini-2.5-pro': (1.25, 10, 0.125, 1.25, 1.25),
    'gemini-2.5-flash': (0.3, 2.5, 0.03, 0.3, 0.3),
    'gemini-2.5-flash-lite': (0.1, 0.4, 0.01, 0.1, 0.1),
}
# 一次请求的提示词（输入 + 缓存）超过这么多 token 时整次改用另一档价格
TIERS = {
    'claude-haiku-5-5': (100000, (0.5, 2.5, 0.05, 0.625, 1)),
    'gpt-6.2-astra': (272000, (16, 60, 0.8, 20, 40)),
    'gpt-6.2-sol': (272000, (4, 15, 0.2, 5, 10)),
    'gpt-6.1-sol': (272000, (4, 15, 0.2, 5, 10)),
    'gpt-6.1-terra': (272000, (2, 7.5, 0.1, 2.5, 5)),
    'gpt-6-astra': (272000, (20, 75, 2, 20, 20)),
    'gpt-5.4': (272000, (5, 22.5, 0.5, 5, 5)),
    'gemini-3.1-pro': (200000, (4, 18, 0.4, 4, 4)),
    'gemini-3-pro': (200000, (4, 18, 0.4, 4, 4)),
    'gemini-2.5-pro': (200000, (2.5, 15, 0.25, 2.5, 2.5)),
}
FAST = {
    'claude-fable-5-2': 2, 'claude-mythos-5-2': 2, 'claude-fable-5-1': 2, 'claude-mythos-5-1': 2,
    'claude-opus-5-5': 2, 'claude-opus-5': 2,
    'gpt-6.2-astra': 2, 'gpt-6.2-sol': 2, 'gpt-6.1-sol': 2, 'gpt-6.1-terra': 2, 'gpt-6-astra': 2,
}   # 快速模式的倍数
WEB_SEARCH = 0.01                                         # 每次网页搜索
ALIASES = {
    'gpt6astra': 'gpt-6-astra',
    'gpt62astra': 'gpt-6.2-astra',
    'gpt62sol': 'gpt-6.2-sol',
    'gpt61sol': 'gpt-6.1-sol',
    'gpt61terra': 'gpt-6.1-terra',
    'gpt6sol': 'gpt-6-sol',
    'gpt6luna': 'gpt-6-luna',
}

TABLE = dict(CLAUDE, **OPENAI, **GEMINI)


def configure(home):
    """读入用户自己的价格（prices.json），覆盖或补充内置的。"""
    TABLE.clear()
    TABLE.update(CLAUDE)
    TABLE.update(OPENAI)
    TABLE.update(GEMINI)
    key.cache_clear()
    try:
        with open(os.path.join(home, 'prices.json'), encoding='utf-8') as f:
            extra = json.load(f)
    except (OSError, ValueError):
        return
    for k, v in extra.items() if isinstance(extra, dict) else ():
        if isinstance(v, list) and len(v) in (3, 5) and all(isinstance(x, (int, float)) for x in v):
            TABLE[k.strip().lower()] = tuple(v) if len(v) == 5 else (v[0], v[1], v[2], v[0], v[0])


def bare(model):
    """去掉 [1m] 这类标记和云平台的前缀（anthropic.、us.anthropic.、openai.、google. ……），统一常见简写。"""
    m = re.sub(r'\[[^\]]*\]$', '', (model or '').strip().lower())
    m = re.sub(r'^(?:[\w-]+\.)*(?:anthropic|openai|google|vertex)\.', '', m)
    for p in ('claude-', 'gpt-', 'gemini-'):
        i = m.find(p)
        if i > 0:
            m = m[i:]
            break
    if m.startswith('gemini-'):
        m = re.sub(r'(?:-tiered)?-(?:minimal|low|medium|high|xhigh|max|thinking)$', '', m)
    for k, v in ALIASES.items():
        if m == k or m.startswith(k + '-') or m.startswith(k + '@'):
            return v + m[len(k):]
    return m


@functools.lru_cache(maxsize=None)
def key(model):
    """模型 ID → 价格表里的那一项（取最长的匹配；后面只允许跟日期、preview 或 latest 后缀）。没有返回 None。"""
    m, best = bare(model), None
    for k in TABLE:
        if m == k or (m.startswith(k) and re.match(r'(?:[-@]\d{4}-?\d{2}-?\d{2}|-(?:preview|exp|latest)(?:-\d{2}-\d{2})?$)', m[len(k):])):
            if not best or len(k) > len(best):
                best = k
    return best


def parts(model, speed, inp, out, cr, cw5, cw1h, web):
    """一次回复的费用分项（美元）：(输入, 输出, 读缓存, 写缓存, 网页搜索)。不知道价格时返回 None。"""
    k = key(model)
    if not k:
        return None
    p = TABLE[k]
    if k in TIERS and inp + cr + cw5 + cw1h > TIERS[k][0]:
        p = TIERS[k][1]
    x = FAST.get(k, 1) if speed == 'fast' else 1
    return (inp * p[0] * x / 1e6, out * p[1] * x / 1e6, cr * p[2] * x / 1e6, (cw5 * p[3] + cw1h * p[4]) * x / 1e6,
            web * WEB_SEARCH)


def row_parts(r):
    """index.usage 的一行（或同样字段的字典）→ 费用分项，见 parts。"""
    return parts(r['model'], r['speed'], r['inp'], r['out'], r['cr'], r['cw5'], r['cw1h'], r['web'])


class Tally:
    """一组回复的用量合计。分项费用由调用方算好传进来，同一行加进好几个分组时只算一次。"""
    __slots__ = ('n', 'inp', 'out', 'cr', 'cw', 'web', 'think', 'unpriced', 'parts')

    def __init__(self):
        self.n = self.inp = self.out = self.cr = self.cw = self.web = self.think = self.unpriced = 0
        self.parts = [0.0] * 5

    def add(self, r, p):
        self.n += 1
        self.inp += r['inp']
        self.out += r['out']
        self.cr += r['cr']
        self.cw += r['cw5'] + r['cw1h']
        self.web += r['web']
        self.think += r['think']
        if p is None:
            self.unpriced += 1 if r['inp'] or r['out'] or r['cr'] or r['cw5'] or r['cw1h'] else 0
        else:
            for i in range(5):
                self.parts[i] += p[i]

    @property
    def cost(self):
        return sum(self.parts)

    @property
    def tokens(self):
        return self.inp + self.out + self.cr + self.cw

    def rate(self):
        """缓存命中率：读缓存占全部输入（未缓存的、读缓存、写缓存）的比例。"""
        total = self.inp + self.cr + self.cw
        return self.cr / total if total else None

    def json(self):
        return {'n': self.n, 'input': self.inp, 'output': self.out, 'cache_read': self.cr, 'cache_write': self.cw,
                'thinking': self.think, 'web': self.web, 'tokens': self.tokens, 'cost': round(self.cost, 8),
                'parts': [round(x, 8) for x in self.parts], 'unpriced': self.unpriced, 'rate': self.rate()}


def model_name(model):
    """claude-opus-5-5 → Opus 5.5，gemini-4-neon → Gemini 4 Neon；别的原样返回。"""
    m = bare(model)
    x = re.fullmatch(r'claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:[-@]\d{8})?', m)
    if x:
        return '%s %s%s' % (x.group(1).capitalize(), x.group(2), '.' + x.group(3) if x.group(3) else '')
    x = re.fullmatch(r'claude-(\d+)(?:-(\d+))?-([a-z]+)(?:[-@]\d{8})?', m)
    if x:
        return '%s %s%s' % (x.group(3).capitalize(), x.group(1), '.' + x.group(2) if x.group(2) else '')
    x = re.fullmatch(r'gemini-(\d+(?:\.\d+)?)-([a-z]+(?:-[a-z]+)*?)(?:-(?:preview|exp|latest)(?:-\d{2}-\d{2})?)?', m)
    if x:
        tail = '-'.join(w.capitalize() for w in x.group(2).split('-'))
        return 'Gemini %s %s' % (x.group(1), tail)
    return model or ''
