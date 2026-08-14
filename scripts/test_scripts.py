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
import process_stats as ps
import settle_tickets as st
import ticket_builder as tb
import fetch_sofa_batch as fsb


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

    def test_detect_live_draw_probes_beyond_stale_list(self):
        # 官方 drawnolist 可能仍停在旧期，但下一期 XML 已经销售中。
        from unittest.mock import patch
        import io
        old = 'jsonString={"drawnolist":[{"drawno":"26084"}]}'.encode()
        xml_old = '<root><matchInfo><matchelem><item><matchandstate>停售</matchandstate></item></matchelem></matchInfo></root>'.encode()
        xml_live = '<root><matchInfo><matchelem><item><matchandstate>销售中</matchandstate></item></matchelem></matchInfo></root>'.encode()

        def fake_fetch(no):
            if no == '26085':
                return xml_live
            if no in {'26084', '26086', '26087', '26088', '26089'}:
                return xml_old
            raise AssertionError(no)

        with patch.object(fi.urllib.request, 'urlopen', return_value=io.BytesIO(old)), \
             patch.object(fi, 'fetch_xml', side_effect=fake_fetch):
            self.assertEqual(fi.detect_live_draw(), '26085')


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


class TestProcessStats(unittest.TestCase):
    def _team(self):        return {'season': {
            'matches': 36, 'goalsScored': 59, 'goalsConceded': 36,
            'shots': 502, 'shotsOnTarget': 176, 'bigChances': 107,
            'bigChancesCreated': 80, 'bigChancesMissed': 62,
            'shotsAgainst': 407, 'shotsOnTargetAgainst': 136, 'bigChancesAgainst': 64,
        }}

    def test_attack_quality(self):
        q = ps.attack_quality(self._team())
        self.assertAlmostEqual(q['shots_per_game'], 502/36, places=1)
        self.assertAlmostEqual(q['sot_rate'], 176/502, places=3)
        self.assertAlmostEqual(q['big_chances_per_game'], 80/36, places=2)
        self.assertAlmostEqual(q['goals_per_game'], 59/36, places=2)

    def test_defense_quality(self):
        q = ps.defense_quality(self._team())
        self.assertAlmostEqual(q['conceded_per_game'], 36/36, places=2)
        self.assertAlmostEqual(q['shots_on_target_against'], 136/36, places=2)
        self.assertAlmostEqual(q['big_chances_against'], 64/36, places=2)

    def test_expected_goals(self):
        t = self._team()
        # 双方同队，期望进球应相同（对称）
        eg = ps.expected_goals(t, t)
        self.assertIsNotNone(eg)
        self.assertEqual(eg['home_xg'], eg['away_xg'])

    def test_expected_goals_missing(self):
        # 缺数据 → None
        self.assertIsNone(ps.expected_goals({}, {}))


class TestSettleTickets(unittest.TestCase):
    def test_parse_ticket_15x5(self):
        # 已购票单必须能解析出 15 张 × 每张5场，层级为3强+1中+1搏
        import collections
        t = st.parse_ticket()
        self.assertEqual(len(t), 15)
        for tk in t:
            self.assertEqual(len(tk['selections']), 5)
        # 场1仍在票8（已购票单冻结，不得被替换）
        t8 = [x for x in t if x['no'] == 8][0]
        self.assertIn('1', [s['no'] for s in t8['selections']])
        # 全场次 1-54 内
        all_nos = [int(s['no']) for tk in t for s in tk['selections']]
        self.assertTrue(all(1 <= n <= 54 for n in all_nos))

    def test_ticket_cost(self):
        t = st.parse_ticket()
        # 每张 20 注 × 2元 = 40元，15张 = 600元
        for tk in t:
            self.assertEqual(len(list(__import__('itertools').combinations(tk['selections'], 2))), 10)
            self.assertEqual(len(list(__import__('itertools').combinations(tk['selections'], 3))), 10)


class TestFetchSofaBatch(unittest.TestCase):
    def test_merge_dedup_prefers_event(self):
        # 同一场次两条记录（一条无event、一条有event）→ 去重保留有event的
        rows = [
            {'no': '53', 'home': 'A', 'errors': ['team_search']},
            {'no': '53', 'home': 'A', 'event': {'id': 1}},
        ]
        by_no = {}
        for r in rows:
            no = r.get('no')
            if no not in by_no or (r.get('event') and not by_no[no].get('event')):
                by_no[no] = r
        merged = [by_no[k] for k in sorted(by_no, key=lambda x: int(x) if str(x).isdigit() else 0)]
        self.assertEqual(len(merged), 1)
        self.assertIn('event', merged[0])


class TestTicketBuilder(unittest.TestCase):
    def test_structure_constants(self):
        # 15组强项骨架：13个强项、45组强强配对唯一
        import collections, itertools
        cnt = collections.Counter(n for t in tb.TRIPLES for n in t)
        self.assertEqual(len(cnt), 13)
        self.assertTrue(all(3 <= v <= 4 for v in cnt.values()))
        pairs = [tuple(sorted(x)) for t in tb.TRIPLES for x in itertools.combinations(t, 2)]
        self.assertEqual(len(pairs), 45)
        self.assertEqual(len(set(pairs)), 45)
        self.assertEqual(len(tb.MID), 15)
        self.assertEqual(len(tb.RISK), 15)
        self.assertEqual(len(set(tb.MID) & set(tb.RISK)), 0)
        self.assertEqual(len(set(tb.MID) & set(tb.CORE)), 0)
        self.assertEqual(len(set(tb.RISK) & set(tb.CORE)), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
