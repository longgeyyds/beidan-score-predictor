#!/usr/bin/env python3
"""把 manual_predictions_20260816.md 的最终66场快照转成结构化 predict JSON（review_auto 复盘用）。"""
import json, re
from pathlib import Path

SRC = Path('docs/examples/manual_predictions_20260816.md')
OUT = Path('predict_26085_0816.json')

lines = SRC.read_text(encoding='utf-8').split('\n')
in_final = False
preds = {}
pat = re.compile(r'^(\d+)\s+(.+?)\s+(\d+:\d+)\s+(.+?)\s*$')
for ln in lines:
    if ln.startswith('## 最终66场'):
        in_final = True
        continue
    if not in_final or not ln.strip():
        continue
    m = pat.match(ln.strip())
    if not m:
        print('⚠️ 无法解析:', ln)
        continue
    no, home, score, away = m.groups()
    preds[no] = {'home': home, 'away': away, 'pred': score}

data = {'draw_no': '26085', 'source': 'manual_predictions_20260816.md 最终修正版', 'predictions': preds}
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
print(f'已生成 {len(preds)} 场 → {OUT.name}')
