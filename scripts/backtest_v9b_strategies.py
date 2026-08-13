#!/usr/bin/env python3
"""v9b：半年严格滚动回测 —— 三种选场策略对比。

原则（2026-08-11 用户要求）：
1. 以历史为镜：预测期近半年（2026-02-11 起），每场只用该场 cutoff 之前可得的全部历史。
2. 模拟赛前状况：训练窗口 = 该场之前 365 天同联赛数据，严格防泄漏。
3. 只对比下注场次：规则不达标就不下注、不统计——不拿全场次对比，只看敢下注的场次命中率。
4. 三种策略对比：
   A. v8 固定联赛池猜 1:1（跨年验证的固定知识，赛前已知）
   B. 滚动学习（1:1率>12% 或 最优低比分>12% 才下注）——即v9
   C. 滚动学习高阈值（>13% 才下注，更挑剔）

诚实声明：历史 CSV 只有赛果比分，没有赛前伤病/天气/阵容记录——
赛前情报在历史回测中属于"情报缺口"，本回测无法模拟，只能给出无情报时的下限表现。
"""
import csv, json, math, re
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path
from bisect import bisect_left

CSV = Path('data/beidan_history_2021_2026.csv')
OUT = Path('backtest_v9b_strategies.json')
PRED_START = datetime(2026, 2, 11)
TRAIN_WIN = timedelta(days=365)
MIN_N = 30
LOW_SCORES = ['1:0', '1:1', '2:1', '0:1', '0:0', '2:0']
V8_POOL = {'英冠', '意乙', '波兰甲', '瑞士超', '澳超', '瑞典超', '巴西乙', '英联杯', '足总杯'}

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

class Bet:
    def __init__(self):
        self.n = 0; self.hit = 0; self.dir_hit = 0
        self.bets = []; self.per_league = defaultdict(lambda: {'n': 0, 'hit': 0})
    def add(self, r, sc, why):
        self.n += 1
        is_hit = sc == r['score']
        self.hit += is_hit
        h, a = map(int, sc.split(':'))
        ph = 'H' if h > a else ('D' if h == a else 'A')
        rh, ra = map(int, r['score'].split(':'))
        ract = 'H' if rh > ra else ('D' if rh == ra else 'A')
        if ph == ract: self.dir_hit += 1
        st = self.per_league[r['league']]; st['n'] += 1; st['hit'] += is_hit
        self.bets.append({'date': str(r['date'])[:10], 'league': r['league'],
                          'home': r['home'], 'away': r['away'],
                          'pick': sc, 'actual': r['score'], 'hit': is_hit, 'why': why})

def summarize(name, bet, all_test, note=''):
    rate = bet.hit / bet.n if bet.n else 0
    lo, hi = wilson(bet.hit, bet.n)
    print(f'\n=== {name} ===')
    print(f'下注: {bet.n}/{all_test} ({bet.n/all_test*100:.1f}%)  跳过: {all_test-bet.n}')
    print(f'精确: {bet.hit}/{bet.n} = {rate*100:.2f}%  95%CI [{lo*100:.2f}%, {hi*100:.2f}%]  {"✅超12%" if lo > 0.12 else "❌未超"}')
    print(f'方向: {bet.dir_hit}/{bet.n} = {bet.dir_hit/bet.n*100:.1f}%')
    if note: print(note)
    return {'name': name, 'bet_matches': bet.n, 'exact_hits': bet.hit,
            'exact_rate': round(rate, 4), 'ci95': [lo, hi],
            'direction_rate': round(bet.dir_hit/bet.n, 4) if bet.n else None,
            'note': note}

def main():
    rows = load()
    by_league = defaultdict(list)
    for r in rows: by_league[r['league']].append(r)
    for lg in by_league: by_league[lg].sort(key=lambda r: r['date'])
    dates = {lg: [r['date'] for r in lst] for lg, lst in by_league.items()}

    test = [r for r in rows if r['date'] >= PRED_START]
    all_test = len(test)

    ba, bb, bc = Bet(), Bet(), Bet()
    for r in test:
        lg = r['league']
        lst = by_league[lg]; ds = dates[lg]
        lo = bisect_left(ds, r['date'] - TRAIN_WIN)
        hi = bisect_left(ds, r['date'])
        scores = [x['score'] for x in lst[lo:hi]]
        n = len(scores)
        cnt = Counter(scores) if n else Counter()
        r11 = cnt['1:1'] / n if n else 0

        # 策略A: v8固定池猜1:1
        if lg in V8_POOL:
            ba.add(r, '1:1', f'v8池 1:1率{r11*100:.1f}%(n={n})')
        # 策略B: 滚动学习 >12%
        pick_b = None
        if n >= MIN_N:
            if r11 > 0.12:
                pick_b = ('1:1', f'1:1率{r11*100:.1f}%(n={n})')
            else:
                best = max(LOW_SCORES, key=lambda s: cnt[s])
                if cnt[best]/n > 0.12:
                    pick_b = (best, f'{best}率{cnt[best]/n*100:.1f}%(n={n})')
        if pick_b: bb.add(r, pick_b[0], pick_b[1])
        # 策略C: 滚动学习 >13%
        pick_c = None
        if n >= MIN_N:
            if r11 > 0.13:
                pick_c = ('1:1', f'1:1率{r11*100:.1f}%(n={n})')
            else:
                best = max(LOW_SCORES, key=lambda s: cnt[s])
                if cnt[best]/n > 0.13:
                    pick_c = (best, f'{best}率{cnt[best]/n*100:.1f}%(n={n})')
        if pick_c: bc.add(r, pick_c[0], pick_c[1])

    # 全场1:1背景
    all_11 = sum(1 for r in test if r['score'] == '1:1')
    print(f'预测期: {PRED_START.date()} ~ {test[-1]["date"].date()}  总场次: {all_test}')
    print(f'背景: 全场1:1率 {all_11/all_test*100:.2f}%  全场低比分率 {sum(1 for r in test if r["score"] in LOW_SCORES)/all_test*100:.1f}%')

    res = [
        summarize('A. v8固定池(英冠/意乙/波兰甲/瑞士超/澳超/瑞典超/巴西乙/英联杯/足总杯)猜1:1', ba, all_test),
        summarize('B. 滚动学习阈值>12%', bb, all_test),
        summarize('C. 滚动学习阈值>13%', bc, all_test),
    ]

    print('\n=== A策略逐联赛 ===')
    for lg, st in sorted(ba.per_league.items(), key=lambda x: -x[1]['n']):
        print(f'{lg:<10} n={st["n"]:>4} 率={st["hit"]/st["n"]*100:5.2f}%')

    out = {'period': [str(PRED_START.date()), str(test[-1]['date'].date())],
           'all_matches': all_test, 'background_1v1': round(all_11/all_test, 4),
           'strategies': res,
           'strategy_A_per_league': {lg: {'n': v['n'], 'hit': v['hit'], 'rate': round(v['hit']/v['n'], 4)}
                                     for lg, v in sorted(ba.per_league.items(), key=lambda x: -x[1]['n'])},
           'note': '历史CSV无赛前伤病/天气记录，赛前情报属情报缺口；本回测为无情报下限表现'}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n结果已存: {OUT}')

if __name__ == '__main__':
    main()
