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

# Anthropic 官方价目（2026-10）。写缓存：保留 5 分钟是输入价的 1.25 倍，1 小时是 2 倍
CLAUDE = {
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
    'claude-sonnet-5-5': (2, 10, 0.2, 2.5, 4),
    'claude-sonnet-5': (2, 10, 0.2, 2.5, 4),
    'claude-sonnet-4-6': (3, 15, 0.3, 3.75, 6),
    'claude-sonnet-4-5': (3, 15, 0.3, 3.75, 6),
    'claude-sonnet-4': (3, 15, 0.3, 3.75, 6),
    'claude-3-7-sonnet': (3, 15, 0.3, 3.75, 6),
    'claude-haiku-5-5': (0.1, 0.5, 0.01, 0.125, 0.2),
    'claude-haiku-4-5': (1, 5, 0.1, 1.25, 2),
    'claude-3-5-haiku': (0.8, 4, 0.08, 1, 1.6),
}
# OpenAI（Codex 用的模型）：GPT-6 系列取自第三方整理的价目，没有和 OpenAI 官方价目页核对过；
# GPT-5 系列是 2025 年的官方价。OpenAI 不单收写缓存的钱，按输入价计
OPENAI = {
    'gpt-6-astra': (10, 50, 1, 10, 10),
    'gpt-6.1-sol': (2, 10, 0.1, 2.5, 2.5),
    'gpt-6-sol': (2, 10, 0.2, 2, 2),
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
# 一次请求的提示词（输入 + 缓存）超过这么多 token 时整次改用另一档价格
TIERS = {
    'claude-haiku-5-5': (100000, (0.5, 2.5, 0.05, 0.625, 1)),
    'gpt-6-astra': (272000, (20, 75, 2, 20, 20)),
    'gpt-6.1-sol': (272000, (4, 10, 0.2, 2.5, 2.5)),
}
FAST = {'claude-opus-5-5': 2, 'claude-opus-5': 2, 'gpt-6-astra': 2}   # 快速模式的倍数
WEB_SEARCH = 0.01                                         # 每次网页搜索
ALIASES = {'gpt6astra': 'gpt-6-astra'}

TABLE = dict(CLAUDE, **OPENAI)


def configure(home):
    """读入用户自己的价格（prices.json），覆盖或补充内置的。"""
    TABLE.clear()
    TABLE.update(CLAUDE)
    TABLE.update(OPENAI)
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
    """去掉 [1m] 这类标记和云平台的前缀（anthropic.、us.anthropic.、openai. ……），统一常见简写。"""
    m = re.sub(r'\[[^\]]*\]$', '', (model or '').strip().lower())
    m = re.sub(r'^(?:[\w-]+\.)*(?:anthropic|openai)\.', '', m)
    for p in ('claude-', 'gpt-'):
        i = m.find(p)
        if i > 0:
            m = m[i:]
            break
    for k, v in ALIASES.items():
        if m == k or m.startswith(k + '-') or m.startswith(k + '@'):
            return v + m[len(k):]
    return m


@functools.lru_cache(maxsize=None)
def key(model):
    """模型 ID → 价格表里的那一项（取最长的匹配；后面只允许跟日期后缀）。没有返回 None。"""
    m, best = bare(model), None
    for k in TABLE:
        if m == k or (m.startswith(k) and re.match(r'[-@]\d{4}-?\d{2}-?\d{2}', m[len(k):])):
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
    """claude-opus-5-5 → Opus 5.5，claude-3-5-haiku-20241022 → Haiku 3.5；别的原样返回。"""
    m = bare(model)
    x = re.fullmatch(r'claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:[-@]\d{8})?', m)
    if x:
        return '%s %s%s' % (x.group(1).capitalize(), x.group(2), '.' + x.group(3) if x.group(3) else '')
    x = re.fullmatch(r'claude-(\d+)(?:-(\d+))?-([a-z]+)(?:[-@]\d{8})?', m)
    if x:
        return '%s %s%s' % (x.group(3).capitalize(), x.group(1), '.' + x.group(2) if x.group(2) else '')
    return model or ''
