#!/usr/bin/env python3
"""v8：联赛众数比分策略 —— 稳定超基线验证。

核心发现：用"联赛识别 + 该联赛滚动众数比分"猜，
2025和2026两年独立验证都超12%基线。

进一步细分：加入"主/客/均势"条件，看能否再提高。
"""
import csv, json, math
from collections import defaultdict, deque, Counter
from datetime import datetime
from pathlib import Path

CSV = Path('data/beidan_history_2021_2026.csv')
OUT = Path('backtest_v8_league_mode.json')

def load():
    rows = []
    with CSV.open(encoding='utf-8-sig', newline='') as f:
        for x in csv.DictReader(f):
            try:
                dt = datetime.fromisoformat(x['cutoff_time'])
                h = int(x['ft_home']); a = int(x['ft_away'])
            except Exception: continue
            if h < 0 or a < 0 or h > 15 or a > 15: continue
            rows.append({'date': dt, 'league': x['league'], 'home': x['home'], 'away': x['away'],
                         'hg': h, 'ag': a, 'score': f'{h}:{a}'})
    return sorted(rows, key=lambda r: r['date'])

def wilson(k, n):
    if not n: return (0, 0)
    p = k / n; z = 1.96
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    m = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return c - m, c + m

def main():
    rows = load()
    # 用2026前半（1-6月）学众数 → 2026后半验证 太短；改用2025学 → 2026验证（真正时间前向）
    # 方案：2025年数据积累联赛众数，2026年用它预测
    train = [r for r in rows if r['date'].year == 2025]
    test = [r for r in rows if r['date'].year == 2026]
    # 从train学每个联赛的众数比分
    league_counter = Counter()
    for r in train:
        league_counter[r['league']] += 1
        # 需要比分频率
    league_mode = {}
    cnt = defaultdict(Counter)
    for r in train:
        cnt[r['league']][r['score']] += 1
    for lg, c in cnt.items():
        if sum(c.values()) >= 30:  # 样本门槛
            league_mode[lg] = c.most_common(1)[0][0]
    print(f'从2025学到众数的联赛: {len(league_mode)}个')
    # 2026验证
    n = hit = 0
    per_league = {}
    for r in test:
        mode = league_mode.get(r['league'])
        if mode is None: continue
        n += 1
        is_hit = mode == r['score']
        hit += is_hit
        st = per_league.setdefault(r['league'], {'n': 0, 'hit': 0, 'mode': mode})
        st['n'] += 1; st['hit'] += is_hit
    rate = hit / n if n else 0
    lo, hi = wilson(hit, n)
    print(f'\n=== v8 联赛众数策略 ===')
    print(f'2026验证: {hit}/{n} = {rate*100:.2f}%  95%CI [{lo*100:.2f}%, {hi*100:.2f}%]')
    print(f'基线12%: {"✅ 显著超基线" if lo > 0.12 else "❌ 未达"}')
    # 逐联赛
    print(f'\n=== 逐联赛（2025学→2026测）===')
    good = []
    for lg, st in sorted(per_league.items(), key=lambda x: -x[1]['hit']/x[1]['n']):
        if st['n'] < 40: continue
        r = st['hit']/st['n']
        mark = '✅' if r > 0.13 else ''
        print(f'{lg:<14} 众数[{st["mode"]}] {r*100:>5.2f}% (n={st["n"]}) {mark}')
        if r > 0.12: good.append((lg, st['mode'], r, st['n']))
    out = {'method': 'v8 联赛众数比分：2025学习→2026前向验证', 'n': n, 'hit': hit,
           'rate': rate, 'ci95': [lo, hi], 'good_leagues': good}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n超12%联赛: {len(good)}个')

if __name__ == '__main__':
    main()
