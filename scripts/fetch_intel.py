#!/usr/bin/env python3
"""自动化情报收集脚本：修复漏洞#5（手写记录遗漏）。

把"能自动化的情报"全部自动化，输出结构化 JSON，杜绝手写 markdown 遗漏。
伤病/缺阵/球场坐标需 browser_use（Sofascore 反爬），本脚本生成待查清单，照单执行。

自动收集（本地/官方/天气，无需 browser_use）：
1. 官方 XML → 赛程 + 即时 SP（全部25项）
2. 本地 CSV → 双方近期状态、首回合、首回合后中间比赛
3. Open-Meteo → 开球时刻天气（需球场坐标，坐标来自缓存或 browser_use）

输出：intel/intel_{期号}.json
"""
import csv, json, re, sys, urllib.request, xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE = 'https://www.bjlot.com.cn'
CSV = Path('data/beidan_history_2021_2026.csv')
OUTDIR = Path('intel')
UA = 'Mozilla/5.0 (compatible; BeidanIntel/1.0)'

# 球场坐标缓存（已查过的队，避免重复 browser_use）
VENUE_CACHE = {
    '巴黎圣日耳曼': (48.841363, 2.253069, 'Europe/Paris'),
    '阿斯顿维拉': (52.509, -1.885, 'Europe/London'),
    '博卡青年': (-34.61315, -58.37723, 'America/Argentina/Buenos_Aires'),
    '玻利瓦尔': (-16.49945, -68.122853, 'America/La_Paz'),
    '北西兰': (55.82, 12.32, 'Europe/Copenhagen'),
    # 其余待 browser_use 查
}

SCORES = ['1:0','2:0','2:1','3:0','3:1','3:2','4:0','4:1','4:2','胜其它',
          '0:0','1:1','2:2','3:3','平其它','0:1','0:2','1:2','0:3','1:3','2:3',
          '0:4','1:4','2:4','负其它']


def txt(el, tag):
    q = el.find(tag)
    return q.text if q is not None and q.text else ''


def norm_league(s):
    s = re.sub(r'^(?:20)?\d{2}[-/]\d{2}', '', (s or '').strip())
    s = re.sub(r'^20\d{2}', '', s)
    s = re.sub(r'^\d{2}(?=[\u4e00-\u9fffA-Za-z])', '', s)
    return s or '未知赛事'


def fetch_xml(draw_no):
    url = f'{BASE}/data/250ParlayGetGame_{draw_no}.xml?ts={int(datetime.now().timestamp())}'
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': BASE + '/'})
    return urllib.request.urlopen(req, timeout=30).read()


def get_schedule(draw_no):
    """官方XML → 在售场次 + SP"""
    b = fetch_xml(draw_no)
    root = ET.fromstring(b.decode('utf-8-sig', 'replace'))
    matches = []
    for it in root.findall('.//matchInfo/matchelem/item'):
        no = txt(it, 'no') or it.get('no', '')
        if txt(it, 'matchandstate') != '销售中':
            continue
        sps = {}
        for ch in it.findall('.//spitem/*'):
            if ch.tag.startswith('sp') and ch.tag[2:].isdigit():
                v = ch.text
                if v and float(v) > 0:
                    sps[int(ch.tag[2:])] = float(v)
        matches.append({
            'no': no, 'league': txt(it, 'leagueName'),
            'home': txt(it, 'hostFull') or txt(it, 'host'),
            'away': txt(it, 'guestFull') or txt(it, 'guest'),
            'kickoff': txt(it, 'endTime'),
            'sp': {SCORES[i-1]: sps[i] for i in sorted(sps) if i <= 25},
        })
    return matches


def load_history():
    rows = []
    with CSV.open(encoding='utf-8-sig', newline='') as f:
        for x in csv.DictReader(f):
            try:
                dt = datetime.fromisoformat(x['cutoff_time'].replace(' ', 'T'))
                h = int(x['ft_home']); a = int(x['ft_away'])
            except Exception:
                continue
            if h < 0 or a < 0: continue
            rows.append({'date': dt, 'league': norm_league(x['league']),
                         'home': x['home'], 'away': x['away'],
                         'hg': h, 'ag': a, 'score': f'{h}:{a}'})
    rows.sort(key=lambda r: r['date'])
    return rows


def team_form(rows, team, limit=6):
    lst = []
    for r in rows:
        if r['home'] == team:
            lst.append((r['date'].strftime('%y-%m-%d'), '主', r['hg'], r['ag'], r['score'], r['league']))
        elif r['away'] == team:
            lst.append((r['date'].strftime('%y-%m-%d'), '客', r['ag'], r['hg'], r['score'], r['league']))
    lst.sort(reverse=True)
    return lst[:limit]


def h2h_and_mid(rows, home, away, kickoff_str):
    """首回合 + 首回合后中间比赛（资格赛两回合关键维度）

    首回合 = 两队最近一次交锋（8/6-8/7那批）
    中间比赛 = 首回合之后、本场之前，各队又打的联赛/杯赛，判断体能+状态拐点
    """
    h2h = []
    for r in rows:
        if (r['home'] == home and r['away'] == away) or (r['home'] == away and r['away'] == home):
            h2h.append((r['date'], f"{r['date'].strftime('%y-%m-%d')} {r['home']} {r['score']} {r['away']}"))
    h2h.sort()
    mid = {'home': [], 'away': []}
    if h2h:
        first_leg = h2h[-1][0]  # 最近一次交锋 = 首回合日期
        ko = datetime.strptime(kickoff_str, '%Y-%m-%d %H:%M:%S')
        for r in rows:
            if first_leg < r['date'] < ko:
                if r['home'] == home or r['away'] == home:
                    mid['home'].append(f"{r['date'].strftime('%y-%m-%d')} {r['home']} {r['score']} {r['away']}")
                if r['home'] == away or r['away'] == away:
                    mid['away'].append(f"{r['date'].strftime('%y-%m-%d')} {r['home']} {r['score']} {r['away']}")
    return {'h2h': [x[1] for x in h2h], 'mid': mid}


def weather(lat, lon, utc_kickoff_hour):
    """Open-Meteo 默认返回 UTC 整点。utc_kickoff_hour 形如 '2026-08-13T16:00'。
    开球时刻向下取整到整点（19:25开球 → 查19:00，即开球时进行中的那个小时）。"""
    url = f'https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation,wind_speed_10m'
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    d = json.loads(urllib.request.urlopen(req, timeout=10).read())
    times = d['hourly']['time']
    for i, t in enumerate(times):
        if t == utc_kickoff_hour:
            return {'time': t, 'temp': d['hourly']['temperature_2m'][i],
                    'precip': d['hourly']['precipitation'][i],
                    'wind': d['hourly']['wind_speed_10m'][i]}
    return None


def main():
    draw_no = sys.argv[1] if len(sys.argv) > 1 else '26084'
    OUTDIR.mkdir(parents=True, exist_ok=True)
    matches = get_schedule(draw_no)
    rows = load_history()

    result = {'draw_no': draw_no, 'generated': datetime.now().isoformat(),
              'matches': [], 'todo_injuries': []}
    for m in matches:
        home, away = m['home'], m['away']
        entry = dict(m)
        entry['home_form'] = team_form(rows, home)
        entry['away_form'] = team_form(rows, away)
        h2h_mid = h2h_and_mid(rows, home, away, m['kickoff'])
        entry['h2h'] = h2h_mid['h2h']
        entry['mid'] = h2h_mid['mid']
        # 天气：北京时间 → UTC → 取整点匹配（坐标缺失则留空进待查清单）
        if home in VENUE_CACHE:
            lat, lon, _tz = VENUE_CACHE[home]
            ko = datetime.strptime(m['kickoff'], '%Y-%m-%d %H:%M:%S')
            utc_ko = (ko - timedelta(hours=8)).replace(minute=0, second=0, microsecond=0)
            entry['weather'] = weather(lat, lon, utc_ko.strftime('%Y-%m-%dT%H:%M'))
        else:
            entry['weather'] = None
        result['matches'].append(entry)
        # 待 browser_use 查伤病的队
        result['todo_injuries'].append({'home': home, 'away': away})

    out = OUTDIR / f'intel_{draw_no}.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'draw_no': draw_no, 'matches': len(matches),
                      'todo_injuries': len(result['todo_injuries']),
                      'out': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
