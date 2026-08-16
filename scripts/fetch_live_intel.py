#!/usr/bin/env python3
"""活情报层：把"有血有肉"的场外变量从免费渠道算出来。

一个资深球迷看球，先看这几样（历史统计之外的东西）：
  1. 球队身份/档次 —— 谁打谁（豪门 vs 保级队 vs 升班马）
  2. 士气 —— 近5场胜/平/负轨迹（连败的队场上跑不动，士气是真实战力）
  3. 体能 —— 近7天赛程密度（双线作战/一周双赛，主力腿抬不起来）
  4. 教练 —— 临场指挥（摆大巴/打对攻），Sofascore event 端点有 manager 字段
  5. 天气 —— 已由 fetch_intel.py 的 Open-Meteo 覆盖

免费渠道全部验证：
  士气/体能 → 官方 CSV + Sofascore form（本地算，本脚本）
  教练 manager → Sofascore /api/v1/event/{id} 的 homeTeam.manager.name（浏览器抓）
  天气 → Open-Meteo（fetch_intel.py 已做）

用法：
  python3 fetch_live_intel.py 26085
  输出 live_intel_{期号}.json，含每场双方 士气轨迹/体能密度/教练(待浏览器补)

教训来源：26085期30场全死，根子就是我只看"近6场战绩"这个死数字，
没看士气(连败)、体能(赛程)、教练、球队身份这些"活"的东西。
"""
import csv, json, sys
from collections import defaultdict
from pathlib import Path

BASE = Path('/var/minis/shared/beidan_score')
CSV = BASE / 'data' / 'beidan_history_2021_2026.csv'


def load_history():
    rows = list(csv.DictReader(open(CSV, encoding='utf-8-sig')))
    rows.sort(key=lambda r: r['cutoff_time'])
    hist = defaultdict(list)  # team -> [(date, goals_for, goals_against)]
    for r in rows:
        try:
            gh, ga = int(r['ft_home']), int(r['ft_away'])
        except Exception:
            continue
        if gh < 0 or ga < 0:
            continue
        hist[r['home']].append((r['cutoff_time'][:10], gh, ga))
        hist[r['away']].append((r['cutoff_time'][:10], ga, gh))
    return hist


def morale(hist, team, n=5):
    """近n场胜/平/负轨迹，连败/连胜一目了然。"""
    seq = hist.get(team, [])[-n:]
    if len(seq) < 3:
        return {'轨迹': '样本不足', '胜': 0, '负': 0, '连败': 0, '连胜': 0}
    trail = ''.join('胜' if g > a else ('平' if g == a else '负') for _, g, a in seq)
    wins = sum(1 for _, g, a in seq if g > a)
    loses = sum(1 for _, g, a in seq if g < a)
    # 当前连败/连胜（从最近往前数）
    streak = 0
    for _, g, a in reversed(seq):
        if g < a:
            streak -= 1
        elif streak < 0:
            break
        else:
            streak = 0
    if streak == 0:  # 算连胜
        streak = 0
        for _, g, a in reversed(seq):
            if g > a:
                streak += 1
            else:
                break
    return {'轨迹': trail, '胜': wins, '负': loses, '连败' if streak < 0 else '连胜': abs(streak), 'streak': streak}


def density(sofa_form, days=7):
    """近days天踢了几场（体能负荷）。"""
    from datetime import datetime
    c = 0
    for e in (sofa_form or []):
        day = (e.get('date') or '')[:10]
        try:
            t = datetime.strptime(day, '%Y-%m-%d')
        except Exception:
            continue
        if t >= datetime(2026, 8, 15 - days):
            c += 1
    return c


def main():
    draw = sys.argv[1] if len(sys.argv) > 1 else '26085'
    intel = json.loads((BASE / 'intel' / f'intel_{draw}.json').read_text(encoding='utf-8'))
    sofa = json.loads((BASE / 'data' / 'sofa_145_full.json').read_text(encoding='utf-8'))['matches']
    sofa_by = {r['no']: r for r in sofa}
    hist = load_history()

    out = {'draw_no': draw, 'matches': []}
    for m in intel['matches']:
        no = m['no']
        r = sofa_by.get(no, {})
        h, a = m['home'], m['away']
        out['matches'].append({
            'no': no, 'league': m['league'], 'home': h, 'away': a,
            'home_morale': morale(hist, h), 'away_morale': morale(hist, a),
            'home_density7': density(r.get('form', {}).get('home', []), 7),
            'away_density7': density(r.get('form', {}).get('away', []), 7),
            'home_manager': None,  # 待浏览器从 /api/v1/event/{id} 补
            'away_manager': None,
        })

    dest = BASE / 'intel' / f'live_intel_{draw}.json'
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ 活情报已生成 {dest}（{len(out["matches"])}场，士气+体能已算，教练待浏览器补）')
    # 打印样例
    for x in out['matches'][:10]:
        hm = x['home_morale']; am = x['away_morale']
        print(f"[{x['no']:>3}] {x['home']}({hm['轨迹']},{hm.get('连败') or hm.get('连胜')}) vs "
              f"{x['away']}({am['轨迹']},{am.get('连败') or am.get('连胜')}) "
              f"体能{x['home_density7']}:{x['away_density7']}")


if __name__ == '__main__':
    main()
