#!/usr/bin/env python3
"""核心脚本单元测试（unittest，无第三方依赖）。

覆盖：verify_results.py / bets_ev.py / fetch_intel.py 的纯函数。
运行：python3 test_scripts.py  或  python3 -m unittest test_scripts
"""
import sys, unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import verify_results as vr
import bets_ev as bev
import fetch_intel as fi
import log_loss as ll
import review_auto as ra


class TestVerifyResults(unittest.TestCase):
    def test_pair_normal(self):
        self.assertEqual(vr.pair('1:0'), ('1', '0'))
        self.assertEqual(vr.pair('3:2'), ('3', '2'))
        self.assertEqual(vr.pair('0:0'), ('0', '0'))

    def test_pair_invalid(self):
        # 胜其它/负其它/空 都不是数字比分，应返回空元组
        self.assertEqual(vr.pair('胜其它'), ('', ''))
        self.assertEqual(vr.pair(''), ('', ''))
        self.assertEqual(vr.pair(None), ('', ''))

    def test_txt_missing(self):
        import xml.etree.ElementTree as ET
        el = ET.fromstring('<a><b>值</b></a>')
        self.assertEqual(vr.txt(el, 'b'), '值')
        self.assertEqual(vr.txt(el, 'c'), '')  # 不存在 → 空串


class TestBetsEv(unittest.TestCase):
    def test_implied_prob(self):
        # 返奖率0.70，SP 4.80 → 0.70/4.80
        self.assertAlmostEqual(bev.implied_prob(4.80), 0.70 / 4.80, places=5)
        self.assertAlmostEqual(bev.implied_prob(152.07), 0.70 / 152.07, places=5)

    def test_combos_count(self):
        sel = [('a', 1, 0.1), ('b', 2, 0.1), ('c', 3, 0.1), ('d', 4, 0.1)]
        self.assertEqual(len(bev.combos(sel, 2)), 6)   # C(4,2)
        self.assertEqual(len(bev.combos(sel, 3)), 4)   # C(4,3)

    def test_ev_of(self):
        # 单场 p=0.5, SP=2 → sp_prod=2, p_all=0.5, ev=0.5*2-1=0
        sp, p_all, ev = bev.ev_of([('x', 2.0, 0.5)])
        self.assertEqual(sp, 2.0)
        self.assertEqual(p_all, 0.5)
        self.assertAlmostEqual(ev, 0.0)
        # 两串：p=0.5*0.5=0.25, sp=2*3=6 → ev=0.25*6-1=0.5
        _, _, ev2 = bev.ev_of([('x', 2.0, 0.5), ('y', 3.0, 0.5)])
        self.assertAlmostEqual(ev2, 0.5)


class TestFetchIntel(unittest.TestCase):
    def test_norm_league(self):
        self.assertEqual(fi.norm_league('25-26英超'), '英超')
        self.assertEqual(fi.norm_league('20-21西甲2'), '西甲2')
        self.assertEqual(fi.norm_league('英超'), '英超')
        self.assertEqual(fi.norm_league(''), '未知赛事')
        self.assertEqual(fi.norm_league(None), '未知赛事')

    def test_load_venue_cache(self):
        cache = fi.load_venue_cache()
        self.assertIsInstance(cache, dict)
        # 缓存文件已存在且含真实队名
        self.assertIn('贝西克塔斯', cache)
        self.assertIn('lat', cache['贝西克塔斯'])
        self.assertIn('lon', cache['贝西克塔斯'])

    def _mk_row(self, d, home, away, score):
        h, a = score.split(':')
        return {'date': datetime.fromisoformat(d), 'league': '测试', 'home': home,
                'away': away, 'hg': int(h), 'ag': int(a), 'score': score}

    def test_team_form_limit_and_order(self):
        rows = [
            self._mk_row('2026-08-01 10:00:00', 'A队', 'X队', '2:1'),
            self._mk_row('2026-08-05 10:00:00', 'B队', 'A队', '0:0'),
            self._mk_row('2026-08-10 10:00:00', 'A队', 'Y队', '1:0'),
        ]
        form = fi.team_form(rows, 'A队', limit=6)
        # A队出现在3场：主场2:1、客场0:0、主场1:0
        self.assertEqual(len(form), 3)
        # 最近一场在前
        self.assertEqual(form[0][0], '26-08-10')

    def test_h2h_and_mid(self):
        # 首回合 8/7，本场 8/14，首回合后 8/9 主队又打了一场
        rows = [
            self._mk_row('2026-08-07 20:00:00', '客队', '主队', '1:0'),  # 首回合
            self._mk_row('2026-08-09 18:00:00', '主队', '另一队', '2:0'),  # 主队中间比赛
            self._mk_row('2026-08-10 18:00:00', '又另一队', '客队', '0:1'),  # 客队中间比赛
        ]
        res = fi.h2h_and_mid(rows, '主队', '客队', '2026-08-14 02:00:00')
        self.assertEqual(len(res['h2h']), 1)
        self.assertIn('26-08-07', res['h2h'][0])
        # 中间比赛：主队1场、客队1场
        self.assertEqual(len(res['mid']['home']), 1)
        self.assertEqual(len(res['mid']['away']), 1)
        self.assertIn('2:0', res['mid']['home'][0])


class TestLogLoss(unittest.TestCase):
    def test_hit_uses_ln_p(self):
        import math
        self.assertAlmostEqual(ll.log_loss('1:1', '1:1', 0.20), -math.log(0.20))

    def test_miss_uses_ln_1p(self):
        import math
        self.assertAlmostEqual(ll.log_loss('1:1', '0:0', 0.20), -math.log(0.80))

    def test_base_ll_value(self):
        # 基线 = 0.12·(-ln0.12) + 0.88·(-ln0.88) ≈ 0.367
        self.assertAlmostEqual(ll.BASE_LL, 0.367, delta=0.002)


class TestReviewAuto(unittest.TestCase):
    def test_dir_of(self):
        self.assertEqual(ra.dir_of('2:1'), 'H')
        self.assertEqual(ra.dir_of('1:1'), 'D')
        self.assertEqual(ra.dir_of('0:1'), 'A')


if __name__ == '__main__':
    unittest.main(verbosity=2)
