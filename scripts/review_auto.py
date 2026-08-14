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
import json, math, re, sys
from pathlib import Path

import verify_results as vr

BASE_P = 0.12
BASE_LL = BASE_P * (-math.log(BASE_P)) + (1 - BASE_P) * (-math.log(1 - BASE_P))

LEDGER = Path('docs/review_ledger.md')


def dir_of(score):
    h, a = score.split(':')
    return 'H' if h > a else ('D' if h == a else 'A')


def append_ledger(draw_no, n, hit, dir_hit, by_conf, mismatches):
    """复盘后自动追加账本（修复手写漏记 26084 的问题）。"""
    if n == 0:
        print('⚠️ 无已开奖场次，不写账本')
        return
    if not LEDGER.exists():
        print(f'⚠️ 账本不存在: {LEDGER}')
        return
    txt = LEDGER.read_text(encoding='utf-8')
    date = __import__('datetime').datetime.now().strftime('%m-%d')
    pct = hit / n * 100
    dpct = dir_hit / n * 100
    row = f'| {date} | {draw_no}期 | {n} | {hit} | {pct:.1f}% | {dpct:.1f}% |'
    # 追加到版本C表格（找最后一行数据行，插在其后）
    lines = txt.split('\n')
    c_section = False
    inserted = False
    for i, ln in enumerate(lines):
        if ln.startswith('### 版本C'):
            c_section = True
        if c_section and ln.startswith('| 08-') and not inserted:
            lines.insert(i + 1, row)
            inserted = True
            break
        if c_section and ln.strip() == '' and not inserted:
            lines.insert(i, row)
            inserted = True
            break
    if not inserted:
        lines.append(row)
    # 更新置信度分级累计（A/B/C 行的命中/场次）
    for conf in sorted(by_conf):
        c = by_conf[conf]
        prefix = f'| {conf}级 |'
        for i, ln in enumerate(lines):
            if ln.startswith(prefix) and '样本不足' in ln:
                parts = ln.split('|')
                # ['', ' A级 ', ' 情报... ', ' 1/6 ', ' 16.7% ', ' 样本不足(n=6) ', '']
                if len(parts) >= 6 and '/' in parts[3]:
                    old_hit, old_n = parts[3].strip().split('/')
                    new_hit = int(old_hit) + c['hit']
                    new_n = int(old_n) + c['n']
                    parts[3] = f' {new_hit}/{new_n} '
                    parts[4] = f' {new_hit / new_n * 100:.1f}% '
                    parts[5] = f' 样本不足(n={new_n}) '
                    lines[i] = '|'.join(parts)
                    break
    LEDGER.write_text('\n'.join(lines), encoding='utf-8')
    print(f'✅ 账本已追加 {draw_no}：{n}场 {hit}中={pct:.1f}% | 方向 {dpct:.1f}%')


def main():
    draw_no = sys.argv[1] if len(sys.argv) > 1 else '26084'
    args = sys.argv[2:]
    no_ledger = '--no-ledger' in args
    pred_path = next((a for a in args if not a.startswith('--')), None) or f'predict_{draw_no}.json'
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
    if not no_ledger:
        append_ledger(draw_no, n, hit, dir_hit, by_conf, mismatches)


if __name__ == '__main__':
    main()
