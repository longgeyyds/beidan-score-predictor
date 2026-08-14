#!/usr/bin/env python3
"""过程数据转存器：把 browser_use 抓取的 Sofascore 赛季统计，规范化后并入 process_data.json。

抓取流程（browser_use 的 execute_js，Sofascore 反爬 curl 直连 403）：
1. 搜队拿 ID：/api/v1/search/all?q=队名 → team.id
2. 拿当前赛事 season：/api/v1/team/{id}/events/next/0 → event.season.id + tournament.uniqueTournament.id
3. 拿赛季统计：/api/v1/team/{id}/unique-tournament/{ut}/season/{sid}/statistics/overall
   → statistics 字段里含 matches/shots/shotsOnTarget/bigChances/bigChancesCreated/
     bigChancesMissed/goalsScored/goalsConceded/shotsOnTargetAgainst/bigChancesAgainst 等
4. 把原始 JSON（格式 {队名: {"season": {...}}}）喂给本脚本转存

用法：
  python3 save_process_data.py <原始JSON路径>                  # 旧格式 {队名: {"season": {...}}}
  python3 save_process_data.py --from-sofa <sofa期号>          # 新格式 sofa_{期号}.json（fetch_sofa_batch 产物）
原始JSON格式示例见 process_data.json。
"""
import json, sys
from pathlib import Path

DATA = Path('process_data.json')

# 需要保留的赛季字段（进攻 + 防守 Against）
KEEP_KEYS = [
    'matches', 'goalsScored', 'goalsConceded',
    'shots', 'shotsOnTarget', 'bigChances', 'bigChancesCreated', 'bigChancesMissed',
    'shotsAgainst', 'shotsOnTargetAgainst', 'bigChancesAgainst', 'bigChancesMissedAgainst',
    'cleanSheets',
]


def normalize(team_data):
    """从原始 season 数据抽取 KEEP_KEYS，缺失补 0。"""
    season = team_data.get('season', {})
    out = {}
    for k in KEEP_KEYS:
        v = season.get(k, 0)
        out[k] = int(v) if isinstance(v, (int, float)) else 0
    return {'season': out}


def import_from_sofa(draw):
    """从 fetch_sofa_batch 的 sofa_{期号}.json 批量导入双方赛季统计。"""
    src = Path('data') / f'sofa_{draw}.json'
    if not src.exists():
        sys.exit(f'{src} 不存在，先跑 fetch_sofa_batch.py merge {draw}')
    data = json.loads(src.read_text(encoding='utf-8'))['matches']
    raw = {}
    n_stats = 0
    for r in data:
        for side in ('home', 'away'):
            st = (r.get('stats') or {}).get(side)
            if st:
                raw[r[side]] = {'season': st}
                n_stats += 1
    if not raw:
        sys.exit('❌ sofa 数据里没有任何赛季统计，检查 fetch_sofa_batch merge 的 stats 覆盖')
    existing = {}
    if DATA.exists():
        existing = json.loads(DATA.read_text(encoding='utf-8'))
    existing = {k: v for k, v in existing.items() if not k.startswith('_')}
    existing.update({t: normalize(d) for t, d in raw.items()})
    out = {'_comment': '过程数据画像（Sofascore 赛季统计，browser_use 抓取）。含进攻和防守(Against)两端。',
           '_sources': existing.get('_sources', []) + [f'sofa_{draw}.json'],
           **{k: v for k, v in existing.items() if not k.startswith('_')}}
    DATA.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ 从 {src.name} 导入 {len(raw)} 条统计（{n_stats} 队次），process_data.json 现有 {len(out)-1} 队')


def main():
    args = sys.argv[1:]
    if args and args[0] == '--from-sofa':
        if len(args) < 2:
            sys.exit('用法: save_process_data.py --from-sofa <期号>')
        return import_from_sofa(args[1])
    src_path = args[0] if args else None
    if not src_path or not Path(src_path).exists():
        print('用法: python3 save_process_data.py <原始JSON路径>  或  --from-sofa <期号>')
        sys.exit(1)
    raw = json.loads(Path(src_path).read_text(encoding='utf-8'))

    # 读现有数据（保留已存的队）
    existing = {}
    if DATA.exists():
        existing = json.loads(DATA.read_text(encoding='utf-8'))
    existing = {k: v for k, v in existing.items() if not k.startswith('_')}

    # 并入新数据
    for team, team_data in raw.items():
        if team.startswith('_'):
            continue
        existing[team] = normalize(team_data)

    out = {'_comment': '过程数据画像（Sofascore 赛季统计，browser_use 抓取）。含进攻和防守(Against)两端。',
           **existing}
    DATA.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'已转存 {len(existing)} 队到 {DATA}')


if __name__ == '__main__':
    main()
