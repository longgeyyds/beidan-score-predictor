#!/usr/bin/env python3
"""v11：纯递推计算模型 —— 不看任何比率/众数/频率。

用户要求（2026-08-11）：不固定猜1:1，不允许看比率大小，按实际情况实际计算、实际预测。

本模型完全不用历史频率：
- 不用"1:1率"、不用众数、不用Top1、不用基线
- 每队维护攻击/防守状态，用指数平滑递推公式从实际比赛结果更新
- 主客场状态分开维护
- 联赛进球水平是实际数据（滚动场均），不是比率
- 本场期望进球 = 双方状态 × 联赛实际水平（纯计算）
- 比分 = 期望进球直接映射（确定性，非抽样）

选场只要求：跨年池内（池子只决定看不看这场）+ 双方状态数据完整。
比分完全由公式计算。
"""
import csv, json, math, re
from collections import defaultdict, deque
from datetime import datetime, timedelta
from bisect import bisect_left

CSV = Path = __import__('pathlib').Path('data/beidan_history_2021_2026.csv')
OUT = __import__('pathlib').Path('backtest_v11_compute.json')
TEST_START = datetime(2026, 2, 11)
ALPHA = 0.5          # 递推平滑系数：新信息权重
MIN_MATCHES = 5      # 状态至少需要的场次

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

def main():
    rows = load()

    # ===== 状态存储（递推公式的变量） =====
    # 每队: att_home/att_away = 进攻状态, def_home/def_away = 防守状态
    # 状态初始1.0（=联赛平均水平），随实际比赛递推更新
    state = defaultdict(lambda: {'att_h': 1.0, 'att_a': 1.0, 'def_h': 1.0, 'def_a': 1.0,
                                 'n_h': 0, 'n_a': 0})
    # 联赛进球水平（滚动窗口的实际数据）
    league_goals = defaultdict(lambda: deque(maxlen=200))

    def update_state(team, side, gf, ga, lg_avg):
        """递推公式：新状态 = α×本场表现 + (1-α)×旧状态
        本场表现相对联赛平均标准化：gf/lg_avg（攻），ga/lg_avg（防）"""
        st = state[team]
        if side == 'home':
            st['att_h'] = ALPHA * (gf / lg_avg) + (1 - ALPHA) * st['att_h']
            st['def_h'] = ALPHA * (ga / lg_avg) + (1 - ALPHA) * st['def_h']
            st['n_h'] += 1
        else:
            st['att_a'] = ALPHA * (gf / lg_avg) + (1 - ALPHA) * st['att_a']
            st['def_a'] = ALPHA * (ga / lg_avg) + (1 - ALPHA) * st['def_a']
            st['n_a'] += 1

    test = [r for r in rows if r['date'] >= TEST_START]
    all_test = len(test)

    n = hit = dir_hit = skipped = 0
    bets = []
    for r in rows:
        lg = r['league']
        lg_avg = sum(league_goals[lg]) / len(league_goals[lg]) if league_goals[lg] else 2.7
        if lg_avg <= 0: lg_avg = 2.7
        lg_avg_single = lg_avg / 2  # 单队场均进球（联赛总进球的一半）

        if r['date'] >= TEST_START:
            # ===== 预测（只用此前状态） =====
            hst = state[r['home']]; ast = state[r['away']]
            if hst['n_h'] < MIN_MATCHES or ast['n_a'] < MIN_MATCHES:
                skipped += 1
            else:
                # 本场期望进球（纯计算）：
                # 主队期望 = 联赛实际场均 × 主队主场攻击状态 × 客队客场防守状态
                # 客队期望 = 联赛实际场均 × 客队客场攻击状态 × 主队主场防守状态
                h_exp = lg_avg_single * hst['att_h'] * ast['def_a']
                a_exp = lg_avg_single * ast['att_a'] * hst['def_h']
                # 比分 = 期望值映射（就近取整，确定性）
                gh = max(0, min(6, round(h_exp)))
                ga = max(0, min(6, round(a_exp)))
                pick = f'{gh}:{ga}'

                n += 1
                is_hit = pick == r['score']
                hit += is_hit
                ph = 'H' if gh > ga else ('D' if gh == ga else 'A')
                rh, ra = r['hg'], r['ag']
                ract = 'H' if rh > ra else ('D' if rh == ra else 'A')
                if ph == ract: dir_hit += 1
                bets.append({'date': str(r['date'])[:10], 'league': lg,
                             'home': r['home'], 'away': r['away'],
                             'pick': pick, 'actual': r['score'], 'hit': is_hit,
                             'h_exp': round(h_exp, 2), 'a_exp': round(a_exp, 2)})
        # ===== 更新状态（递推，本场结果成为下一场的先验） =====
        update_state(r['home'], 'home', r['hg'], r['ag'], lg_avg_single)
        update_state(r['away'], 'away', r['ag'], r['hg'], lg_avg_single)
        league_goals[lg].append(r['hg'] + r['ag'])

    rate = hit / n if n else 0
    print(f'=== v11 纯递推计算模型（不看比率/众数/频率） ===')
    print(f'预测期: {TEST_START.date()} ~ {test[-1]["date"].date()}  总场次: {all_test}')
    print(f'预测场次: {n}  跳过(状态不足): {skipped}')
    print(f'精确命中: {hit}/{n} = {rate*100:.2f}%')
    print(f'方向命中: {dir_hit}/{n} = {dir_hit/n*100:.1f}%')
    print(f'（参照：同期全场1:1=11.89%，统计池无脑1:1=13.25%——仅为对比参考，本模型不用它们生成比分）')

    # 预测比分分布
    from collections import Counter
    pc = Counter(b['pick'] for b in bets)
    print(f'\n=== 计算出的比分分布 ===')
    for s, c in pc.most_common(10):
        print(f'  {s}: {c} ({c/n*100:.1f}%)')

    out = {
        'method': 'v11 纯递推计算：指数平滑状态(α=0.5,主客分离) × 联赛实际场均 → 期望进球 → 就近取整',
        'period': [str(TEST_START.date()), str(test[-1]['date'].date())],
        'all_matches': all_test, 'predicted': n, 'skipped': skipped,
        'exact_hits': hit, 'exact_rate': round(rate, 4),
        'direction_hits': dir_hit, 'direction_rate': round(dir_hit/n, 4) if n else None,
        'ref_1v1_all': 0.1189, 'ref_stat_pool': 0.1325,
        'pick_dist': {s: c for s, c in pc.most_common()},
        'sample': bets[:30]
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n结果已存: {OUT}')

if __name__ == '__main__':
    main()
