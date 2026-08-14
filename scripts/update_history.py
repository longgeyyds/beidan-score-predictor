#!/usr/bin/env python3
"""只从北京体彩官方游戏250开奖XML增量更新历史赛果；不读取SP。"""
from __future__ import annotations
import csv, datetime as dt, json, re, time, urllib.request
from pathlib import Path
import xml.etree.ElementTree as ET
BASE='https://www.bjlot.com.cn';CSV=Path('data/beidan_history_2021_2026.csv');RAW=Path('data/raw');UA='Mozilla/5.0 (compatible; BeidanResearchV2/1.0)'
FIELDS=['draw_no','match_no','cutoff_time','league','home','away','ht_home','ht_away','ft_home','ft_away']
def get(u,retries=3):
    """拉取+指数退避重试（修复2026-08-14 IncompleteRead 假失败）。"""
    last=None
    for i in range(retries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':UA,'Referer':BASE+'/'}),timeout=45).read()
        except Exception as e:
            last=e
            if i<retries-1:time.sleep(1.5*(2**i))
    raise last
def js(b):
 s=b.decode('utf-8-sig','replace');return json.loads(s[s.index('{'):])
def text(x,p):
 q=x.find(p);return (q.text or '').strip() if q is not None else ''
def pair(s):
 m=re.fullmatch(r'(\d+):(\d+)',s or '');return (m.group(1),m.group(2)) if m else ('','')
def draws():
 y=dt.datetime.now().year;m=dt.datetime.now().month;out=[]
 for yy,mm in [(y,m),(y,m-1 if m>1 else 12)]:
  if m==1 and mm==12:yy-=1
  try:out += [x['drawno'] for x in js(get(f'{BASE}/data/250/control/drawnolist_{yy}{mm:02d}.js')).get('drawnolist',[])]
  except:pass
 try:out += re.findall(r'\d{5}',get(f'{BASE}/ssm/250/html/gameinfo_his.txt').decode('utf-8-sig','replace'))
 except:pass
 return sorted(set(out))[-8:]
def main():
 old=[];seen=set()
 if CSV.exists():
  with CSV.open(encoding='utf-8-sig',newline='') as f:
   old=list(csv.DictReader(f));seen={(x['draw_no'],x['match_no']) for x in old}
 new=[];RAW.mkdir(parents=True,exist_ok=True)
 for no in draws():
  try:b=get(f'{BASE}/data/250ParlayGetGame_{no}.xml?ts={int(dt.datetime.now().timestamp())}');(RAW/f'{no}.xml').write_bytes(b);root=ET.fromstring(b.decode('utf-8-sig','replace'))
  except Exception as e:print('WARN',no,e);continue
  for x in root.findall('.//matchesp/matchInfo/matchelem/item'):
   n=text(x,'no') or x.get('no','');fh,fa=pair(text(x,'soccer'));hh,ha=pair(text(x,'halfsoccer'))
   if not fh or (no,n) in seen:continue
   new.append({'draw_no':no,'match_no':n,'cutoff_time':text(x,'endTime'),'league':text(x,'leagueName'),'home':text(x,'hostFull') or text(x,'host'),'away':text(x,'guestFull') or text(x,'guest'),'ht_home':hh,'ht_away':ha,'ft_home':fh,'ft_away':fa});seen.add((no,n))
 rows=old+new;rows.sort(key=lambda x:(x['cutoff_time'],x['draw_no'],int(x['match_no'])))
 with CSV.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
 print(json.dumps({'draws_checked':draws(),'old':len(old),'added':len(new),'total':len(rows),'latest':rows[-1]['cutoff_time'] if rows else None},ensure_ascii=False))
if __name__=='__main__':main()
