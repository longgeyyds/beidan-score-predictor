#!/usr/bin/env python3
"""GitHub 自动同步：把 shared/beidan_score 的最新产物同步到公开仓库并 push。

修复"GitHub 镜像丢失 + 同步靠手动"的尾巴。
同步内容（排除 Sofascore 版权数据 team_history.json 和运行产物 runs/settlements/intel）：
  skill/SKILL.md  ← SKILL.md
  scripts/*.py    ← 核心脚本（verify/bets_ev/fetch_intel/update_history + backtest系列）
  docs/*.md       ← 复盘报告 + 累计账本 + 回测报告
  docs/examples/  ← 每日预测快照
  data/*.csv      ← 官方历史赛果

用法：python3 sync_github.py [commit消息]
"""
import shutil, subprocess, sys
from pathlib import Path

SRC = Path('/var/minis/shared/beidan_score')
SKILL = Path('SKILL.md')
DST = Path('/var/minis/workspace/beidan-score-predictor')

# 绝对路径 → 仓库内相对路径（8/12教训：本地路径不能进公开仓库）
PATH_REPLACEMENTS = [
    ('data/beidan_history_2021_2026.csv', 'data/beidan_history_2021_2026.csv'),
    ('data/', 'data/'),
    ('docs/examples/manual_predictions_', 'docs/examples/manual_predictions_'),
    ('docs/review_ledger.md', 'docs/review_ledger.md'),
    ('docs/review_', 'docs/review_'),
    ('docs/win_rate_improvement_analysis.md', 'docs/win_rate_improvement_analysis.md'),
    ('scripts/update_history.py', 'scripts/update_history.py'),
    ('', ''),
    ('', ''),
    ('', ''),
]

CORE_SCRIPTS = [
    'verify_results.py', 'bets_ev.py', 'fetch_intel.py', 'update_history.py',
    'log_loss.py', 'review_auto.py', 'sync_github.py', 'test_scripts.py',
    'self_check.py', 'process_stats.py', 'save_process_data.py',
    'backtest_v8_league_mode.py', 'backtest_v9_halfyear_strict.py',
    'backtest_v9b_strategies.py', 'backtest_v9c_2025pool.py',
    'backtest_v9d_crossyear.py', 'backtest_v9e_dynamic.py',
    'backtest_v10_actual.py', 'backtest_v11_compute.py',
]

DOC_REPORTS = [
    'review_ledger.md', 'league_diagnosis_report.md', 'win_rate_improvement_analysis.md',
    'backtest_v8_report.md', 'backtest_v9_report.md', 'backtest_v10_report.md',
    'review_20260807.md', 'review_20260808.md', 'review_20260809.md',
    'review_20260810.md', 'review_20260812.md', 'review_failures_all.md', 'review_26085_per_match.md', 'lesson_handbook.md',
]


def clean_paths(text):
    for old, new in PATH_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def sync_files():
    copied = []
    # skill
    if SKILL.exists():
        dst = DST / 'skill' / 'SKILL.md'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SKILL, dst)
        copied.append(str(dst))
    # scripts
    for f in CORE_SCRIPTS:
        src = SRC / f
        if src.exists():
            shutil.copy2(src, DST / 'scripts' / f)
            copied.append(f'scripts/{f}')
    # docs 报告
    for f in DOC_REPORTS:
        src = SRC / f
        if src.exists():
            shutil.copy2(src, DST / 'docs' / f)
            copied.append(f'docs/{f}')
    # docs/examples 预测快照
    for src in sorted(SRC.glob('manual_predictions_*.md')) + sorted(SRC.glob('recheck_*.md')):
        shutil.copy2(src, DST / 'docs' / 'examples' / src.name)
        copied.append(f'docs/examples/{src.name}')
    # data CSV
    csv = SRC / 'data' / 'beidan_history_2021_2026.csv'
    if csv.exists():
        shutil.copy2(csv, DST / 'data' / csv.name)
        copied.append(f'data/{csv.name}')
    # 球场坐标缓存
    vc = SRC / 'venue_cache.json'
    if vc.exists():
        shutil.copy2(vc, DST / 'data' / 'venue_cache.json')
        copied.append('data/venue_cache.json')
    # 清理绝对路径（所有 .md/.py）
    for p in DST.rglob('*'):
        if not p.is_file() or p.suffix not in ('.md', '.py'):
            continue
        txt = p.read_text(encoding='utf-8', errors='ignore')
        new = clean_paths(txt)
        if new != txt:
            p.write_text(new, encoding='utf-8')
    return copied


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else 'sync: 更新预测快照/复盘/脚本'
    copied = sync_files()
    # git
    subprocess.run(['git', 'add', '-A'], cwd=DST, check=True)
    r = subprocess.run(['git', 'status', '--short'], cwd=DST, capture_output=True, text=True)
    changed = r.stdout.strip()
    if not changed:
        print('无变更，跳过 push')
        return
    subprocess.run(['git', 'commit', '-q', '-m', msg], cwd=DST, check=True)
    subprocess.run(['git', 'push', '-q'], cwd=DST, check=True)
    print(f'已同步 {len(copied)} 个文件并 push：{msg}')


if __name__ == '__main__':
    main()
