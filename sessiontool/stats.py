"""总的统计：全部会话的用量、费用（按 API 价格估算）、缓存命中率，按天、模型、推理强度、账号、项目、时段分组；
各账号的额度用量。结果可以直接转成 JSON，页面脚本画图。"""
import collections
from datetime import datetime, timedelta

from . import pricing

SLOTS = 6           # 图上单独着色的模型数，其余并成“其他”


def when(ts):
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
    except (AttributeError, ValueError):
        return None


def streaks(days, today):
    """(最长连续天数, 截至今天的连续天数)。今天还没用也不算断。"""
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    cur, d = 0, today if today in days else today - timedelta(days=1)
    while d in days:
        cur += 1
        d -= timedelta(days=1)
    return best, cur


def compute(cat, src='', account='', days=0):
    """src：claude / codex / 空（全部）；account：账号的 key，空是全部；days：只看最近几天，0 是全部。"""
    now = datetime.now().astimezone()
    today = now.date()
    start = today - timedelta(days=days - 1) if days else None
    rows = cat.index.usage()
    # 模型的颜色按全部时间的花费排定，筛选时不变色
    order = collections.Counter()
    for r in rows:
        order[r['model']] += sum(pricing.row_parts(r) or ()) or r['out'] / 1e6
    slot = {m: i for i, (m, _) in enumerate(order.most_common(SLOTS))}

    def keep(s):
        return s and (not src or s.src == src) and (not account or s.account == account)

    total = pricing.Tally()
    by_day, by_model, by_effort = collections.defaultdict(pricing.Tally), collections.defaultdict(pricing.Tally), collections.defaultdict(pricing.Tally)
    by_acct, by_proj, by_sess = collections.defaultdict(pricing.Tally), collections.defaultdict(pricing.Tally), collections.defaultdict(pricing.Tally)
    day_model = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0]))
    hours = [[0] * 24 for _ in range(7)]
    active, sess_seen = set(), set()
    for r in rows:
        s = cat.by_cli.get(r['sid']) or cat.owner.get(r['file'])
        if not keep(s):
            continue
        t = when(r['ts'])
        if not t or (start and t.date() < start):
            continue
        p = pricing.row_parts(r)
        d = t.date()
        for tally in (total, by_day[d], by_model[r['model']], by_effort[r['effort']], by_acct[s.account],
                      by_proj[(s.src, s.proj)], by_sess[s.id]):
            tally.add(r, p)
        cell = day_model[d][slot.get(r['model'], SLOTS)]
        cell[0] += sum(p) if p else 0
        cell[1] += r['inp'] + r['out'] + r['cr'] + r['cw5'] + r['cw1h']
        hours[t.weekday()][t.hour] += 1
        active.add(d)
        sess_seen.add(s.id)
    # 提问和工具调用来自整理好的会话条目；复刻的会话只数复刻点之后的，之前的是原会话的
    prompts, tools, per_day_prompts = 0, 0, collections.Counter()
    by_id = {s.id: s for s in cat.sessions}
    for s in cat.sessions:
        if not keep(s):
            continue
        items = cat.content(s)['items']
        fork = next((i for i, it in enumerate(items) if it['kind'] == 'fork'), None) if s.parent else None
        for it in items[fork + 1:] if fork is not None else items:
            if it['kind'] not in ('user', 'tools'):
                continue
            t = when(it['ts'])
            if not t or (start and t.date() < start):
                continue
            if it['kind'] == 'user':
                prompts += 1
                per_day_prompts[t.date()] += 1
                sess_seen.add(s.id)
                active.add(t.date())
            else:
                tools += len(it['tools'])
    first = start or min(active, default=today)
    span = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    best, cur = streaks(active, today)
    peak = max(((w, h) for w in range(7) for h in range(24)), key=lambda x: hours[x[0]][x[1]])
    fav = max(by_model.items(), key=lambda kv: kv[1].n, default=(None, None))

    def acct_info(key):
        a = cat.accounts.get(key) or {}
        return {'key': key, 'name': a.get('name') or '（未知账号）', 'email': a.get('email', ''), 'src': a.get('src', '')}

    sessions_in = collections.Counter(by_id[i].account for i in sess_seen if i in by_id)
    proj_sessions = collections.Counter((by_id[i].src, by_id[i].proj) for i in sess_seen if i in by_id)
    models = [dict(t.json(), model=m, name=pricing.model_name(m) or '（未知）', slot=slot.get(m, SLOTS), priced=bool(pricing.key(m)))
              for m, t in sorted(by_model.items(), key=lambda kv: (-kv[1].cost, -kv[1].n))]
    return {
        'range': {'days': days, 'from': span[0].isoformat(), 'to': today.isoformat()},
        'filters': {'src': src, 'account': account},
        'accounts': sorted((acct_info(k) for k in cat.accounts), key=lambda a: (a['src'], a['name'])),
        'total': total.json(), 'sessions': len(sess_seen), 'prompts': prompts, 'tools': tools,
        'active_days': len(active), 'streak': cur, 'best_streak': best,
        'peak': {'weekday': peak[0], 'hour': peak[1], 'n': hours[peak[0]][peak[1]]} if total.n else None,
        'favorite': {'name': pricing.model_name(fav[0]), 'share': fav[1].n / total.n} if fav[1] and total.n else None,
        'slots': [pricing.model_name(m) for m, _ in order.most_common(SLOTS)],
        'days': [{'d': d.isoformat(), 'cost': round(by_day[d].cost, 6) if d in by_day else 0,
                  'tokens': by_day[d].tokens if d in by_day else 0, 'n': by_day[d].n if d in by_day else 0,
                  'prompts': per_day_prompts[d], 'rate': by_day[d].rate() if d in by_day else None,
                  'models': [[k, round(v[0], 6), v[1]] for k, v in sorted(day_model[d].items())]} for d in span],
        'hours': hours,
        'models': models,
        'efforts': [dict(t.json(), effort=e) for e, t in sorted(by_effort.items(), key=lambda kv: -kv[1].n)],
        'by_account': [dict(t.json(), sessions=sessions_in[k], **acct_info(k))
                       for k, t in sorted(by_acct.items(), key=lambda kv: -kv[1].cost)],
        'projects': [dict(t.json(), src=k[0], proj=k[1], sessions=proj_sessions[k])
                     for k, t in sorted(by_proj.items(), key=lambda kv: -kv[1].cost)[:20]],
        'top': [dict(t.json(), page=by_id[i].page, title=cat.content(by_id[i])['title'], proj=by_id[i].proj, src=by_id[i].src,
                     account=(cat.account(by_id[i]) or {}).get('name', ''))
                for i, t in sorted(by_sess.items(), key=lambda kv: -kv[1].cost)[:12] if i in by_id],
        'quota': quota(cat, account),
    }


def quota(cat, account=''):
    """各账号最近一次记下的额度用量（5 小时窗口、7 天窗口），和最近 7 天里 7 天窗口用量的走势。"""
    org_acct = {}
    for s in cat.sessions:
        if s.org and s.account:
            org_acct.setdefault(s.org, s.account)
    cut = (datetime.now().timestamp() - 7 * 86400) * 1000
    latest, trend = {}, collections.defaultdict(list)
    for org, t, fh, sd in cat.sources.plan_usage():
        latest[org] = (t, fh, sd)
        if t >= cut and isinstance(sd, (int, float)):
            trend[org].append((t, sd))
    out = []
    for org, (t, fh, sd) in latest.items():
        key = org_acct.get(org, '')
        if account and key != account:
            continue
        a = cat.accounts.get(key) or {}
        pts = trend[org]
        step = max(1, len(pts) // 60)          # 走势线最多留六十来个点
        out.append({'org': org, 'account': a.get('name') or org[:8], 'email': a.get('email', ''), 't': t,
                    'five_hour': fh, 'seven_day': sd, 'trend': pts[::step]})
    out.sort(key=lambda q: -q['t'])
    return out
