#!/usr/bin/env python3
"""v9：半年严格滚动回测 —— 模拟赛前状况，只对比下注场次。

原则（2026-08-11 用户要求）：
1. 以历史为镜：预测期近半年（2026-02-11 起），每场只用该场 cutoff 之前可得的全部历史。
2. 模拟赛前状况：训练窗口 = 该场之前 365 天同联赛数据（近期画面优先），严格防泄漏。
3. 只对比下注场次：规则不达标就不下注、不统计——不拿全场次对比，只看敢下注的场次命中率。
4. 策略来自 v8 验证：特定联赛猜 1:1 有跨年稳定优势；备选低比分组最优项。

诚实声明：历史 CSV 只有赛果比分，没有赛前伤病/天气/阵容记录——
赛前情报在历史回测中属于"情报缺口"，本回测无法模拟，只能给出无情报时的下限表现。
"""
import csv, json, math, re
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path
from bisect import bisect_left

CSV = Path('data/beidan_history_2021_2026.csv')
OUT = Path('backtest_v9_halfyear_strict.json')
PRED_START = datetime(2026, 2, 11)   # 预测期起点（近半年）
TRAIN_WIN = timedelta(days=365)      # 训练窗口：该场之前365天
MIN_N = 30                           # 联赛样本门槛
BASE_RATE = 0.12                     # 历史众数基线
LOW_SCORES = ['1:0', '1:1', '2:1', '0:1', '0:0', '2:0']  # 低比分组

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

def pick_from_window(scores):
    """给定窗口内比分列表，返回 (预测比分, 依据) 或 None(不下注)。"""
    n = len(scores)
    if n < MIN_N: return None
    cnt = Counter(scores)
    r11 = cnt['1:1'] / n
    if r11 > BASE_RATE:
        return ('1:1', f'1:1率{r11*100:.1f}%(n={n})')
    # 备选：低比分组里最优项
    best = max(LOW_SCORES, key=lambda s: cnt[s])
    br = cnt[best] / n
    if br > BASE_RATE:
        return (best, f'{best}率{br*100:.1f}%(n={n})')
    return None

def main():
    rows = load()
    # 按联赛分组（组内按日期排序）
    by_league = defaultdict(list)
    for r in rows:
        by_league[r['league']].append(r)
    for lg in by_league:
        by_league[lg].sort(key=lambda r: r['date'])
    dates = {lg: [r['date'] for r in lst] for lg, lst in by_league.items()}

    # 预计算预测期场次
    test = [r for r in rows if r['date'] >= PRED_START]
    all_test = len(test)

    n = hit = dir_hit = no_bet = 0
    per_league = defaultdict(lambda: {'n': 0, 'hit': 0})
    bets = []
    for r in test:
        lg = r['league']
        lst = by_league[lg]; ds = dates[lg]
        # 窗口 = [date-365d, date)，二分定位
        lo = bisect_left(ds, r['date'] - TRAIN_WIN)
        hi = bisect_left(ds, r['date'])   # 严格不含当天（当天同期的也算赛前可得，但保守起见不含）
        scores = [x['score'] for x in lst[lo:hi]]
        pick = pick_from_window(scores)
        if pick is None:
            no_bet += 1
        else:
            sc, why = pick
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
                         'pick': sc, 'actual': r['score'], 'hit': is_hit, 'why': why})

    rate = hit / n if n else 0
    lo, hi = wilson(hit, n)
    print(f'预测期: {PRED_START.date()} ~ {test[-1]["date"].date()}  总场次(预测期): {all_test}')
    print(f'下注场次: {n}  跳过: {no_bet}  下注占比: {n/all_test*100:.1f}%')
    print(f'\n=== v9 半年严格滚动回测 ===')
    print(f'精确命中: {hit}/{n} = {rate*100:.2f}%  95%CI [{lo*100:.2f}%, {hi*100:.2f}%]')
    print(f'基线12%: {"✅ 显著超基线" if lo > BASE_RATE else "❌ 未超基线"}')
    print(f'方向命中: {dir_hit}/{n} = {dir_hit/n*100:.1f}%')
    # 全场1:1参照（仅作背景，不参与对比）
    all_11 = sum(1 for r in test if r['score'] == '1:1')
    print(f'（背景参照：预测期全场1:1率 {all_11/all_test*100:.2f}% = 基线）')
    print(f'\n=== 逐联赛（下注场次）===')
    good = []
    for lg, st in sorted(per_league.items(), key=lambda x: -x[1]['hit']/x[1]['n']):
        r = st['hit']/st['n']
        mark = '✅' if r > BASE_RATE else ''
        print(f'{lg:<14} {r*100:>5.2f}% (n={st["n"]}, 中{st["hit"]}) {mark}')
        if r > BASE_RATE: good.append((lg, r, st['n']))
    print(f'\n超基线联赛: {len(good)}/{len(per_league)}')

    out = {
        'method': 'v9 半年严格滚动回测：每场只用此前365天同联赛数据，只统计下注场次',
        'period': [str(PRED_START.date()), str(test[-1]['date'].date())],
        'all_matches': all_test, 'bet_matches': n, 'no_bet': no_bet,
        'exact_hits': hit, 'exact_rate': round(rate, 4), 'ci95': [lo, hi],
        'direction_hits': dir_hit, 'direction_rate': round(dir_hit/n, 4) if n else None,
        'baseline': BASE_RATE, 'vs_baseline': round(rate - BASE_RATE, 4),
        'per_league': {lg: {'n': v['n'], 'hit': v['hit'], 'rate': round(v['hit']/v['n'], 4)}
                       for lg, v in sorted(per_league.items(), key=lambda x: -x[1]['hit']/x[1]['n'])},
        'sample_bets': bets[:40],
        'note': '历史CSV无赛前伤病/天气记录，赛前情报属情报缺口；本回测为无情报下限表现'
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n结果已存: {OUT}')

if __name__ == '__main__':
    main()
