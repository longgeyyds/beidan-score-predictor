#!/usr/bin/env python3
"""v10：画面驱动 + 联赛先验校准 —— "按实际预测"模型。

用户要求（2026-08-11）：按实际情况预测，不套概率（不无脑猜1:1）。
本模型把"预测"拆成两层：

【选场层】只用已验证的统计信号决定"哪些场次值得下注"：
  1. 跨年稳定池（2024+2025连续两年1:1率>12%的联赛）——这些联赛值得深入分析
  2. 双方近8场画面完整（≥5场）

【比分层】每场按实际画面生成比分（非固定猜1:1）：
  1. 双方近8场攻防 → 期望进球 lh/la（主攻vs客防、客攻vs主防）
  2. 大球属性 → 比赛性格（双大/单边/双闷/混合）
  3. 期望进球 → Poisson 候选比分分布（画面证据）
  4. 联赛滚动365天比分分布（先验，防泄漏只用赛前）与画面分布混合：
     P = w×P_league + (1-w)×P_poisson
  5. 取Top1下注

严格防泄漏：每场只用该场 cutoff 之前的数据（画面、联赛先验均不含当场）。
只统计下注场次（选场层过滤后）。
"""
import csv, json, math, re
from collections import defaultdict, deque, Counter
from datetime import datetime, timedelta
from pathlib import Path
from bisect import bisect_left

CSV = Path('data/beidan_history_2021_2026.csv')
OUT = Path('backtest_v10_actual.json')
TEST_START = datetime(2026, 2, 11)
MIN_N = 30          # 跨年池联赛样本门槛
BASE = 0.12
YEARS = [2024, 2025]
W = 0.4             # 联赛先验权重（固定，防过拟合）
SCORES = ['0:0','1:0','0:1','1:1','2:0','0:2','2:1','1:2','2:2',
          '3:0','0:3','3:1','1:3','3:2','2:3','4:0','0:4']

def norm_league(s):
    s = re.sub(r'^(?:20)?\d{2}[-/]\d{2}', '', (s or '').strip())
    s = re.sub(r'^20\d{2}', '', s)
    s = re.sub(r'^\d{2}(?=[\u4e00-\u9fffA-Za-z])', '', s)
    return s or '未知赛事'

def load():
    rows = []
    with CSV.open(encoding='utf-8-sig', newline='') as f:
        for x in csv.DictReader(f):
            try:
                dt = datetime.fromisoformat(x['cutoff_time'].replace(' ', 'T'))
                h = int(x['ft_home']); a = int(x['ft_away'])
            except Exception:
                continue
            if h < 0 or a < 0 or h > 15 or a > 15: continue
            rows.append({'date': dt, 'league': norm_league(x['league']),
                         'home': x['home'], 'away': x['away'],
                         'hg': h, 'ag': a, 'score': f'{h}:{a}'})
    rows.sort(key=lambda r: r['date'])
    return rows

def wilson(k, n):
    if not n: return (0, 0)
    p = k / n; z = 1.96
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    m = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return c - m, c + m

def poisson_pmf(lmb, k):
    return math.exp(-lmb) * lmb**k / math.factorial(k)

def score_prob(lh, la):
    """画面证据：Poisson 生成候选比分概率（期望进球 → 分布）"""
    d = {}
    for s in SCORES:
        h, a = map(int, s.split(':'))
        if h <= 4 and a <= 4:
            d[s] = poisson_pmf(lh, h) * poisson_pmf(la, a)
    # 其余归入胜其它/负其它，不算候选
    return d

def main():
    rows = load()

    # 跨年池（同v9d：2024+2025连续两年1:1率>12%）
    by_year = {y: defaultdict(Counter) for y in YEARS}
    for r in rows:
        if r['date'].year in by_year:
            by_year[r['date'].year][r['league']][r['score']] += 1
    pool = set()
    leagues = set()
    for y in YEARS: leagues |= set(by_year[y].keys())
    for lg in sorted(leagues):
        rates = {}
        ok = True
        for y in YEARS:
            c = by_year[y][lg]
            n = sum(c.values())
            if n < MIN_N: ok = False; break
            rates[y] = c['1:1'] / n
        if ok and rates[2024] > BASE and rates[2025] > BASE:
            pool.add(lg)
    print(f'跨年稳定池: {len(pool)}个联赛: {sorted(pool)}')

    # 按联赛分组 + 日期索引（用于滚动先验）
    by_league = defaultdict(list)
    for r in rows: by_league[r['league']].append(r)
    for lg in by_league: by_league[lg].sort(key=lambda r: r['date'])
    dates = {lg: [r['date'] for r in lst] for lg, lst in by_league.items()}

    # 每队滚动近10场画面（防泄漏：只用该场之前）
    recent = defaultdict(lambda: deque(maxlen=10))

    def prof(t):
        g = recent[t]
        if len(g) < 5: return None
        gf = sum(x['gf'] for x in g)/len(g)
        ga = sum(x['ga'] for x in g)/len(g)
        big = sum(1 for x in g if x['gf']+x['ga'] >= 3)/len(g)
        home = [x for x in g if x['home']]
        away = [x for x in g if not x['home']]
        hgf = sum(x['gf'] for x in home)/len(home) if home else gf
        hga = sum(x['ga'] for x in home)/len(home) if home else ga
        agf = sum(x['gf'] for x in away)/len(away) if away else gf
        aga = sum(x['ga'] for x in away)/len(away) if away else ga
        return {'gf': gf, 'ga': ga, 'big': big, 'hgf': hgf, 'hga': hga,
                'agf': agf, 'aga': aga}

    test = [r for r in rows if r['date'] >= TEST_START]
    all_test = len(test)

    n = hit = dir_hit = skipped_pool = skipped_data = 0
    bets = []
    per_league = defaultdict(lambda: {'n': 0, 'hit': 0})
    for r in test:
        lg = r['league']
        # 选场层1：跨年池
        if lg not in pool:
            skipped_pool += 1
            # 更新画面后继续
            recent[r['home']].append({'gf': r['hg'], 'ga': r['ag'], 'home': True})
            recent[r['away']].append({'gf': r['ag'], 'ga': r['hg'], 'home': False})
            continue
        hp, ap = prof(r['home']), prof(r['away'])
        if hp is None or ap is None:
            skipped_data += 1
            recent[r['home']].append({'gf': r['hg'], 'ga': r['ag'], 'home': True})
            recent[r['away']].append({'gf': r['ag'], 'ga': r['hg'], 'home': False})
            continue

        # ===== 比分层：按实际画面生成 =====
        # 1. 期望进球
        lh = (hp['hgf'] + ap['aga']) / 2
        la = (ap['agf'] + hp['hga']) / 2
        # 2. 性格（大球属性）
        if hp['big'] >= 0.6 and ap['big'] >= 0.6: char = '双大'
        elif hp['big'] >= 0.6 and ap['big'] <= 0.4: char = '主大客闷'
        elif ap['big'] >= 0.6 and hp['big'] <= 0.4: char = '客大主闷'
        elif hp['big'] <= 0.4 and ap['big'] <= 0.4: char = '双闷'
        else: char = '混合'
        # 3. 画面证据（Poisson）
        pv = score_prob(lh, la)
        # 4. 联赛滚动365天先验（防泄漏：不含当场）
        lst = by_league[lg]; ds = dates[lg]
        lo = bisect_left(ds, r['date'] - timedelta(days=365))
        hi = bisect_left(ds, r['date'])
        hist = [x['score'] for x in lst[lo:hi]]
        cnt = Counter(hist)
        tn = len(hist)
        pl = {s: cnt[s]/tn for s in SCORES}
        # 5. 混合
        pf = {s: W*pl.get(s, 0) + (1-W)*pv.get(s, 0) for s in SCORES}
        pick = max(pf, key=pf.get)
        pick_p = pf[pick]

        # ===== 结算 =====
        n += 1
        is_hit = pick == r['score']
        hit += is_hit
        hh, aa = map(int, pick.split(':'))
        ph = 'H' if hh > aa else ('D' if hh == aa else 'A')
        rh, ra = map(int, r['score'].split(':'))
        ract = 'H' if rh > ra else ('D' if rh == ra else 'A')
        if ph == ract: dir_hit += 1
        st = per_league[lg]; st['n'] += 1; st['hit'] += is_hit
        bets.append({'date': str(r['date'])[:10], 'league': lg,
                     'home': r['home'], 'away': r['away'],
                     'pick': pick, 'actual': r['score'], 'hit': is_hit,
                     'char': char, 'lh': round(lh, 2), 'la': round(la, 2),
                     'p': round(pick_p, 4)})
        # 更新画面（当场结果，下一场才可见）
        recent[r['home']].append({'gf': r['hg'], 'ga': r['ag'], 'home': True})
        recent[r['away']].append({'gf': r['ag'], 'ga': r['hg'], 'home': False})

    rate = hit / n if n else 0
    lo, hi = wilson(hit, n)
    # 参照：同场次无脑猜1:1（对照组，同一选场范围）
    ref_11 = sum(1 for b in bets if b['actual'] == '1:1')
    print(f'\n=== v10 画面驱动+联赛先验 (w={W}) ===')
    print(f'预测期: {TEST_START.date()} ~ {test[-1]["date"].date()}  总场次: {all_test}')
    print(f'跨年池内: {n + skipped_data}  画面不足跳过: {skipped_data}  池外跳过: {skipped_pool}')
    print(f'下注: {n}  精确: {hit}/{n} = {rate*100:.2f}%  95%CI [{lo*100:.2f}%, {hi*100:.2f}%]  {"✅超12%" if lo > BASE else "❌未超"}')
    print(f'方向: {dir_hit}/{n} = {dir_hit/n*100:.1f}%')
    print(f'（对照组：同一选场范围无脑猜1:1 → {ref_11}/{n} = {ref_11/n*100:.2f}%）')

    # 选出的比分构成
    pick_cnt = Counter(b['pick'] for b in bets)
    print(f'\n=== 预测比分构成 ===')
    for s, c in pick_cnt.most_common(12):
        print(f'  {s}: {c}次 ({c/n*100:.1f}%)')

    print(f'\n=== 逐联赛 ===')
    good = []
    for lg, st in sorted(per_league.items(), key=lambda x: -x[1]['hit']/x[1]['n']):
        r2 = st['hit']/st['n']
        mark = '✅' if r2 > BASE else ''
        print(f'{lg:<12} {r2*100:>5.2f}% (n={st["n"]}, 中{st["hit"]}) {mark}')
        if r2 > BASE: good.append((lg, r2, st['n']))
    print(f'\n超基线联赛: {len(good)}/{len(per_league)}')

    out = {
        'method': 'v10 画面驱动(Poisson)+联赛滚动先验混合，跨年池选场，只统计下注场次',
        'w': W, 'period': [str(TEST_START.date()), str(test[-1]['date'].date())],
        'all_matches': all_test, 'pool_leagues': len(pool),
        'skipped_pool': skipped_pool, 'skipped_data': skipped_data,
        'bet_matches': n, 'exact_hits': hit, 'exact_rate': round(rate, 4), 'ci95': [lo, hi],
        'direction_rate': round(dir_hit/n, 4) if n else None,
        'ref_1v1_same_pool': round(ref_11/n, 4) if n else None,
        'pick_dist': {s: c for s, c in pick_cnt.most_common()},
        'per_league': {lg: {'n': v['n'], 'hit': v['hit'], 'rate': round(v['hit']/v['n'], 4)}
                       for lg, v in sorted(per_league.items(), key=lambda x: -x[1]['hit']/x[1]['n'])},
        'note': '历史CSV无赛前伤病/天气记录——比分层的情报修正无法回测；此为无情报下限'
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n结果已存: {OUT}')

if __name__ == '__main__':
    main()
