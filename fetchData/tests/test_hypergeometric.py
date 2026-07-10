"""超几何分布 PMF 的数值正确性 + 期望值 + PMF 和为 1。"""

import os
import sys
import unittest
from math import comb

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import metrics


class TestHypergeometric(unittest.TestCase):
    def test_pmf_sums_to_one(self):
        for count in [1, 2, 5, 8, 10, 20]:
            pmf = metrics.hit_distribution(count)
            s = sum(pmf.values())
            self.assertAlmostEqual(s, 1.0, places=10,
                                   msg=f"PMF sum for count={count} is {s}")

    def test_expected_hits_matches_pmf_mean(self):
        for count in [1, 3, 8, 10]:
            pmf = metrics.hit_distribution(count)
            mean = sum(k * p for k, p in pmf.items())
            self.assertAlmostEqual(mean, metrics.expected_hits(count), places=10)
            self.assertAlmostEqual(mean, count * 20 / 80, places=10)

    def test_pmf_matches_reference(self):
        """选 8 个命中 0 的概率 = C(60,8)/C(80,8)."""
        pmf = metrics.hit_distribution(8)
        ref_p0 = comb(60, 8) / comb(80, 8)
        self.assertAlmostEqual(pmf[0], ref_p0, places=10)
        # 命中 20 是不可能的（选 8 个）
        self.assertNotIn(20, pmf)

    def test_variance_positive_and_finite(self):
        for count in [1, 5, 8, 10]:
            v = metrics.hit_variance(count)
            self.assertGreater(v, 0)
            self.assertLess(v, count)


if __name__ == "__main__":
    unittest.main()
