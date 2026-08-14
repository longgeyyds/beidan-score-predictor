#!/usr/bin/env python3
"""过程数据画像：用"射门质量"替代"历史比分频率"推导期望进球。

背景（2026-08-14 死磕比分，换更强的输入）：
之前 v3-v11 全部用"历史比分频率"猜比分——那是"结果"，天花板12%。
体育数据分析的共识：预测进球该用"过程"——射门量、射正率、重大机会（xG的简化代理）、
重大机会转化率。这些是 Sofascore 免费 API 能拿到的（真 xG 免费层锁了）。

数据结构（由 browser_use 抓取后存 JSON）：
process_data.json = {
  "贝西克塔斯": {
     "season": {"shots": 502, "shotsOnTarget": 176, "bigChances": 107,
                "bigChancesCreated": 80, "bigChancesMissed": 62,
                "goalsScored": 59, "goalsConceded": 36, "matches": 38},
     "recent": [  # 最近5场逐场
        {"home": "贝西克塔斯", "away": "科尼亚", "shotsOnTarget_h": 4, "shotsOnTarget_a": 1, ...}
     ]
  }
}

本脚本：读 process_data.json → 算每队"进攻质量/防守质量" → 双方对位 → 期望进球。
"""
import json, sys
from pathlib import Path

DATA = Path('process_data.json')


def load():
    if not DATA.exists():
        return {}
    return json.loads(DATA.read_text(encoding='utf-8'))


def attack_quality(team):
    """进攻质量：射正率 + 重大机会创造 + 转化。返回 0~2 倍于平均的系数。"""
    d = team.get('season', {})
    shots = d.get('shots', 0)
    sot = d.get('shotsOnTarget', 0)
    big = d.get('bigChancesCreated', d.get('bigChances', 0))
    goals = d.get('goalsScored', 0)
    matches = d.get('matches', 1) or 1
    if shots <= 0 or matches <= 0:
        return None
    # 每场射门量、射正率、重大机会转化率
    shots_per = shots / matches
    sot_rate = sot / shots if shots else 0
    # 重大机会转化 = 进球数 / 重大机会创造（把握力）
    big_conv = goals / big if big else None
    return {
        'shots_per_game': round(shots_per, 1),
        'sot_rate': round(sot_rate, 3),
        'big_chances_per_game': round(big / matches, 2),
        'big_conv': round(big_conv, 3) if big_conv is not None else None,
        'goals_per_game': round(goals / matches, 2),
    }


def defense_quality(team):
    """防守质量：被射正数 + 被创造重大机会数（Against 系列，比失球数更反映防守真实水平）。"""
    d = team.get('season', {})
    matches = d.get('matches', 1) or 1
    if matches <= 0:
        return None
    return {
        'conceded_per_game': round(d.get('goalsConceded', 0) / matches, 2),
        'shots_on_target_against': round(d.get('shotsOnTargetAgainst', 0) / matches, 2),
        'big_chances_against': round(d.get('bigChancesAgainst', 0) / matches, 2),
    }


def expected_goals(home, away):
    """对位推导期望进球。

    思路（简化版 xG，用可得的代理字段）：
    主队期望 = 中性基准 × 主队进攻系数 × 客队防守系数
    - 进攻系数 = 重大机会创造/场 相对中性(1.2/场) + 射正率
    - 防守系数 = 被创造重大机会/场 相对中性(1.2/场) + 被射正
    中性基准取 1.35 球/队（历史单队场均约 1.3-1.4）。
    """
    ha = attack_quality(home)
    aa = attack_quality(away)
    hd = defense_quality(home)
    ad = defense_quality(away)
    if not (ha and aa and hd and ad):
        return None
    BASE = 1.35          # 中性基准单队进球
    NEUTRAL_BIG = 1.2    # 中性"重大机会创造/场"
    NEUTRAL_SOT = 0.35   # 中性射正率

    def att_coef(q):
        # 进攻系数：重大机会创造/场 为主（权重0.7），射正率为辅（权重0.3）
        c = 1.0
        big_c = q['big_chances_per_game']
        c *= (big_c / NEUTRAL_BIG) ** 0.7 if big_c > 0 else 1.0
        if q['sot_rate']:
            c *= (q['sot_rate'] / NEUTRAL_SOT) ** 0.3
        return c

    def def_coef(q):
        # 防守系数：被创造重大机会/场 为主，被射正为辅
        c = 1.0
        ba = q['big_chances_against']
        c *= (ba / NEUTRAL_BIG) ** 0.7 if ba > 0 else 1.0
        sa = q['shots_on_target_against']
        c *= (sa / (NEUTRAL_SOT * 4)) ** 0.3 if sa > 0 else 1.0
        return c

    h_exp = BASE * att_coef(ha) * def_coef(ad)
    a_exp = BASE * att_coef(aa) * def_coef(hd)
    return {'home_xg': round(h_exp, 2), 'away_xg': round(a_exp, 2)}


def main():
    data = load()
    if not data:
        print('process_data.json 不存在或为空。先用 browser_use 抓取并存盘。')
        sys.exit(1)
    teams = [t for t in data if not t.startswith('_')]
    print(f'=== 过程数据画像（{len(teams)} 队）===')
    for t in teams:
        aq = attack_quality(data[t])
        dq = defense_quality(data[t])
        if aq and dq:
            print(f'{t}: 射门{aq["shots_per_game"]}/场 射正率{aq["sot_rate"]*100:.0f}% '
                  f'重大机会{aq["big_chances_per_game"]}/场 转化{aq["big_conv"] if aq["big_conv"] is not None else "?"} '
                  f'进球{aq["goals_per_game"]}/场 失球{dq["conceded_per_game"]}/场')
    # 若指定双方，输出对位期望
    if len(sys.argv) >= 3:
        home, away = sys.argv[1], sys.argv[2]
        if home in data and away in data:
            eg = expected_goals(data[home], data[away])
            if eg:
                print(f'\n对位 {home} vs {away}: 期望 {eg["home_xg"]}:{eg["away_xg"]}')
                # 期望进球 → 精确比分候选（死磕比分，不是大小球）
                h = round(eg['home_xg']); a = round(eg['away_xg'])
                print(f'  → 精确比分候选: {h}:{a}')
                # 附第二候选（四舍五入的另一方向）
                h2 = int(eg['home_xg']); a2 = int(eg['away_xg'])
                if (h, a) != (h2, a2):
                    print(f'    第二候选: {h2}:{a2}')


if __name__ == '__main__':
    main()
