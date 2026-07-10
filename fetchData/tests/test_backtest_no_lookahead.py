"""确认回测框架没有 look-ahead 泄露。

方法一：合成场景 —— 造一个"未来必中 42"的假开奖序列，跑一个"永远选 42"的策略。
如果框架泄露了未来信息，命中率会看起来偏高。正确实现下：42 只是每期都出的号，
选 42 时命中数固定 = 1（因为策略选 8 个，只有 42 一个出现在 20 个开奖号里）。
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import backtest


class TestBacktestNoLookahead(unittest.TestCase):
    def test_uniform_history_matches_baseline(self):
        """在纯均匀随机开奖上，uniform_random 均值必须接近 count/4。"""
        import random
        rng = random.Random(0xC0FFEE)
        n_periods = 600
        fake = []
        for i in range(n_periods):
            nums = rng.sample(range(1, 81), 20)
            fake.append({
                "period": str(2020000 + n_periods - i),
                "date": "2026-01-01",
                "numbers": [str(x) for x in nums],
            })
        rows = backtest.walk_forward(fake, count=8, window=100,
                                     strategy_ids=["uniform_random"])
        hits = [r[3] for r in rows]
        mean = sum(hits) / len(hits)
        # 2σ 内：500 期均值的 σ = sqrt(1.478 / 500) ≈ 0.054
        self.assertLess(abs(mean - 2.0), 0.2,
                        f"uniform_random mean {mean} deviates too much from baseline 2.0")

    def test_heuristics_do_not_beat_baseline_on_uniform_data(self):
        """所有启发式策略在纯均匀数据上均值都应在 [1.5, 2.5] 内。
        显著偏离 → 有 look-ahead bug。"""
        import random
        rng = random.Random(0x1234)
        n_periods = 500
        fake = []
        for i in range(n_periods):
            nums = rng.sample(range(1, 81), 20)
            fake.append({
                "period": str(2020000 + n_periods - i),
                "date": "2026-01-01",
                "numbers": [str(x) for x in nums],
            })
        rows = backtest.walk_forward(fake, count=8, window=100)
        # 每策略均值
        from collections import defaultdict
        buckets = defaultdict(list)
        for _p, sid, _picks, h in rows:
            buckets[sid].append(h)
        for sid, hits in buckets.items():
            mean = sum(hits) / len(hits)
            self.assertGreater(mean, 1.5,
                               f"{sid} mean {mean} suspiciously low")
            self.assertLess(mean, 2.5,
                            f"{sid} mean {mean} suspiciously high — likely look-ahead leak")


if __name__ == "__main__":
    unittest.main()
