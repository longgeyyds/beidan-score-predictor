#!/usr/bin/env python3
"""v9e：跨年稳定池 + 动态画面过滤 → 2026上半年验证。

模拟完整赛前判断流程（skill铁律）：
1. 联赛池：2024+2025连续两年1:1率>12% → 猜1:1（v9d）
2. 动态过滤：查双方该场之前近8场的大球属性（≥3球场次占比）：
   - 任一方近期≥60%大球 → 该队1:1概率打折，跳过（大球属性队不踢1:1）
   - 双方都≤40%大球（双闷）→ 1:1信心加强，下注
   - 中间（单闷）→ 保留但标记
3. 只统计最终下注场次。

严格防泄漏：双方近8场只用该场 cutoff 之前的比赛。
"""
import csv, json, math, re
from collections import defaultdict, deque, Counter
from datetime import datetime
from pathlib import Path

CSV = Path('data/beidan_history_2021_2026.csv')
OUT = Path('backtest_v9e_dynamic.json')
MIN_N = 30
BASE = 0.12
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

    # 跨年定池（同v9d）
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
            rates[y] = c['1:1'] / n
        if ok and rates[2024] > BASE and rates[2025] > BASE:
            pool[lg] = ('1:1', f'24年{rates[2024]*100:.1f}%/25年{rates[2025]*100:.1f}%')
    print(f'跨年稳定池: {len(pool)}个联赛')

    # 动态画面：每队滚动近8场大球属性（只用历史）
    team_big = defaultdict(lambda: deque(maxlen=8))  # team -> 该场之前近8场的≥3球标记

    n = hit = dir_hit = 0
    skipped_big = 0
    per_league = defaultdict(lambda: {'n': 0, 'hit': 0})
    bets = []
    for r in test:
        lg = r['league']
        pick = pool.get(lg)
        if pick is None:
            # 不在池里也更新画面
            pass
        else:
            sc, why = pick
            hb = team_big[r['home']]; ab = team_big[r['away']]
            hbig = sum(hb)/len(hb) if hb else None
            abig = sum(ab)/len(ab) if ab else None
            # 动态过滤：任一方明确大球属性(≥60%) → 1:1信心不足，跳过
            if hbig is not None and abig is not None and (hbig >= 0.6 or abig >= 0.6):
                skipped_big += 1
            else:
                n += 1
                is_hit = sc == r['score']
                hit += is_hit
                h, a = map(int, sc.split(':'))
                ph = 'H' if h > a else ('D' if h == a else 'A')
                rh, ra = map(int, r['score'].split(':'))
                ract = 'H' if rh > ra else ('D' if rh == ra else 'A')
                if ph == ract: dir_hit += 1
                st = per_league[lg]; st['n'] += 1; st['hit'] += is_hit
                bets.append({'date': str(r['date'])[:10], 'league': lg,
                             'home': r['home'], 'away': r['away'],
                             'pick': sc, 'actual': r['score'], 'hit': is_hit,
                             'hbig': round(hbig, 2) if hbig is not None else None,
                             'abig': round(abig, 2) if abig is not None else None})
        # 更新两队画面（该场本身，下一场才能用）
        team_big[r['home']].append(1 if r['hg'] + r['ag'] >= 3 else 0)
        team_big[r['away']].append(1 if r['hg'] + r['ag'] >= 3 else 0)

    rate = hit / n if n else 0
    lo, hi = wilson(hit, n)
    all_11 = sum(1 for r in test if r['score'] == '1:1')
    print(f'\n=== v9e 跨年池 + 动态大球过滤 ===')
    print(f'预测期: {TEST_START.date()} ~ {test[-1]["date"].date()}  总场次: {all_test}')
    print(f'背景: 全场1:1率 {all_11/all_test*100:.2f}%')
    print(f'池内场次(不过滤): {n + skipped_big}  大球过滤跳过: {skipped_big}')
    print(f'最终下注: {n}  精确: {hit}/{n} = {rate*100:.2f}%  95%CI [{lo*100:.2f}%, {hi*100:.2f}%]  {"✅超12%" if lo > BASE else "❌未超"}')
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
        'method': 'v9e 跨年稳定池(2024+2025>12%)+动态大球属性过滤→2026上半年验证',
        'pool_size': len(pool),
        'period': [str(TEST_START.date()), str(test[-1]['date'].date())],
        'all_matches': all_test, 'in_pool': n + skipped_big, 'skipped_big': skipped_big,
        'bet_matches': n, 'exact_hits': hit, 'exact_rate': round(rate, 4), 'ci95': [lo, hi],
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
