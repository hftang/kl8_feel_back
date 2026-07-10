#!/usr/bin/env python3
"""KL8 命中率评估指标 —— 基线、超几何分布、置信区间。

**核心事实**：KL8 每期从 1-80 中均匀随机抽 20 个号码。
对任何 k 个号码的选择，命中数服从超几何分布 Hyper(N=80, K=20, n=k)：
    P(X=x) = C(20,x)*C(60,k-x) / C(80,k)
期望 = k * 20/80 = k/4。任何策略在样本量足够大时都无法系统性偏离这个期望。

此模块的目的：给出显式的基线与统计推断工具，让「策略是否显著优于随机」成为
一个可以被证伪的、有 p 值的问题。
"""

from math import comb, sqrt


def expected_hits(count):
    """选 count 个号，命中数期望值 = count * 20 / 80"""
    return count * 20.0 / 80.0


def hit_distribution(count):
    """返回 {k: P(命中k个)} 的完整超几何 PMF。"""
    n_total = 80
    n_win = 20
    if count > n_total or count < 0:
        raise ValueError(f"count out of range: {count}")
    denom = comb(n_total, count)
    pmf = {}
    for k in range(0, min(count, n_win) + 1):
        pmf[k] = comb(n_win, k) * comb(n_total - n_win, count - k) / denom
    return pmf


def hit_variance(count):
    """单次抽奖下命中数的方差（超几何分布方差）。

    Var = n*K/N * (N-K)/N * (N-n)/(N-1)
    """
    N, K, n = 80, 20, count
    if N <= 1:
        return 0.0
    return n * K / N * (N - K) / N * (N - n) / (N - 1)


def summarize(rows):
    """把 walk_forward 的 rows 汇总为 {strategy_id: {mean, std, n, hits_by_k}}。

    rows: iterable of (period, strategy_id, picks, hits)
    """
    buckets = {}
    for _period, sid, _picks, hits in rows:
        b = buckets.setdefault(sid, [])
        b.append(hits)
    out = {}
    for sid, hits_list in buckets.items():
        n = len(hits_list)
        if n == 0:
            continue
        mean = sum(hits_list) / n
        var = sum((h - mean) ** 2 for h in hits_list) / n if n > 1 else 0.0
        std = sqrt(var)
        counter = {}
        for h in hits_list:
            counter[h] = counter.get(h, 0) + 1
        out[sid] = {
            "n": n,
            "mean": mean,
            "std": std,
            "hits_by_k": counter,
        }
    return out


def z_test_vs_baseline(mean_hits, count, n_periods):
    """单样本 z 检验：观察均值 vs 基线 count/4。

    在均匀随机的原假设下，每期命中数的方差 = hit_variance(count)。
    n 期均值的标准误 = sqrt(Var / n)。
    返回 (z, p_two_sided)。p > 0.05 意味着「与基线不可区分」——
    这是所有策略在样本量足够大时的预期结果。
    """
    if n_periods <= 0:
        return 0.0, 1.0
    baseline = expected_hits(count)
    se = sqrt(hit_variance(count) / n_periods)
    if se == 0:
        return 0.0, 1.0
    z = (mean_hits - baseline) / se
    # 标准正态两侧尾概率的一个简单近似（避免依赖 scipy）
    p = _two_sided_normal_p(abs(z))
    return z, p


def _two_sided_normal_p(z_abs):
    """标准正态双侧 p 值 —— 用 erfc 的多项式近似（够用于 |z| ≤ 8 的场景）。"""
    from math import erfc, sqrt as _sqrt
    # P(|Z| > z) = erfc(z / sqrt(2))
    return erfc(z_abs / _sqrt(2))


def bootstrap_ci(hits_list, n_boot=2000, alpha=0.05, seed=42):
    """对均值做 bootstrap 95% 置信区间。"""
    import random as _r
    n = len(hits_list)
    if n == 0:
        return (0.0, 0.0)
    rng = _r.Random(seed)
    means = []
    for _ in range(n_boot):
        s = 0
        for _i in range(n):
            s += hits_list[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(n_boot * alpha / 2)]
    hi = means[int(n_boot * (1 - alpha / 2))]
    return (lo, hi)


def summarize_with_ci(rows, count):
    """汇总 + 每策略附上 95% CI 与 p 值。用于 /api/backtest 直接返回。"""
    buckets = {}
    for _period, sid, _picks, hits in rows:
        buckets.setdefault(sid, []).append(hits)
    baseline = expected_hits(count)
    out = []
    for sid, hits_list in buckets.items():
        n = len(hits_list)
        mean = sum(hits_list) / n if n else 0.0
        ci = bootstrap_ci(hits_list)
        z, p = z_test_vs_baseline(mean, count, n)
        out.append({
            "strategy_id": sid,
            "n_periods": n,
            "mean_hits": mean,
            "ci_low": ci[0],
            "ci_high": ci[1],
            "baseline_mean": baseline,
            "delta_vs_baseline": mean - baseline,
            "z": z,
            "p_value": p,
            "significant": p < 0.05,
        })
    # 按 mean 降序（视觉上"高的"排在前）
    out.sort(key=lambda x: -x["mean_hits"])
    return out
