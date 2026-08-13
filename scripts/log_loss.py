#!/usr/bin/env python3
"""log-loss 复盘脚本：衡量概率预测的"校准度"，惩罚过度自信。

正确理解（与 skill 早前"基线≈2.12"的错误表述不同，此处已修正）：
- 逐场二分类：预测"本场是比分 X"，给概率 p
  - 命中：log-loss 贡献 = -ln(p)
  - 未命中：log-loss 贡献 = -ln(1-p)
- 平均 log-loss = 总贡献 / 场数，**越低越好**（校准越准）
- 基线（无脑猜1:1，p=0.12 历史众数）平均 log-loss ≈ 0.367：
  = 0.12·(-ln0.12) + 0.88·(-ln0.88) ≈ 0.254 + 0.113 = 0.367

⚠️ 陷阱（必须看懂）：log-loss 衡量的是"p 估得准不准"，不是"命中率高不高"。
  - 若我把 p 估得保守（全给0.10），命中率也10%，log-loss 会"好看"但没信息量。
  - 若我 p=0.20 而实际只中10%，log-loss 会变差——这正是它惩罚"过度自信"的价值。
  - 所以 log-loss 要和命中率一起看：p 的均值 ≈ 实际命中率，才算校准良好。

输入：JSON 文件 [{ "pred": "1:1", "actual": "0:0", "p": 0.20 }, ...]
"""
import json, math, sys
from pathlib import Path

BASE_P = 0.12          # 无脑1:1 的历史众数基线
BASE_LL = (BASE_P * (-math.log(BASE_P)) + (1 - BASE_P) * (-math.log(1 - BASE_P)))


def log_loss(pred, actual, p):
    """单场 log-loss：命中 -ln(p)，未命中 -ln(1-p)"""
    if pred == actual:
        return -math.log(p)
    return -math.log(1 - p)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path or not Path(path).exists():
        print(f'用法: python3 log_loss.py <预测结果JSON>')
        print(f'JSON 格式: [{{"pred":"1:1","actual":"0:0","p":0.20}},...]')
        sys.exit(1)

    data = json.loads(Path(path).read_text(encoding='utf-8'))
    n = hit = 0
    total_ll = 0.0
    p_sum = 0.0
    for d in data:
        pred, actual, p = d['pred'], d['actual'], d['p']
        n += 1
        p_sum += p
        total_ll += log_loss(pred, actual, p)
        if pred == actual:
            hit += 1

    avg_ll = total_ll / n if n else 0
    hit_rate = hit / n if n else 0
    avg_p = p_sum / n if n else 0

    print('=' * 60)
    print('log-loss 复盘（校准度评估）')
    print('=' * 60)
    print(f'场次: {n}  命中: {hit}  命中率: {hit_rate*100:.1f}%')
    print(f'平均估计概率 p: {avg_p*100:.1f}%')
    print(f'平均 log-loss: {avg_ll:.3f}')
    print(f'基线 log-loss: {BASE_LL:.3f}（无脑猜1:1 p=12%）')
    print('-' * 60)
    if avg_ll < BASE_LL:
        print('✅ 低于基线：概率预测比无脑猜更校准')
    else:
        print('❌ 高于基线：概率预测不比无脑猜更校准')
    # 校准度判断：p均值 是否接近 实际命中率
    diff = abs(avg_p - hit_rate)
    print(f'校准偏差: |p均值-命中率| = {diff*100:.1f}% ' + ('（校准良好）' if diff < 0.05 else '（校准差：p估得不准）'))
    print('=' * 60)


if __name__ == '__main__':
    main()
