"""store.py 的幂等性与命中评估正确性。"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import store


class TestStoreIdempotent(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db)  # sqlite 自己会重建
        store.init_db(self.db)

    def tearDown(self):
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_init_db_twice_ok(self):
        store.init_db(self.db)
        store.init_db(self.db)  # 不应报错

    def test_upsert_draws_idempotent(self):
        draws = [
            {"period": "1", "date": "2026-01-01", "numbers": [str(i) for i in range(1, 21)]},
            {"period": "2", "date": "2026-01-02", "numbers": [str(i) for i in range(21, 41)]},
        ]
        n1 = store.upsert_draws(draws, self.db)
        n2 = store.upsert_draws(draws, self.db)
        self.assertEqual(n1, 2)
        self.assertEqual(n2, 0)
        self.assertEqual(store.draw_count(self.db), 2)
        self.assertEqual(store.latest_period(self.db), "2")

    def test_evaluate_recommendations(self):
        # 灌一条开奖 + 一条推荐（3 个命中）
        draw = {"period": "100", "date": "2026-01-01",
                "numbers": ["1", "5", "10", "15", "20", "25", "30", "35",
                            "40", "45", "50", "55", "60", "65", "70", "75",
                            "80", "3", "7", "11"]}
        store.upsert_draws([draw], self.db)
        rid = store.record_recommendation("100", "hot", 5, [1, 5, 10, 99, 100],
                                          source="live", db_path=self.db)
        # 只有 1, 5, 10 在开奖里 → hits = 3
        n = store.evaluate_pending_recommendations(self.db)
        self.assertEqual(n, 1)
        # 重复调用不应重算
        n = store.evaluate_pending_recommendations(self.db)
        self.assertEqual(n, 0)
        hist = store.recommendations_history(10, self.db)
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["hits"], 3)

    def test_evaluate_skips_pending_target(self):
        """target_period 尚未开奖时不应评估。"""
        rid = store.record_recommendation("999", "hot", 5, [1, 2, 3, 4, 5],
                                          source="live", db_path=self.db)
        n = store.evaluate_pending_recommendations(self.db)
        self.assertEqual(n, 0)
        hist = store.recommendations_history(10, self.db)
        self.assertIsNone(hist[0]["hits"])


if __name__ == "__main__":
    unittest.main()
