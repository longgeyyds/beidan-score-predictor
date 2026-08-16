#!/usr/bin/env python3
"""活情报层 v2：把"有血有肉"的场外变量从免费渠道算出来。

一个资深球迷看球，先看这几样（历史统计之外的东西）：
  1. 球队身份/档次 —— 谁打谁（豪门 vs 保级队 vs 升班马）
  2. 士气 —— 近5场胜/平/负轨迹（连败的队场上跑不动）
  3. 体能 —— 近7天赛程密度（双线作战/一周双赛）
  4. 教练 —— 临场指挥（摆大巴/打对攻）
  5. 天气 —— Open-Meteo

2026-08-16 新增（资深球迷增量维度，数据已在 sofa stats/streaks 里，之前没读）：
  6. 战术风格对位 —— 控球/防反/突破/封堵/长传/对抗/犯规
  7. 定位球 —— 任意球/点球/角球/头球/传中（约30%进球来源）
  8. 纪律/红牌风险 —— 黄牌/红牌/犯规/送点
  9. 门将状态 —— 扑救/阻止进球/失误致丢球
  10. xG —— expectedGoals / expectedGoalsOnTarget
  11. 开场节奏 —— streaks: 先进球/上半场胜负/大小球倾向/牌数
  12. 旅行距离 —— 客队主场→本场球场直线距离（venue_cache + event.venue 坐标）

用法：
  python3 fetch_live_intel.py 26085
  输出 live_intel_{期号}.json，含每场双方 士气/体能/风格/定位球/纪律/门将/xG/节奏/旅行距离
"""
import csv, json, sys
from collections import defaultdict
from math import radians, sin, cos, asin, sqrt
from pathlib import Path

BASE = Path('/var/minis/shared/beidan_score')
CSV = BASE / 'data' / 'beidan_history_2021_2026.csv'
SOFA = BASE / 'data' / 'sofa_145_full.json'
VENUE_CACHE = BASE / 'venue_cache.json'


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
    streak = 0
    for _, g, a in reversed(seq):
        if g < a:
            streak -= 1
        elif streak < 0:
            break
        else:
            streak = 0
    if streak == 0:
        for _, g, a in reversed(seq):
            if g > a:
                streak += 1
            else:
                break
    key = '连败' if streak < 0 else '连胜'
    return {'轨迹': trail, '胜': wins, '负': loses, key: abs(streak), 'streak': streak}


def density(sofa_form, days=7, ref_date='2026-08-15'):
    """近days天踢了几场（体能负荷）。"""
    from datetime import datetime
    try:
        ref = datetime.strptime(ref_date, '%Y-%m-%d')
    except Exception:
        ref = datetime(2026, 8, 15)
    c = 0
    for e in (sofa_form or []):
        day = (e.get('date') or '')[:10]
        try:
            t = datetime.strptime(day, '%Y-%m-%d')
        except Exception:
            continue
        if t >= datetime(ref.year, ref.month, ref.day - days):
            c += 1
    return c


# —— 2026-08-16 新增：stats/streaks 增量维度 ——

# stats 字段 → 中文标签（战术风格/定位球/纪律/门将/xG 五类）
STYLE_KEYS = [
    ('averageBallPossession', '控球率%'),
    ('fastBreaks', '防反次数'),
    ('fastBreakGoals', '防反进球'),
    ('successfulDribbles', '成功过人'),
    ('blockedScoringAttempt', '封堵射门'),
    ('accurateLongBalls', '成功长传'),
    ('totalLongBalls', '长传总数'),
    ('aerialDuelsWon', '空中对抗赢'),
    ('totalAerialDuels', '空中对抗总'),
    ('duelsWon', '对抗赢'),
    ('totalDuels', '对抗总'),
    ('fouls', '犯规'),
]
SETPIECE_KEYS = [
    ('freeKickGoals', '任意球进球'),
    ('freeKickShots', '任意球射门'),
    ('penaltyGoals', '点球进球'),
    ('penaltiesTaken', '获点球'),
    ('penaltyGoalsConceded', '被判点球'),
    ('corners', '角球'),
    ('headedGoals', '头球进球'),
    ('accurateCrosses', '成功传中'),
    ('totalCrosses', '传中总'),
]
DISCIPLINE_KEYS = [
    ('yellowCards', '黄牌'),
    ('redCards', '红牌'),
    ('yellowRedCards', '两黄变红'),
    ('penaltiesCommited', '送点'),
]
KEEPER_KEYS = [
    ('saves', '扑救'),
    ('goalsPrevented', '阻止进球'),
    ('errorsLeadingToGoal', '失误致丢球'),
    ('cleanSheets', '零封'),
]
XG_KEYS = [
    ('expectedGoals', 'xG'),
    ('expectedGoalsOnTarget', 'xG射正'),
]

RHYTHM_NAMES = [
    'First to score', 'First to concede', 'First half winner', 'First half loser',
    'Both teams scoring', 'Less than 2.5 goals', 'More than 2.5 goals',
    'More than 4.5 cards', 'Less than 4.5 cards',
    'Wins', 'Losses', 'No wins', 'No losses',
    'No goals conceded', 'No goals scored', 'Without clean sheet',
]


def pick_stats(stats_side, keymap):
    """从单侧 stats 提取指定字段，只保留有值的。"""
    out = {}
    if not stats_side:
        return out
    for k, label in keymap:
        if k in stats_side and stats_side[k] is not None:
            out[label] = stats_side[k]
    return out


def pick_rhythm(streaks, side):
    """从 streaks 提取该侧的开场节奏信号。"""
    out = {}
    st = streaks or {}
    for s in (st.get('general') or []) or []:
        if s.get('team') not in (side, 'both'):
            continue
        name = s.get('name')
        if name in RHYTHM_NAMES:
            out[name] = s.get('value')
    return out


def travel_distance_km(venue_cache, away_name, event):
    """客队主场 → 本场球场直线距离（km）。"""
    from_coord = venue_cache.get(away_name)
    vc = (event or {}).get('venue') or {}
    to_coord = vc.get('venueCoordinates') or {}
    if not from_coord or not to_coord:
        return None
    lat1, lon1 = from_coord['lat'], from_coord['lon']
    lat2, lon2 = to_coord['latitude'], to_coord['longitude']
    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return round(2 * r * asin(sqrt(a)), 0)


def main():
    draw = sys.argv[1] if len(sys.argv) > 1 else '26085'
    intel = json.loads((BASE / 'intel' / f'intel_{draw}.json').read_text(encoding='utf-8'))
    sofa = json.loads(SOFA.read_text(encoding='utf-8'))['matches']
    sofa_by = {r['no']: r for r in sofa}
    venue_cache = json.loads(VENUE_CACHE.read_text(encoding='utf-8'))
    hist = load_history()

    out = {'draw_no': draw, 'matches': []}
    for m in intel['matches']:
        no = m['no']
        r = sofa_by.get(no, {})
        h, a = m['home'], m['away']
        stats = r.get('stats') or {}
        streaks = r.get('streaks') or {}
        event = r.get('event') or {}
        form = r.get('form') or {}

        out['matches'].append({
            'no': no, 'league': m['league'], 'home': h, 'away': a,
            # 士气 + 体能
            'home_morale': morale(hist, h), 'away_morale': morale(hist, a),
            'home_density7': density(form.get('home', []), 7),
            'away_density7': density(form.get('away', []), 7),
            # 2026-08-16 增量维度
            'home_style': pick_stats(stats.get('home'), STYLE_KEYS),
            'away_style': pick_stats(stats.get('away'), STYLE_KEYS),
            'home_setpiece': pick_stats(stats.get('home'), SETPIECE_KEYS),
            'away_setpiece': pick_stats(stats.get('away'), SETPIECE_KEYS),
            'home_discipline': pick_stats(stats.get('home'), DISCIPLINE_KEYS),
            'away_discipline': pick_stats(stats.get('away'), DISCIPLINE_KEYS),
            'home_keeper': pick_stats(stats.get('home'), KEEPER_KEYS),
            'away_keeper': pick_stats(stats.get('away'), KEEPER_KEYS),
            'home_xg': pick_stats(stats.get('home'), XG_KEYS),
            'away_xg': pick_stats(stats.get('away'), XG_KEYS),
            'home_rhythm': pick_rhythm(streaks, 'home'),
            'away_rhythm': pick_rhythm(streaks, 'away'),
            'travel_km': travel_distance_km(venue_cache, a, event),
            'home_manager': None,  # 待浏览器从 /api/v1/event/{id} 补
            'away_manager': None,
        })

    dest = BASE / 'intel' / f'live_intel_{draw}.json'
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ 活情报已生成 {dest}（{len(out["matches"])}场，士气/体能/风格/定位球/纪律/门将/xG/节奏/旅行距离）')
    # 打印样例（前8场，展示新增维度）
    for x in out['matches'][:8]:
        hm = x['home_morale']; am = x['away_morale']
        print(f"\n[{x['no']:>3}] {x['home']}({hm['轨迹']}) vs {x['away']}({am['轨迹']}) 体能{x['home_density7']}:{x['away_density7']} 客旅{x['travel_km']}km")
        print(f"    主风格: {x['home_style']}")
        print(f"    客风格: {x['away_style']}")
        if x['home_xg']:
            print(f"    xG 主{x['home_xg']} 客{x['away_xg']}")


if __name__ == '__main__':
    main()
