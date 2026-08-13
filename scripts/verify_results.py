#!/usr/bin/env python3
"""复盘前数据校验：官方XML最新赛果 vs 本地CSV，不一致则报警。

修复漏洞#1：update_history.py 抓的 raw XML 可能是赛果未定稿版（南美场次开球晚，
早期 XML 的 soccer 字段可能为空或未更新），导致本地 CSV 与官方最终赛果不一致。
本脚本在复盘前强制用官方最新 XML 复核，发现不一致立即报警并提示修正。
"""
import csv, re, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime

BASE = 'https://www.bjlot.com.cn'
CSV = 'data/beidan_history_2021_2026.csv'
UA = 'Mozilla/5.0 (compatible; BeidanVerify/1.0)'


def txt(el, tag):
    q = el.find(tag)
    return q.text if q is not None and q.text else ''


def pair(s):
    m = re.fullmatch(r'(\d+):(\d+)', s or '')
    return (m.group(1), m.group(2)) if m else ('', '')


def fetch_xml(draw_no):
    url = f'{BASE}/data/250ParlayGetGame_{draw_no}.xml?ts={int(datetime.now().timestamp())}'
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': BASE + '/'})
    return urllib.request.urlopen(req, timeout=30).read()


def verify(draw_no):
    """返回 (official_dict, mismatch_list)"""
    b = fetch_xml(draw_no)
    root = ET.fromstring(b.decode('utf-8-sig', 'replace'))
    official = {}
    for it in root.findall('.//matchInfo/matchelem/item'):
        no = txt(it, 'no') or it.get('no', '')
        fh, fa = pair(txt(it, 'soccer'))
        if no and fh:  # 官方已有赛果
            official[no] = (fh, fa)
    csv_rows = {}
    with open(CSV, encoding='utf-8-sig', newline='') as f:
        for x in csv.DictReader(f):
            if x['draw_no'] == draw_no:
                csv_rows[x['match_no']] = (x['ft_home'], x['ft_away'])
    mismatches = []
    for no, (fh, fa) in sorted(official.items(), key=lambda x: int(x[0])):
        if no in csv_rows and csv_rows[no] != (fh, fa):
            mismatches.append((no, csv_rows[no], (fh, fa)))
    return official, mismatches


def main():
    # 默认校验最近已开奖的期号（26084 是当前期）
    targets = sys.argv[1:] or ['26084']
    for no in targets:
        try:
            official, mism = verify(no)
            if mism:
                print(f'❌ 期号 {no}：发现 {len(mism)} 场 CSV 与官方不一致！')
                for m_no, csv_v, off_v in mism:
                    print(f'   场{m_no}: CSV={csv_v[0]}:{csv_v[1]} 官方={off_v[0]}:{off_v[1]}')
                print(f'   → 请用官方值修正 CSV，或运行修复命令')
            else:
                print(f'✅ 期号 {no}：{len(official)} 场已开奖，CSV 与官方一致')
        except Exception as e:
            print(f'⚠️ 期号 {no} 校验失败：{e}')


if __name__ == '__main__':
    main()
