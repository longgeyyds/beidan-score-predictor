#!/usr/bin/env python3
"""v9d：跨年稳定定池 → 2026上半年验证（最忠实的赛前模拟）。

模拟情境：站在2025-12-31，用2024+2025连续两年的北单历史赛果决定联赛池，
只保留"两年都稳定超12%"的联赛（这正是v8发现的跨年信号），然后2026上半年验证。
只统计下注场次。

规则：
1. 联赛在2024年样本≥MIN_N 且 2025年样本≥MIN_N
2. 2024年1:1率>12% 且 2025年1:1率>12% → 猜1:1
3. 否则若2024/2025两年同一低比分都>12% → 猜该低比分
4. 否则不下注
"""
import csv, json, math, re
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

CSV = Path('data/beidan_history_2021_2026.csv')
OUT = Path('backtest_v9d_crossyear.json')
MIN_N = 30
BASE = 0.12
LOW_SCORES = ['1:0', '1:1', '2:1', '0:1', '0:0', '2:0']
YEARS = [2024, 2025]
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
    by_year = {y: defaultdict(Counter) for y in YEARS}
    for r in rows:
        if r['date'].year in by_year:
            by_year[r['date'].year][r['league']][r['score']] += 1
    test = [r for r in rows if r['date'] >= TEST_START]
    all_test = len(test)

    # 跨年定池
    pool = {}
    leagues = set()
    for y in YEARS: leagues |= set(by_year[y].keys())
    for lg in sorted(leagues):
        rates = {}
        ok = True
        for y in YEARS:
            c = by_year[y][lg]
            n = sum(c.values())
            if n < MIN_N: ok = False; break
            r11 = c['1:1'] / n
            best = max(LOW_SCORES, key=lambda s: c[s])
            br = c[best] / n
            rates[y] = (n, r11, best, br)
        if not ok: continue
        (n24, r11_24, b24, br24), (n25, r11_25, b25, br25) = rates[2024], rates[2025]
        if r11_24 > BASE and r11_25 > BASE:
            pool[lg] = ('1:1', f'24年1:1{r11_24*100:.1f}%(n={n24})/25年{r11_25*100:.1f}%(n={n25})')
        elif b24 == b25 and br24 > BASE and br25 > BASE:
            pool[lg] = (b24, f'24年{b24}{br24*100:.1f}%(n={n24})/25年{br25*100:.1f}%(n={n25})')
    print(f'跨年稳定池: {len(pool)}个联赛（2024+2025两年同一比分率都>12%）')
    for lg, (p, why) in sorted(pool.items()):
        print(f'  {lg:<12} → 猜{p}  ({why})')

    # 验证
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
    print(f'\n=== v9d 跨年稳定池 → 2026上半年验证 ===')
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
        'method': 'v9d 2024+2025连续两年同一比分率>12%定池→2026-02-11~08-11验证，只统计下注场次',
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
