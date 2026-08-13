#!/usr/bin/env python3
"""主动自检：把历史踩过的所有坑，自动查一遍，输出体检报告。

目的：不等用户要求优化，主动发现问题。
覆盖的坑（都是真实踩过的）：
  1. 数据源出错（CSV vs 官方XML不一致）
  2. 脚本语法/测试没过
  3. 球场坐标缓存覆盖不足（导致天气 None）
  4. 半成品（写死值、TODO、待查）
  5. 预测快照没附概率 p / 没生成结构化 predict_*.json
  6. GitHub 镜像丢失 / 有未提交变更
  7. skill 里 SP>5 规则残留（8/10 已取消）
  8. log-loss 基线值写错（应 0.367，非 2.12）

用法：python3 self_check.py [期号]   默认期号 26084
"""
import json, re, subprocess, sys
from pathlib import Path
from datetime import datetime

SRC = Path('/var/minis/shared/beidan_score')
SKILL = Path('SKILL.md')
REPO = Path('/var/minis/workspace/beidan-score-predictor')
CSV = SRC / 'data' / 'beidan_history_2021_2026.csv'
VENUE = SRC / 'venue_cache.json'

issues = []
ok = []


def check(name, cond, detail=''):
    if cond:
        ok.append(name)
    else:
        issues.append(f'{name}：{detail}')


def main():
    draw_no = sys.argv[1] if len(sys.argv) > 1 else '26084'

    # 1. 数据一致性
    try:
        import verify_results as vr
        official, mism = vr.verify(draw_no)
        check(f'数据一致性({draw_no})', not mism,
              f'{len(mism)} 场 CSV 与官方不一致' if mism else '')
    except Exception as e:
        check('数据一致性', False, f'校验失败 {e}')

    # 2. 测试全绿（unittest 输出在 stderr，且看 returncode）
    r = subprocess.run(['python3', 'test_scripts.py'], cwd=SRC, capture_output=True, text=True)
    out = (r.stdout + r.stderr)
    check('脚本测试全绿', r.returncode == 0 and 'FAILED' not in out and 'OK' in out,
          (out.strip().split('\n')[-1] if out.strip() else '无输出') or f'rc={r.returncode}')

    # 3. 坐标缓存覆盖
    if VENUE.exists():
        cache = json.loads(VENUE.read_text(encoding='utf-8'))
        n_cache = len([k for k in cache if not k.startswith('_')])
        check('球场坐标缓存', n_cache >= 30, f'仅 {n_cache} 队，可能天气 None')
    else:
        check('球场坐标缓存', False, 'venue_cache.json 不存在')

    # 4. 半成品检测：只查真信号（TODO/FIXME/写死魔数），排除自检脚本本身
    for f in SRC.glob('*.py'):
        if f.name == 'self_check.py':
            continue
        txt = f.read_text(encoding='utf-8', errors='ignore')
        # 写死时间魔数（fetch_intel 曾经写死 '20:00' 天气时间，是真实半成品）
        if re.search(r"kickoff_hour\s*=\s*'\d{2}:\d{2}'", txt):
            check(f'半成品({f.name})', False, '写死开球时间魔数')
            continue
        if 'TODO' in txt or 'FIXME' in txt:
            check(f'半成品({f.name})', False, '含 TODO/FIXME')

    # 5. 结构化预测 JSON + 概率 p
    reminders = []
    pj = SRC / f'predict_{draw_no}.json'
    if pj.exists():
        data = json.loads(pj.read_text(encoding='utf-8'))
        preds = data.get('predictions', {})
        has_p = any('p' in v for v in preds.values())
        check(f'预测JSON({draw_no})', len(preds) > 0, '无预测')
        # 下期起才强制 p，这里作提醒不判错
        if not has_p:
            reminders.append(f'预测概率p：{draw_no}期预测未附p（下期起强制）')
    else:
        check(f'预测JSON({draw_no})', False, f'predict_{draw_no}.json 不存在')

    # 6. GitHub 镜像 + 未提交变更
    if REPO.exists() and (REPO / '.git').exists():
        r = subprocess.run(['git', 'status', '--short'], cwd=REPO, capture_output=True, text=True)
        check('GitHub镜像未提交变更', not r.stdout.strip(),
              f'{len(r.stdout.strip().splitlines())} 个文件未提交')
    else:
        check('GitHub镜像', False, '本地镜像不存在或未 git init')

    # 7. skill 里 SP>5 残留
    if SKILL.exists():
        txt = SKILL.read_text(encoding='utf-8', errors='ignore')
        bad = [l for l in txt.split('\n') if 'SP>5' in l and '取消' not in l and '已去掉' not in l and '去掉' not in l]
        check('skill无SP>5残留', not bad, f'{len(bad)} 处疑似残留')

    # 8. log-loss 基线值
    llp = SRC / 'log_loss.py'
    if llp.exists():
        txt = llp.read_text(encoding='utf-8', errors='ignore')
        check('log-loss基线正确', 'BASE_LL' in txt and '0.367' in txt, '基线值缺失或错误')

    # 输出报告
    print('=' * 56)
    print(f'北单预测系统 自检报告（{datetime.now().strftime("%Y-%m-%d %H:%M")}）')
    print('=' * 56)
    print(f'✅ 通过 {len(ok)} 项：')
    for x in ok:
        print(f'  ✓ {x}')
    if reminders:
        print(f'\n📌 待办提醒 {len(reminders)} 条（不判错）：')
        for x in reminders:
            print(f'  · {x}')
    if issues:
        print(f'\n❌ 发现 {len(issues)} 个问题：')
        for x in issues:
            print(f'  ✗ {x}')
    else:
        print('\n🎉 无问题，全部健康')
    print('=' * 56)
    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
