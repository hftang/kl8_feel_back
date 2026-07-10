#!/usr/bin/env python3
"""composite 策略的权重调优 —— 随机搜索 + 训练/评估窗口分离。

⚠ 重要认知：
    KL8 是均匀随机抽奖，任何权重组合都不可能让 composite 策略的长期均值
    显著高于基线 count/4。调优器的作用是：
      1) 消除代码里的 25/25/20/15/10/5 魔数
      2) 提供一个可复现的、原则性的权重选择
      3) 明确演示这个天花板（评估窗 CI 应覆盖基线）

    如果调优后评估窗均值远高于基线，几乎可以肯定是 look-ahead bug 或过拟合到训练窗，
    **绝不是**发现了 alpha。

    明确不做：不加梯度下降、不加神经网络、不加 LSTM。它们在均匀分布上同样
    打不过基线，只会让工具看起来"更复杂但更不诚实"。
"""

import argparse
import json
import os
import random
from typing import List

import kl8tool
import metrics
import backtest as backtest_mod

WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights.json")

DEFAULT_WEIGHTS = {
    "w_f": 25.0,
    "w_wf": 25.0,
    "w_m": 20.0,
    "w_z": 15.0,
    "w_oe": 10.0,
    "w_pos": 5.0,
}


def load_weights():
    """加载权重；若无 weights.json 则返回默认。"""
    if os.path.exists(WEIGHTS_PATH):
        try:
            with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_WEIGHTS)


def save_weights(weights, extra=None):
    payload = dict(weights)
    if extra:
        payload["_meta"] = extra
    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def make_parametric_composite(weights):
    """返回一个参数化的 composite 策略函数，签名与其它策略一致。"""
    w_f = weights["w_f"]
    w_wf = weights["w_wf"]
    w_m = weights["w_m"]
    w_z = weights["w_z"]
    w_oe = weights["w_oe"]
    w_pos = weights["w_pos"]

    def _strategy(count, freq, missing, wfreq=None, rng=None):
        wfreq = wfreq or {}
        scores = {}
        max_freq = max(freq.values()) if freq else 1
        max_miss = max(missing.values()) if missing else 1
        max_wfreq = max(wfreq.values()) if wfreq else 1
        if max_wfreq == 0:
            max_wfreq = 1
        for n in range(1, 81):
            f_score = (freq.get(n, 0) / max_freq) * w_f
            wf_score = (wfreq.get(n, 0) / max_wfreq) * w_wf
            m = missing.get(n, 0)
            m_score = min(m / max_miss, 0.6) * w_m
            zone_idx = (n - 1) // 20
            z_score = w_z - abs(zone_idx - 1.5) * (w_z / 3.75)
            oe_score = w_oe if n % 2 == 1 else w_oe * 0.8
            pos_score = w_pos - abs(n - 40) / 40 * w_pos
            scores[n] = f_score + wf_score + m_score + z_score + oe_score + pos_score
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return sorted([n for n, _ in ranked[:count]])

    return _strategy


def _mean_hits_over_window(results_slice, strategy_func, count, window):
    """对 results_slice 跑 walk-forward，只跑一个策略，返回均值。"""
    from backtest import ALL_STRATEGIES
    # 临时把该策略挂进 ALL_STRATEGIES，跑完再撤
    key = "__tune_candidate__"
    ALL_STRATEGIES[key] = strategy_func
    try:
        rows = backtest_mod.walk_forward(
            results_slice, count=count, window=window,
            strategy_ids=[key],
        )
    finally:
        del ALL_STRATEGIES[key]
    hits = [r[3] for r in rows]
    return (sum(hits) / len(hits)) if hits else 0.0, len(hits), hits


def random_search(results, count=8, window=50, n_samples=100, seed=42,
                  train_frac=0.5):
    """在 6 维单纯形上随机搜索权重。

    - train_frac: 训练窗占比（较早的历史用于训练，较近的用于评估）
      results 是 newest-first；training 用 results[eval_size:]，eval 用 results[:eval_size]
    """
    rng = random.Random(seed)
    n_total = len(results)
    # 至少留 window + 20 期给评估、window + 20 期给训练
    min_needed = 2 * (window + 20)
    if n_total < min_needed:
        raise ValueError(
            f"历史期数不足：{n_total} < 需要 {min_needed}（window={window}）"
        )
    eval_size = int(n_total * (1 - train_frac))
    eval_slice = results[:eval_size]                # 最近的一段
    train_slice = results[eval_size:]               # 较早的一段

    best = None
    baseline = metrics.expected_hits(count)
    trials = []
    for i in range(n_samples):
        # 每个权重在 [0, 40] 均匀采样（保持数量级与原始 25/25/20/15/10/5 可比）
        candidate = {
            "w_f":   rng.uniform(0, 40),
            "w_wf":  rng.uniform(0, 40),
            "w_m":   rng.uniform(0, 40),
            "w_z":   rng.uniform(0, 40),
            "w_oe":  rng.uniform(0, 40),
            "w_pos": rng.uniform(0, 40),
        }
        strat = make_parametric_composite(candidate)
        train_mean, train_n, _ = _mean_hits_over_window(train_slice, strat, count, window)
        trials.append({"weights": candidate, "train_mean": train_mean, "train_n": train_n})
        if best is None or train_mean > best["train_mean"]:
            best = trials[-1]
    # 也评估一次默认权重作为基准
    default_strat = make_parametric_composite(DEFAULT_WEIGHTS)
    default_train, default_n, _ = _mean_hits_over_window(train_slice, default_strat, count, window)
    default_eval, _, default_eval_hits = _mean_hits_over_window(eval_slice, default_strat, count, window)

    # 用最优权重跑评估集
    best_strat = make_parametric_composite(best["weights"])
    best_eval, best_eval_n, best_eval_hits = _mean_hits_over_window(eval_slice, best_strat, count, window)
    ci = metrics.bootstrap_ci(best_eval_hits) if best_eval_hits else (0.0, 0.0)
    z, p = metrics.z_test_vs_baseline(best_eval, count, best_eval_n)

    result = {
        "count": count,
        "window": window,
        "baseline_mean": baseline,
        "n_train_periods": default_n,
        "n_eval_periods": best_eval_n,
        "default_weights": DEFAULT_WEIGHTS,
        "default_train_mean": default_train,
        "default_eval_mean": default_eval,
        "best_weights": best["weights"],
        "best_train_mean": best["train_mean"],
        "best_eval_mean": best_eval,
        "best_eval_ci": {"low": ci[0], "high": ci[1]},
        "best_eval_p_vs_baseline": p,
        "significant_vs_baseline": p < 0.05,
        "n_samples": n_samples,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="KL8 composite 权重调优")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--window", type=int, default=50)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-frac", type=float, default=0.5)
    parser.add_argument("--write", action="store_true", help="把最优权重写入 weights.json")
    args = parser.parse_args()

    results = backtest_mod._load_results()
    print(f"[tune] 加载 {len(results)} 期历史")
    out = random_search(results, count=args.count, window=args.window,
                        n_samples=args.samples, seed=args.seed,
                        train_frac=args.train_frac)
    print()
    print(f"[tune] 基线 = {out['baseline_mean']:.3f}")
    print(f"[tune] 训练期数 {out['n_train_periods']} / 评估期数 {out['n_eval_periods']}")
    print(f"[tune] 默认权重 训练均值={out['default_train_mean']:.3f}  评估均值={out['default_eval_mean']:.3f}")
    print(f"[tune] 最优权重 训练均值={out['best_train_mean']:.3f}  评估均值={out['best_eval_mean']:.3f}"
          f"  CI=[{out['best_eval_ci']['low']:.3f}, {out['best_eval_ci']['high']:.3f}]"
          f"  p={out['best_eval_p_vs_baseline']:.3f}")
    print(f"[tune] best weights:")
    for k, v in out["best_weights"].items():
        print(f"        {k:>6} = {v:6.2f}")
    ci_low = out["best_eval_ci"]["low"]
    ci_high = out["best_eval_ci"]["high"]
    if ci_low <= out["baseline_mean"] <= ci_high:
        print("[tune] ✓ 评估集 CI 覆盖基线 —— 符合数学预期（策略不能系统性超越基线）")
    else:
        print("[tune] ⚠ 评估集 CI 未覆盖基线 —— 首先怀疑 look-ahead bug 或过拟合，不是发现了 alpha")
    if args.write:
        save_weights(out["best_weights"], extra={
            "tuned_at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds"),
            "count": args.count,
            "window": args.window,
            "n_samples": args.samples,
            "train_mean": out["best_train_mean"],
            "eval_mean": out["best_eval_mean"],
        })
        print(f"[tune] 写入 {WEIGHTS_PATH}")


if __name__ == "__main__":
    main()
