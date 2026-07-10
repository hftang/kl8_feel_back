"""对照策略 uniform_random 的均值必须收敛到基线 count/4。

这是回测框架完整性的核心指标：任何偏离都说明框架实现有问题。
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import metrics
import backtest


class TestControlMatchesBaseline(unittest.TestCase):
    def test_uniform_random_mean_close_to_baseline(self):
        import random
        rng = random.Random(42)
        n_periods = 1500
        fake = []
        for i in range(n_periods):
            nums = rng.sample(range(1, 81), 20)
            fake.append({
                "period": str(2000000 + n_periods - i),
                "date": "2026-01-01",
                "numbers": [str(x) for x in nums],
            })
        rows = backtest.walk_forward(fake, count=8, window=100,
                                     strategy_ids=["uniform_random"])
        hits = [r[3] for r in rows]
        n = len(hits)
        mean = sum(hits) / n
        baseline = metrics.expected_hits(8)
        # 大样本下均值的标准误 = sqrt(Var/n) ≈ sqrt(1.478/1400) ≈ 0.032
        # 允许 4σ = 0.13 的偏差
        self.assertAlmostEqual(mean, baseline, delta=0.15,
                               msg=f"mean {mean} vs baseline {baseline} n={n}")


if __name__ == "__main__":
    unittest.main()
