#!/usr/bin/env python3
"""自动复盘：读官方 XML 最新赛果，对比预测 JSON，输出逐场结果 + 命中统计。

修复"复盘靠手写 markdown、漏读快照"的尾巴（漏过梦幻v2）。
输入：预测 JSON（scripts/predict_{期号}.json 或任意路径），格式：
  { "draw_no":"26084", "predictions": {
      "20":{"home":"托博尔","away":"游击","pred":"1:1","p":0.20,"conf":"B"}, ... } }

用法：
  python3 review_auto.py 26084 [预测JSON路径]
  # 默认读 predict_26084.json；带 p 字段时顺便输出 log-loss
"""
import json, math, sys
from pathlib import Path

import verify_results as vr

BASE_P = 0.12
BASE_LL = BASE_P * (-math.log(BASE_P)) + (1 - BASE_P) * (-math.log(1 - BASE_P))


def dir_of(score):
    h, a = score.split(':')
    return 'H' if h > a else ('D' if h == a else 'A')


def main():
    draw_no = sys.argv[1] if len(sys.argv) > 1 else '26084'
    pred_path = sys.argv[2] if len(sys.argv) > 2 else f'predict_{draw_no}.json'
    if not Path(pred_path).exists():
        print(f'预测文件不存在: {pred_path}')
        sys.exit(1)
    preds = json.loads(Path(pred_path).read_text(encoding='utf-8'))['predictions']

    # 拉官方赛果
    official, mismatches = vr.verify(draw_no)

    n = hit = dir_hit = 0
    total_ll = 0.0
    p_sum = 0.0
    has_p = False
    by_conf = {}
    print(f'=== {draw_no} 期自动复盘 ===')
    print(f'{"场":>3} {"对阵":<22} {"预测":>5} {"实际":>5} {"精确":>4} {"方向":>4}')
    print('-' * 55)
    for no in sorted(preds, key=int):
        d = preds[no]
        actual = official.get(no)
        if not actual:
            print(f'{no:>3} {d["home"]+"vs"+d["away"]:<22} {d["pred"]:>5} {"未开":>5}')
            continue
        actual_str = f'{actual[0]}:{actual[1]}'
        pred = d['pred']
        n += 1
        is_hit = pred == actual_str
        hit += is_hit
        is_dir = dir_of(pred) == dir_of(actual_str)
        dir_hit += is_dir
        p = d.get('p')
        if p is not None:
            has_p = True
            p_sum += p
            total_ll += -math.log(p) if is_hit else -math.log(1 - p)
        conf = d.get('conf', '?')
        c = by_conf.setdefault(conf, {'n': 0, 'hit': 0})
        c['n'] += 1
        c['hit'] += is_hit
        print(f'{no:>3} {d["home"]+"vs"+d["away"]:<22} {pred:>5} {actual_str:>5} {"✅" if is_hit else "❌":>4} {"✅" if is_dir else "❌":>4}')

    print('-' * 55)
    print(f'已开奖 {n} 场：精确 {hit}/{n} = {hit/n*100:.1f}% | 方向 {dir_hit}/{n} = {dir_hit/n*100:.1f}%')
    if has_p:
        avg_ll = total_ll / n if n else 0
        print(f'log-loss: {avg_ll:.3f}（基线 {BASE_LL:.3f}） | p均值 {p_sum/n*100:.1f}%')
    if by_conf:
        print('置信度分组:')
        for conf in sorted(by_conf):
            c = by_conf[conf]
            print(f'  {conf}级: {c["hit"]}/{c["n"]} = {c["hit"]/c["n"]*100:.1f}%')
    if mismatches:
        print(f'⚠️ 注意：{len(mismatches)} 场 CSV 与官方不一致，已用官方值')


if __name__ == '__main__':
    main()
