#!/usr/bin/env python3
"""v9c：最严格"以历史为镜" —— 2025定池 → 2026上半年前向验证。

模拟情境：站在2025-12-31，手里只有2025年及以前的北单历史赛果。
用2025年数据决定"哪些联赛猜1:1 / 猜哪个低比分"，然后穿越到2026-02-11~08-11验证。
只统计下注场次（敢下注才对比），这是用户2026-08-11要求的赛前模拟回测。

策略规则（只用2025数据，赛前完全可得）：
1. 联赛2025年样本≥MIN_N
2. 若2025年该联赛1:1率>12% → 2026上半年该联赛所有场次猜1:1
3. 否则若2025年某低比分率>12% → 猜该低比分
4. 否则不下注
"""
import csv, json, math, re
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

CSV = Path('data/beidan_history_2021_2026.csv')
OUT = Path('backtest_v9c_2025pool.json')
MIN_N = 30
BASE = 0.12
LOW_SCORES = ['1:0', '1:1', '2:1', '0:1', '0:0', '2:0']
TRAIN_YEAR = 2025
TEST_START = datetime(2026, 2, 11)

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

def main():
    rows = load()
    train = [r for r in rows if r['date'].year == TRAIN_YEAR]
    test = [r for r in rows if r['date'] >= TEST_START]
    all_test = len(test)

    # 2025年定池
    cnt = defaultdict(Counter)
    for r in train: cnt[r['league']][r['score']] += 1
    pool = {}  # league -> (pick, why)
    for lg, c in cnt.items():
        n = sum(c.values())
        if n < MIN_N: continue
        r11 = c['1:1'] / n
        if r11 > BASE:
            pool[lg] = ('1:1', f'2025年1:1率{r11*100:.1f}%(n={n})')
        else:
            best = max(LOW_SCORES, key=lambda s: c[s])
            br = c[best] / n
            if br > BASE:
                pool[lg] = (best, f'2025年{best}率{br*100:.1f}%(n={n})')
    print(f'2025年定池联赛: {len(pool)}个（2025年1:1/低比分率>12%且n≥{MIN_N}）')
    for lg, (p, why) in sorted(pool.items()):
        print(f'  {lg:<12} → 猜{p}  ({why})')

    # 2026上半年验证
    n = hit = dir_hit = 0
    per_league = defaultdict(lambda: {'n': 0, 'hit': 0})
    bets = []
    for r in test:
        pick = pool.get(r['league'])
        if pick is None: continue
        sc, why = pick
        n += 1
        is_hit = sc == r['score']
        hit += is_hit
        h, a = map(int, sc.split(':'))
        ph = 'H' if h > a else ('D' if h == a else 'A')
        rh, ra = map(int, r['score'].split(':'))
        ract = 'H' if rh > ra else ('D' if rh == ra else 'A')
        if ph == ract: dir_hit += 1
        st = per_league[r['league']]; st['n'] += 1; st['hit'] += is_hit
        bets.append({'date': str(r['date'])[:10], 'league': r['league'],
                     'home': r['home'], 'away': r['away'],
                     'pick': sc, 'actual': r['score'], 'hit': is_hit, 'why': why})

    rate = hit / n if n else 0
    lo, hi = wilson(hit, n)
    all_11 = sum(1 for r in test if r['score'] == '1:1')
    print(f'\n=== v9c 2025定池 → 2026上半年验证 ===')
    print(f'预测期: {TEST_START.date()} ~ {test[-1]["date"].date()}  总场次: {all_test}')
    print(f'背景: 全场1:1率 {all_11/all_test*100:.2f}%')
    print(f'下注: {n}/{all_test} ({n/all_test*100:.1f}%)')
    print(f'精确: {hit}/{n} = {rate*100:.2f}%  95%CI [{lo*100:.2f}%, {hi*100:.2f}%]  {"✅超12%" if lo > BASE else "❌未超"}')
    print(f'方向: {dir_hit}/{n} = {dir_hit/n*100:.1f}%')

    print(f'\n=== 逐联赛 ===')
    good = []
    for lg, st in sorted(per_league.items(), key=lambda x: -x[1]['hit']/x[1]['n']):
        r = st['hit']/st['n']
        mark = '✅' if r > BASE else ''
        print(f'{lg:<12} {r*100:>5.2f}% (n={st["n"]}, 中{st["hit"]}) {mark}')
        if r > BASE: good.append((lg, r, st['n']))
    print(f'\n超基线联赛: {len(good)}/{len(per_league)}')

    out = {
        'method': 'v9c 2025年数据定池→2026-02-11~08-11前向验证，只统计下注场次',
        'pool_size': len(pool),
        'pool': {lg: {'pick': p, 'why': why} for lg, (p, why) in pool.items()},
        'period': [str(TEST_START.date()), str(test[-1]['date'].date())],
        'all_matches': all_test, 'bet_matches': n,
        'exact_hits': hit, 'exact_rate': round(rate, 4), 'ci95': [lo, hi],
        'direction_rate': round(dir_hit/n, 4) if n else None,
        'background_1v1': round(all_11/all_test, 4),
        'per_league': {lg: {'n': v['n'], 'hit': v['hit'], 'rate': round(v['hit']/v['n'], 4)}
                       for lg, v in sorted(per_league.items(), key=lambda x: -x[1]['hit']/x[1]['n'])},
        'note': '历史CSV无赛前伤病/天气记录，赛前情报属情报缺口；本回测为无情报下限表现'
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n结果已存: {OUT}')

if __name__ == '__main__':
    main()
