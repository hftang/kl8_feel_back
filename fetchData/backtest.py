#!/usr/bin/env python3
"""KL8 走向前回测（walk-forward backtest）。

**核心不变量（look-ahead-safe）**：
    对第 t 期（要预测的目标期），特征只能用 t 之前（更早）的数据计算。
    即：history = results_desc[t+1 : t+1+window]
        prediction_target = results_desc[t]
    任何在特征计算中"顺手"读到 results_desc[t] 的实现都会伪造出虚假的命中率。

**核心事实**：KL8 是均匀随机抽奖，选 count 个的期望命中数 = count/4。
任何策略在样本量足够大时都会回归到这个基线。若某策略回测显著高于基线，
**首先怀疑 look-ahead 泄露**，而非策略"找到了 alpha"。
"""

import argparse
import json
import random
from typing import Iterable, Optional

import kl8tool
import metrics


# uniform_random 是必须显式加入的"对照策略"：它的回测均值必须等于 count/4，
# 否则说明回测器本身有 bug（例如 look-ahead 泄露）。
UNIFORM_RANDOM_ID = "uniform_random"


def _uniform_random_strategy(count, freq, missing, wfreq=None, rng=None):
    """对照策略：均匀随机从 1-80 选 count 个。"""
    r = rng or random.Random(0)
    return sorted(r.sample(range(1, 81), count))


ALL_STRATEGIES = dict(kl8tool.RECOMMEND_FUNCS)
ALL_STRATEGIES[UNIFORM_RANDOM_ID] = _uniform_random_strategy


def _hits(picks, winning_numbers):
    """picks: list[int]；winning_numbers: list[str] 或 list[int]。返回交集大小。"""
    win_set = {int(x) for x in winning_numbers}
    return sum(1 for p in picks if p in win_set)


def walk_forward(results_desc, count=8, window=100, min_history=None,
                 strategy_ids: Optional[Iterable[str]] = None,
                 max_periods: Optional[int] = None):
    """对 results_desc 做走向前回测。

    Parameters
    ----------
    results_desc : list[dict]
        与 kl8tool.parse_xml_data 输出同形状，**最新一期在前**（index 0）。
    count : int
        每次推荐几个号（默认 8）。
    window : int
        每期用多长历史窗口算特征（默认 100，与线上一致）。
    min_history : int
        允许开始评估的最少历史期数。默认 = window。t 期评估需要 results_desc[t+1:]
        至少有 `min_history` 期数据。
    strategy_ids : iterable[str]
        限定跑哪些策略。默认跑全部（含 uniform_random 对照组）。
    max_periods : int
        最多回测多少期（None = 尽可能多）。用于快速冒烟测试。

    Returns
    -------
    list[tuple[str, str, list[int], int]]
        (period, strategy_id, picks, hits) 每策略每期一行。
    """
    if min_history is None:
        min_history = window
    total = len(results_desc)
    # 最早允许评估的 t：t + 1 + min_history <= total，即 t <= total - 1 - min_history
    max_t = total - 1 - min_history
    if max_t < 0:
        return []
    sids = list(strategy_ids) if strategy_ids else list(ALL_STRATEGIES.keys())
    rows = []
    # t 从 0 到 max_t（含）—— t=0 就是"预测最新一期"（用 t=1..window 的数据）
    ts = range(0, max_t + 1)
    if max_periods is not None:
        ts = list(ts)[:max_periods]
    for t in ts:
        # 关键：严格切片，绝不使用 results_desc[t]
        history = results_desc[t + 1 : t + 1 + window]
        target = results_desc[t]
        freq = kl8tool.frequency_analysis(history)
        missing = kl8tool.missing_analysis(history)
        wfreq = kl8tool.recency_weighted_frequency(history)
        for sid in sids:
            func = ALL_STRATEGIES[sid]
            rng = random.Random(kl8tool._stable_seed(history, sid))
            try:
                picks = func(count, freq, missing, wfreq=wfreq, rng=rng)
            except TypeError:
                # 若某个 warm_* 策略被误加入这个入口（它们需要 warm_pool），跳过
                continue
            hits = _hits(picks, target["numbers"])
            rows.append((target["period"], sid, picks, hits))
    return rows


def run_and_summarize(results_desc, count=8, window=100, max_periods=None,
                      strategy_ids=None):
    """跑回测并输出结构化摘要（供 API 或 CLI 使用）。"""
    rows = walk_forward(results_desc, count=count, window=window,
                        max_periods=max_periods, strategy_ids=strategy_ids)
    summary = metrics.summarize_with_ci(rows, count)
    return {
        "count": count,
        "window": window,
        "n_periods": len(rows) // max(1, len(set(r[1] for r in rows))),
        "baseline_mean": metrics.expected_hits(count),
        "hit_distribution": metrics.hit_distribution(count),
        "strategies": summary,
    }


def _load_results_from_xml():
    xml = kl8tool.fetch_kl8_data()
    if not xml:
        raise RuntimeError("无法获取 XML 数据")
    return kl8tool.parse_xml_data(xml, count=100000)


def _load_results():
    """优先从 SQLite 读全量历史；库空则回退到 XML。"""
    try:
        import store
        store.init_db()
        rows = store.all_draws_desc()
        if rows:
            return rows
    except Exception:
        pass
    return _load_results_from_xml()


def main():
    parser = argparse.ArgumentParser(description="KL8 走向前回测")
    parser.add_argument("--count", type=int, default=8, help="每次推荐几个号")
    parser.add_argument("--window", type=int, default=100, help="特征窗口长度")
    parser.add_argument("--periods", type=int, default=None, help="最多评估多少期（默认全部）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    results = _load_results()
    print(f"[backtest] 加载到 {len(results)} 期历史数据", flush=True)
    if len(results) <= args.window:
        print(f"[backtest] 警告：历史期数 {len(results)} <= window {args.window}，"
              f"可评估期数为 0。请先跑 /api/ingest 落库到更多期，或调小 --window。")
    out = run_and_summarize(results, count=args.count, window=args.window,
                            max_periods=args.periods)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print()
    print(f"回测：count={args.count}, window={args.window}, 基线={out['baseline_mean']:.3f}")
    print(f"{'策略':<20}{'样本数':>8}{'均值':>10}{'与基线差':>12}{'p值':>10}{'95%CI':>22}")
    print("-" * 82)
    for s in out["strategies"]:
        marker = " *" if s["significant"] else ""
        print(f"{s['strategy_id']:<20}{s['n_periods']:>8}{s['mean_hits']:>10.3f}"
              f"{s['delta_vs_baseline']:>+12.3f}{s['p_value']:>10.3f}"
              f"   [{s['ci_low']:.3f}, {s['ci_high']:.3f}]{marker}")
    print()
    print("注：* 表示与基线差异在 p<0.05 水平上显著。在公平彩票上，样本量足够大时")
    print("    所有策略均应回归到基线附近；显著偏离首先怀疑 look-ahead bug。")


if __name__ == "__main__":
    main()
