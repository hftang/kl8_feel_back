#!/usr/bin/env python3
"""获取福彩快乐8中奖号码，统计分析与趋势图"""

import re
import os
import io
import time
import base64
import random
import threading
from collections import Counter
from itertools import chain, combinations as comb

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 中文字体设置
plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "PingFang SC"]
plt.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- fetch_kl8_data 的进程内 XML 缓存 ----------
# 60 秒内的重复请求直接复用上次拉到的 XML，避免每次点击都打站点。
# Phase 2 落库后此缓存可以拆除。
_FETCH_CACHE_TTL = 60.0
_fetch_cache = {"ts": 0.0, "xml": None}
_fetch_lock = threading.Lock()


def _stable_seed(results, tag):
    """基于最新一期期号 + 策略 tag 的稳定种子。

    要求：同样的历史数据 + 同样的策略 tag 一定产出同样的推荐 —— 这是回测有效性的硬前提。
    """
    if results:
        try:
            latest = int(results[0].get("period", 0))
        except (TypeError, ValueError):
            latest = 0
    else:
        latest = 0
    return (latest * 1315423911) ^ (hash(tag) & 0xFFFFFFFF)


def fetch_kl8_data():
    """从500彩票网XML接口获取快乐8开奖数据（60秒进程内缓存）"""
    from urllib.request import Request, urlopen
    now = time.time()
    with _fetch_lock:
        if _fetch_cache["xml"] is not None and (now - _fetch_cache["ts"]) < _FETCH_CACHE_TTL:
            return _fetch_cache["xml"]
    url = "https://kaijiang.500.com/static/info/kaijiang/xml/kl8/list.xml"
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
        xml = raw.decode("utf-8", errors="replace")
        with _fetch_lock:
            _fetch_cache["ts"] = time.time()
            _fetch_cache["xml"] = xml
        return xml
    except Exception as e:
        with open(os.path.join(OUTPUT_DIR, "_debug.log"), "a", encoding="utf-8") as f:
            f.write(f"fetch EXC: {type(e).__name__}: {e}\n")
        return None


def parse_xml_data(xml_content, count=30):
    """解析XML格式的开奖数据"""
    results = []
    pattern = r'<row expect="(\d+)" opencode="([^"]+)" opentime="([^"]+)"'
    matches = re.findall(pattern, xml_content)

    for i, (period, numbers_str, datetime_str) in enumerate(matches):
        if i >= count:
            break
        date = datetime_str.split(" ")[0]
        numbers = numbers_str.split(",")
        results.append({
            "period": period,
            "date": date,
            "numbers": numbers
        })

    return results


def display_results(results):
    """显示开奖结果"""
    if not results:
        print("未获取到开奖数据")
        return

    print(f"\n{'='*85}")
    print(f"{'福彩快乐8近30期中奖号码':^75}")
    print(f"{'='*85}")
    print(f"{'序号':<6}{'期号':<12}{'开奖日期':<14}{'开奖号码（20个）'}")
    print(f"{'-'*85}")

    for i, r in enumerate(results, 1):
        period = r.get("period", "未知")
        date = r.get("date", "未知")
        numbers = r.get("numbers", [])
        nums_str = " ".join(numbers)
        print(f"{i:<6}{period:<12}{date:<14}{nums_str}")

    print(f"{'='*85}")
    print(f"数据来源: 500彩票网 | 共 {len(results)} 期\n")


# ==================== 统计分析 ====================


def frequency_analysis(results):
    """统计每个号码(1-80)出现的次数"""
    all_numbers = [int(x) for x in chain.from_iterable(r["numbers"] for r in results)]
    counter = Counter(all_numbers)
    return {n: counter.get(n, 0) for n in range(1, 81)}


def recency_weighted_frequency(results, decay=0.97):
    """近期加权频率: 最近一期权重最高, 按decay指数衰减"""
    weighted = {}
    for i, r in enumerate(results):
        weight = decay ** i  # i=0是最近一期, 权重最大
        for n in r["numbers"]:
            v = int(n)
            weighted[v] = weighted.get(v, 0) + weight
    return {n: round(weighted.get(n, 0), 2) for n in range(1, 81)}


def hot_cold_analysis(freq_dict, top_n=10):
    """找出热号(高频)和冷号(低频)"""
    sorted_items = sorted(freq_dict.items(), key=lambda x: x[1], reverse=True)
    hot = sorted_items[:top_n]
    cold = sorted_items[-top_n:]
    return hot, cold


def missing_analysis(results):
    """计算每个号码的遗漏期数(距最近一次出现的间隔)"""
    missing = {}
    for n in range(1, 81):
        for i, r in enumerate(results):
            if n in [int(x) for x in r["numbers"]]:
                missing[n] = i
                break
        else:
            missing[n] = len(results)
    return missing


def odd_even_analysis(results):
    """每期奇偶比统计"""
    stats = []
    for r in results:
        nums = [int(x) for x in r["numbers"]]
        odd = sum(1 for n in nums if n % 2 == 1)
        even = 20 - odd
        stats.append({
            "period": r["period"],
            "date": r["date"],
            "odd": odd,
            "even": even
        })
    return stats


def sum_value_analysis(results):
    """每期号码和值统计"""
    sums = []
    for r in results:
        total = sum(int(x) for x in r["numbers"])
        sums.append({
            "period": r["period"],
            "date": r["date"],
            "sum": total
        })
    return sums


def print_analysis(results):
    """打印统计分析结果"""
    freq = frequency_analysis(results)

    # 频率统计
    print(f"\n{'='*60}")
    print(f"{'号码频率统计（近30期）':^50}")
    print(f"{'='*60}")
    for n in range(1, 81):
        count = freq[n]
        if (n - 1) % 10 == 0 and n > 1:
            print()
        print(f"{n:>2}:{count:>2} ", end="")
    print(f"\n{'='*60}")

    # 冷热号
    hot, cold = hot_cold_analysis(freq)
    print(f"\n{'='*60}")
    print(f"{'热号 TOP10（出现最多）':^50}")
    print(f"{'='*60}")
    for num, count in hot:
        print(f"  号码 {num:>2}  出现 {count} 次")
    print(f"\n{'='*60}")
    print(f"{'冷号 TOP10（出现最少）':^50}")
    print(f"{'='*60}")
    for num, count in cold:
        print(f"  号码 {num:>2}  出现 {count} 次")

    # 遗漏分析
    missing = missing_analysis(results)
    print(f"\n{'='*60}")
    print(f"{'遗漏分析（距上次出现的期数）':^50}")
    print(f"{'='*60}")
    sorted_miss = sorted(missing.items(), key=lambda x: x[1], reverse=True)
    print("  遗漏最多的号码:")
    for num, miss in sorted_miss[:10]:
        print(f"    号码 {num:>2}  已遗漏 {miss} 期")
    print("  遗漏最少的号码:")
    for num, miss in sorted_miss[-10:]:
        print(f"    号码 {num:>2}  已遗漏 {miss} 期")

    # 奇偶分析
    oe_stats = odd_even_analysis(results)
    print(f"\n{'='*60}")
    print(f"{'奇偶比分析':^50}")
    print(f"{'='*60}")
    for s in oe_stats:
        print(f"  第{s['period']}期 ({s['date']}): 奇数{s['odd']}个 偶数{s['even']}个  比值 {s['odd']}:{s['even']}")

    # 和值分析
    sv_stats = sum_value_analysis(results)
    print(f"\n{'='*60}")
    print(f"{'和值分析':^50}")
    print(f"{'='*60}")
    avg_sum = sum(s["sum"] for s in sv_stats) / len(sv_stats)
    print(f"  平均和值: {avg_sum:.1f}")
    print(f"  最大和值: {max(s['sum'] for s in sv_stats)}")
    print(f"  最小和值: {min(s['sum'] for s in sv_stats)}")
    for s in sv_stats:
        print(f"  第{s['period']}期 ({s['date']}): 和值 = {s['sum']}")


# ==================== 趋势图 ====================


def plot_frequency(results):
    """号码出现频率柱状图"""
    freq = frequency_analysis(results)
    numbers = list(range(1, 81))
    counts = [freq[n] for n in numbers]

    fig, ax = plt.subplots(figsize=(18, 6))
    colors = ["#e74c3c" if c >= 20 else "#3498db" if c >= 14 else "#95a5a6" for c in counts]
    ax.bar(numbers, counts, color=colors, edgecolor="white", linewidth=0.5)

    ax.set_xlabel("号码", fontsize=12)
    ax.set_ylabel("出现次数", fontsize=12)
    ax.set_title("福彩快乐8 近30期号码出现频率", fontsize=16, fontweight="bold")
    ax.set_xticks(numbers)
    ax.set_xticklabels(numbers, fontsize=7)
    ax.set_xlim(0, 81)

    # 图例
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#e74c3c", label="热号 (≥20次)"),
        Patch(facecolor="#3498db", label="温号 (14-19次)"),
        Patch(facecolor="#95a5a6", label="冷号 (<14次)"),
    ]
    ax.legend(handles=legend_elements, loc="upper right")

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "kl8_frequency.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  频率图已保存: {path}")


def plot_trend(results):
    """每期和值趋势折线图"""
    sv_stats = sum_value_analysis(results)
    # 按时间正序（最早在左）
    sv_stats = list(reversed(sv_stats))

    periods = [s["period"][-4:] for s in sv_stats]
    sums = [s["sum"] for s in sv_stats]
    avg = sum(sums) / len(sums)

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(periods, sums, marker="o", color="#2ecc71", linewidth=2, markersize=5, label="和值")
    ax.axhline(y=avg, color="#e74c3c", linestyle="--", linewidth=1, label=f"平均值 ({avg:.0f})")

    ax.set_xlabel("期号（后4位）", fontsize=12)
    ax.set_ylabel("和值", fontsize=12)
    ax.set_title("福彩快乐8 近30期和值趋势", fontsize=16, fontweight="bold")
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels(periods, rotation=45, fontsize=8)
    ax.legend()

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "kl8_trend.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  趋势图已保存: {path}")


def plot_odd_even(results):
    """奇偶比例走势"""
    oe_stats = odd_even_analysis(results)
    # 按时间正序
    oe_stats = list(reversed(oe_stats))

    periods = [s["period"][-4:] for s in oe_stats]
    odds = [s["odd"] for s in oe_stats]
    evens = [s["even"] for s in oe_stats]

    fig, ax = plt.subplots(figsize=(14, 6))
    x = range(len(periods))
    width = 0.35

    ax.bar([i - width/2 for i in x], odds, width, label="奇数", color="#e74c3c")
    ax.bar([i + width/2 for i in x], evens, width, label="偶数", color="#3498db")

    ax.set_xlabel("期号（后4位）", fontsize=12)
    ax.set_ylabel("个数", fontsize=12)
    ax.set_title("福彩快乐8 近30期奇偶比走势", fontsize=16, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(periods, rotation=45, fontsize=8)
    ax.legend()

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "kl8_odd_even.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  奇偶图已保存: {path}")


def plot_missing(results):
    """遗漏期数柱状图"""
    missing = missing_analysis(results)
    numbers = list(range(1, 81))
    miss_vals = [missing[n] for n in numbers]

    fig, ax = plt.subplots(figsize=(18, 6))
    colors = ["#e74c3c" if m >= 10 else "#f39c12" if m >= 5 else "#2ecc71" for m in miss_vals]
    ax.bar(numbers, miss_vals, color=colors, edgecolor="white", linewidth=0.5)

    ax.set_xlabel("号码", fontsize=12)
    ax.set_ylabel("遗漏期数", fontsize=12)
    ax.set_title("福彩快乐8 近30期号码遗漏分析", fontsize=16, fontweight="bold")
    ax.set_xticks(numbers)
    ax.set_xticklabels(numbers, fontsize=7)
    ax.set_xlim(0, 81)

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#e74c3c", label="高遗漏 (≥10期)"),
        Patch(facecolor="#f39c12", label="中遗漏 (5-9期)"),
        Patch(facecolor="#2ecc71", label="低遗漏 (<5期)"),
    ]
    ax.legend(handles=legend_elements, loc="upper right")

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "kl8_missing.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  遗漏图已保存: {path}")


# ==================== 选号推荐 ====================


STRATEGIES = [
    {
        "id": "hot",
        "name": "热号追踪（娱乐追热）",
        "desc": "选取近期加权频率最高的号码。追热是常见玩法，但不能提高胜率——每期开奖独立同分布。",
    },
    {
        "id": "cold_rebound",
        "name": "冷号回补（娱乐）",
        "desc": "选取长期未出的号码。冷号回补属于赌徒谬误，仅作组合多样化用，不改变命中概率。",
    },
    {
        "id": "missing",
        "name": "遗漏反弹（娱乐）",
        "desc": "选取遗漏期数较高的号码。基于「该回来了」的直觉，本质上仍是赌徒谬误。",
    },
    {
        "id": "zone_balance",
        "name": "区间均衡",
        "desc": "将1-80分为4个区间(1-20/21-40/41-60/61-80)，每区等比选号。产出「看起来正常」的组合。",
    },
    {
        "id": "odd_even",
        "name": "奇偶均衡",
        "desc": "根据历史奇偶比，选出接近均衡比例的号码组合。同上：只是组合外观选择，不提升胜率。",
    },
    {
        "id": "sum_target",
        "name": "和值控制",
        "desc": "控制所选号码和值接近历史平均值。让组合「看起来常见」，不影响期望命中。",
    },
    {
        "id": "consecutive",
        "name": "连号策略",
        "desc": "包含1-2组相邻号码。历史上连号出现是概率事件，本策略只是外观差异化。",
    },
    {
        "id": "composite",
        "name": "综合推荐",
        "desc": "综合频率+遗漏+区间+奇偶多维度加权，权重可由 tune.py 数据驱动调优。均值无法超基线 count/4。",
    },
]


def _recommend_hot(count, freq, missing, wfreq=None, rng=None):
    """热号追踪 — 近期加权频率排序, 追热不追冷"""
    wfreq = wfreq or {}
    ranked = sorted(wfreq.items(), key=lambda x: (-x[1], x[0]))
    return sorted([n for n, _ in ranked[:count]])


def _recommend_cold_rebound(count, freq, missing, wfreq=None, rng=None):
    """冷号回补 — 总频率低但近期有回暖迹象的号码"""
    wfreq = wfreq or {}
    max_freq = max(freq.values()) if freq else 1
    max_miss = max(missing.values()) if missing else 1
    # 得分: 遗漏高(说明长期没出) + 近期加权频率非零(说明最近有动静)
    scores = {}
    max_wfreq = max(wfreq.values()) if wfreq else 1
    for n in range(1, 81):
        miss_score = missing.get(n, 0) / max_miss * 60  # 遗漏越高越该回补
        freq_penalty = freq.get(n, 0) / max_freq * 30   # 总频率越高扣分
        recent_bonus = min(wfreq.get(n, 0) / max_wfreq * 20, 20) if max_wfreq else 0
        scores[n] = miss_score - freq_penalty + recent_bonus
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return sorted([n for n, _ in ranked[:count]])


def _recommend_missing(count, freq, missing, wfreq=None, rng=None):
    """遗漏反弹 — 遗漏期数最高且历史上出现间隔有规律的号码"""
    max_miss = max(missing.values()) if missing else 1
    max_freq = max(freq.values()) if freq else 1
    scores = {}
    for n in range(1, 81):
        m = missing.get(n, 0)
        f = freq.get(n, 0)
        # 遗漏高得分高, 但历史频率不能太低(完全不出的号可能是真的冷)
        miss_score = m / max_miss * 50
        freq_bonus = f / max_freq * 30  # 历史上出过才有可能反弹
        overdue = max(0, m - f / max_freq * max_miss) * 0.5  # 超期值
        scores[n] = miss_score + freq_bonus + overdue
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return sorted([n for n, _ in ranked[:count]])


def _recommend_zone_balance(count, freq, missing, wfreq=None, rng=None):
    """区间均衡 — 4区等比选号"""
    zones = [(1, 20), (21, 40), (41, 60), (61, 80)]
    per_zone = max(1, count // 4)
    remainder = count - per_zone * 4
    result = []
    for i, (lo, hi) in enumerate(zones):
        n = per_zone + (1 if i < remainder else 0)
        pool = [(freq[num], missing[num], num) for num in range(lo, hi + 1)]
        pool.sort(key=lambda x: (-x[0], x[1]))
        result.extend([p[2] for p in pool[:n]])
    return sorted(result)


def _recommend_odd_even(count, freq, missing, wfreq=None, rng=None):
    """奇偶均衡"""
    odd_count = count // 2 + (count % 2)
    even_count = count - odd_count
    odd_pool = [(freq[n], missing[n], n) for n in range(1, 81) if n % 2 == 1]
    even_pool = [(freq[n], missing[n], n) for n in range(1, 81) if n % 2 == 0]
    odd_pool.sort(key=lambda x: (-x[0], x[1]))
    even_pool.sort(key=lambda x: (-x[0], x[1]))
    result = [p[2] for p in odd_pool[:odd_count]] + [p[2] for p in even_pool[:even_count]]
    return sorted(result)


def _recommend_sum_target(count, freq, missing, wfreq=None, rng=None):
    """和值控制 — 使号码和值接近理论均值"""
    # 理论均值: 80个号选20个，平均约40.5，选count个的和值目标 ≈ count * 40.5
    target = count * 40.5
    pool = [(freq[n] + 1, missing[n], n) for n in range(1, 81)]
    pool.sort(key=lambda x: -x[0])
    # 贪心: 从高频开始，逐步调整使和值接近目标
    selected = []
    current_sum = 0
    for score, miss, n in pool:
        if len(selected) >= count:
            break
        selected.append(n)
        current_sum += n
    # 如果偏离目标太远，交换优化
    pool_sorted = sorted([(freq[n], missing[n], n) for n in range(1, 81)], key=lambda x: x[2])
    _rng = rng or random.Random(0)
    for _ in range(50):
        if abs(current_sum - target) < 2:
            break
        idx = _rng.randrange(len(selected))
        old = selected[idx]
        for _, _, cand in pool_sorted:
            if cand not in selected:
                new_sum = current_sum - old + cand
                if abs(new_sum - target) < abs(current_sum - target):
                    selected[idx] = cand
                    current_sum = new_sum
                    break
    return sorted(selected)


def _recommend_consecutive(count, freq, missing, wfreq=None, rng=None):
    """连号策略 — 包含1-2组相邻号"""
    # 先按频率排序
    sorted_freq = sorted(freq.items(), key=lambda x: -x[1])
    top_nums = [n for n, _ in sorted_freq]
    # 找相邻对
    pairs = []
    for i in range(len(top_nums) - 1):
        a, b = top_nums[i], top_nums[i + 1]
        if b == a + 1:
            pairs.append((a, b))
    result = []
    used = set()
    # 加入第一组连号
    if pairs:
        result.extend(list(pairs[0]))
        used.update(pairs[0])
    # 加入第二组连号(如果数量够)
    for p in pairs[1:]:
        if len(result) >= count:
            break
        for n in p:
            if n not in used and len(result) < count:
                result.append(n)
                used.add(n)
    # 补足剩余
    for n in top_nums:
        if len(result) >= count:
            break
        if n not in used:
            result.append(n)
            used.add(n)
    return sorted(result[:count])


def _recommend_composite(count, freq, missing, wfreq=None, rng=None):
    """综合推荐 — 多维度加权(含近期趋势)。

    权重可从同目录的 weights.json 加载（由 tune.py 产出）；
    若不存在则用与历史 UI 一致的默认 25/25/20/15/10/5 布局。
    """
    wfreq = wfreq or {}
    scores = {}
    max_freq = max(freq.values()) if freq else 1
    max_miss = max(missing.values()) if missing else 1
    max_wfreq = max(wfreq.values()) if wfreq else 1
    if max_wfreq == 0:
        max_wfreq = 1
    w = _load_composite_weights()
    for n in range(1, 81):
        # 总频率得分
        f_score = (freq.get(n, 0) / max_freq) * w["w_f"]
        # 近期加权频率 — 最近出得多的号更活跃
        wf_score = (wfreq.get(n, 0) / max_wfreq) * w["w_wf"]
        # 遗漏得分 — 适度遗漏有"该反弹了"的直觉价值（本质是赌徒谬误，仅供组合多样化）
        m = missing.get(n, 0)
        m_score = min(m / max_miss, 0.6) * w["w_m"]
        # 区间均衡
        zone_idx = (n - 1) // 20
        z_score = w["w_z"] - abs(zone_idx - 1.5) * (w["w_z"] / 3.75)
        # 奇偶
        oe_score = w["w_oe"] if n % 2 == 1 else w["w_oe"] * 0.8
        # 位置分
        pos_score = w["w_pos"] - abs(n - 40) / 40 * w["w_pos"]
        scores[n] = f_score + wf_score + m_score + z_score + oe_score + pos_score
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return sorted([n for n, _ in ranked[:count]])


_COMPOSITE_DEFAULT_WEIGHTS = {
    "w_f": 25.0, "w_wf": 25.0, "w_m": 20.0,
    "w_z": 15.0, "w_oe": 10.0, "w_pos": 5.0,
}

_composite_weights_cache = {"path_mtime": None, "w": None}


def _load_composite_weights():
    """加载 weights.json（有则用，无则回退默认）。基于 mtime 简单缓存。"""
    path = os.path.join(OUTPUT_DIR, "weights.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        _composite_weights_cache["w"] = dict(_COMPOSITE_DEFAULT_WEIGHTS)
        _composite_weights_cache["path_mtime"] = None
        return _composite_weights_cache["w"]
    if _composite_weights_cache["path_mtime"] == mt and _composite_weights_cache["w"]:
        return _composite_weights_cache["w"]
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            raw = _json.load(f)
        w = {k: float(raw.get(k, _COMPOSITE_DEFAULT_WEIGHTS[k])) for k in _COMPOSITE_DEFAULT_WEIGHTS}
    except Exception:
        w = dict(_COMPOSITE_DEFAULT_WEIGHTS)
    _composite_weights_cache["w"] = w
    _composite_weights_cache["path_mtime"] = mt
    return w


RECOMMEND_FUNCS = {
    "hot": _recommend_hot,
    "cold_rebound": _recommend_cold_rebound,
    "missing": _recommend_missing,
    "zone_balance": _recommend_zone_balance,
    "odd_even": _recommend_odd_even,
    "sum_target": _recommend_sum_target,
    "consecutive": _recommend_consecutive,
    "composite": _recommend_composite,
}


def recommend(count, results):
    """对每种策略生成推荐号码。

    所有随机策略基于 (最新期号, 策略id) 派生的确定种子 —— 同样输入必产生同样输出。
    这是回测/复现的硬前提。
    """
    freq = frequency_analysis(results)
    missing = missing_analysis(results)
    wfreq = recency_weighted_frequency(results)
    output = []
    for s in STRATEGIES:
        rng = random.Random(_stable_seed(results, s["id"]))
        nums = RECOMMEND_FUNCS[s["id"]](count, freq, missing, wfreq=wfreq, rng=rng)
        output.append({
            "id": s["id"],
            "name": s["name"],
            "desc": s["desc"],
            "numbers": nums,
        })
    return output


# ==================== Web 接口 ====================


def _fig_to_base64(fig):
    """将 matplotlib figure 转为 base64 字符串"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return b64


# 下面 4 组 _render_* 是无副作用的绘图核心，_plot_*_b64 / plot_* 分别用作 web 输出与 CLI 落盘。
# 避免了原版两条路径 30 行雷同代码的重复。
def _render_frequency(ax, results):
    freq = frequency_analysis(results)
    numbers = list(range(1, 81))
    counts = [freq[n] for n in numbers]
    colors = ["#e74c3c" if c >= 20 else "#3498db" if c >= 14 else "#95a5a6" for c in counts]
    ax.bar(numbers, counts, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("号码", fontsize=11)
    ax.set_ylabel("出现次数", fontsize=11)
    ax.set_title(f"号码出现频率（近{len(results)}期）", fontsize=14, fontweight="bold")
    ax.set_xticks(numbers)
    ax.set_xticklabels(numbers, fontsize=6)
    ax.set_xlim(0, 81)
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor="#e74c3c", label="热号 (>=20次)"),
        Patch(facecolor="#3498db", label="温号 (14-19次)"),
        Patch(facecolor="#95a5a6", label="冷号 (<14次)"),
    ], loc="upper right")


def _render_trend(ax, results):
    sv = list(reversed(sum_value_analysis(results)))
    periods = [s["period"][-4:] for s in sv]
    sums = [s["sum"] for s in sv]
    avg = sum(sums) / len(sums) if sums else 0
    ax.plot(periods, sums, marker="o", color="#2ecc71", linewidth=2, markersize=4, label="和值")
    ax.axhline(y=avg, color="#e74c3c", linestyle="--", linewidth=1, label=f"平均值 ({avg:.0f})")
    ax.set_xlabel("期号", fontsize=11)
    ax.set_ylabel("和值", fontsize=11)
    ax.set_title(f"和值趋势（近{len(results)}期）", fontsize=14, fontweight="bold")
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels(periods, rotation=45, fontsize=7)
    ax.legend()


def _render_odd_even(ax, results):
    oe = list(reversed(odd_even_analysis(results)))
    periods = [s["period"][-4:] for s in oe]
    odds = [s["odd"] for s in oe]
    evens = [s["even"] for s in oe]
    x = range(len(periods))
    w = 0.35
    ax.bar([i - w/2 for i in x], odds, w, label="奇数", color="#e74c3c")
    ax.bar([i + w/2 for i in x], evens, w, label="偶数", color="#3498db")
    ax.set_xlabel("期号", fontsize=11)
    ax.set_ylabel("个数", fontsize=11)
    ax.set_title(f"奇偶比走势（近{len(results)}期）", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(periods, rotation=45, fontsize=7)
    ax.legend()


def _render_missing(ax, results):
    missing = missing_analysis(results)
    numbers = list(range(1, 81))
    miss_vals = [missing[n] for n in numbers]
    colors = ["#e74c3c" if m >= 10 else "#f39c12" if m >= 5 else "#2ecc71" for m in miss_vals]
    ax.bar(numbers, miss_vals, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("号码", fontsize=11)
    ax.set_ylabel("遗漏期数", fontsize=11)
    ax.set_title(f"号码遗漏分析（近{len(results)}期）", fontsize=14, fontweight="bold")
    ax.set_xticks(numbers)
    ax.set_xticklabels(numbers, fontsize=6)
    ax.set_xlim(0, 81)
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor="#e74c3c", label="高遗漏 (>=10期)"),
        Patch(facecolor="#f39c12", label="中遗漏 (5-9期)"),
        Patch(facecolor="#2ecc71", label="低遗漏 (<5期)"),
    ], loc="upper right")


def _plot_frequency_b64(results):
    fig, ax = plt.subplots(figsize=(16, 5))
    _render_frequency(ax, results)
    plt.tight_layout()
    return _fig_to_base64(fig)


def _plot_trend_b64(results):
    fig, ax = plt.subplots(figsize=(12, 5))
    _render_trend(ax, results)
    plt.tight_layout()
    return _fig_to_base64(fig)


def _plot_odd_even_b64(results):
    fig, ax = plt.subplots(figsize=(12, 5))
    _render_odd_even(ax, results)
    plt.tight_layout()
    return _fig_to_base64(fig)


def _plot_missing_b64(results):
    fig, ax = plt.subplots(figsize=(16, 5))
    _render_missing(ax, results)
    plt.tight_layout()
    return _fig_to_base64(fig)


def generate_charts(results):
    """生成4张图表，返回 base64 字典"""
    return {
        "frequency": _plot_frequency_b64(results),
        "trend": _plot_trend_b64(results),
        "odd_even": _plot_odd_even_b64(results),
        "missing": _plot_missing_b64(results),
    }



WARM_STRATEGIES = [
    {
        "id": "warm_hot",
        "name": "温号高频（娱乐）",
        "desc": "从温号池（频率中间60%）中选取频率最高的号码。追温不追冷，不改变期望命中。",
    },
    {
        "id": "warm_rebound",
        "name": "温号回补（娱乐）",
        "desc": "选取温号池中遗漏期数较高的号码，博反弹。本质是赌徒谬误。",
    },
    {
        "id": "warm_recent",
        "name": "温号近期",
        "desc": "选取温号池中近期活跃度（加权频率）最高的号码。",
    },
    {
        "id": "warm_zone",
        "name": "温号均衡",
        "desc": "从温号池中按四区（1-20/21-40/41-60/61-80）等比选号。",
    },
    {
        "id": "warm_oddeven",
        "name": "温号奇偶",
        "desc": "从温号池中奇偶均衡选取号码组合。",
    },
    {
        "id": "warm_sum",
        "name": "温号和值",
        "desc": "控制所选温号和值接近历史平均值，避免极端。",
    },
    {
        "id": "warm_seq",
        "name": "温号连号",
        "desc": "从温号池中包含1-2组连号的选号策略。",
    },
    {
        "id": "warm_composite",
        "name": "温号综合",
        "desc": "综合频率、遗漏、近期、区间、奇偶多维度加权选号。",
    },
]


def _warm_hot(count, freq, missing, warm_pool, wfreq=None, rng=None):
    """温号高频 — 温号池内按频率排序选最高频"""
    pool = [(freq[n], n) for n in warm_pool]
    pool.sort(key=lambda x: -x[0])
    return sorted([n for _, n in pool[:count]])


def _warm_rebound(count, freq, missing, warm_pool, wfreq=None, rng=None):
    """温号回补 — 温号池内遗漏期数高的优先，博冷门回补"""
    pool = [(missing[n], freq[n], n) for n in warm_pool]
    pool.sort(key=lambda x: (-x[0], -x[1]))
    return sorted([n for _, _, n in pool[:count]])


def _warm_recent(count, freq, missing, warm_pool, wfreq=None, rng=None):
    """温号近期 — 温号池内按近期加权频率排序"""
    wfreq = wfreq or {}
    pool = [(wfreq.get(n, 0), freq[n], n) for n in warm_pool]
    pool.sort(key=lambda x: (-x[0], -x[1]))
    return sorted([n for _, _, n in pool[:count]])


def _warm_zone(count, freq, missing, warm_pool, wfreq=None, rng=None):
    """温号均衡 — 温号池内四区等比选号"""
    zones = [(1, 20), (21, 40), (41, 60), (61, 80)]
    per_zone = max(1, count // 4)
    remainder = count - per_zone * 4
    result = []
    for i, (lo, hi) in enumerate(zones):
        n = per_zone + (1 if i < remainder else 0)
        zone_pool = [(freq[num], num) for num in warm_pool if lo <= num <= hi]
        zone_pool.sort(key=lambda x: -x[0])
        result.extend([p[1] for p in zone_pool[:n]])
    return sorted(result)


def _warm_oddeven(count, freq, missing, warm_pool, wfreq=None, rng=None):
    """温号奇偶 — 温号池内奇偶均衡"""
    odd_count = count // 2 + (count % 2)
    even_count = count - odd_count
    odd_pool = [(freq[n], n) for n in warm_pool if n % 2 == 1]
    even_pool = [(freq[n], n) for n in warm_pool if n % 2 == 0]
    odd_pool.sort(key=lambda x: -x[0])
    even_pool.sort(key=lambda x: -x[0])
    result = [p[1] for p in odd_pool[:odd_count]] + [p[1] for p in even_pool[:even_count]]
    return sorted(result)


def _warm_sum(count, freq, missing, warm_pool, wfreq=None, rng=None):
    """温号和值 — 温号池内控制和值接近理论均值"""
    target = count * 40.5
    pool = sorted([(freq[n], n) for n in warm_pool], key=lambda x: -x[0])
    selected = []
    cur = 0
    for _, num in pool:
        if len(selected) >= count:
            break
        selected.append(num)
        cur += num
    all_nums = sorted(warm_pool)
    _rng = rng or random.Random(0)
    for _ in range(50):
        if abs(cur - target) < 2:
            break
        idx = _rng.randrange(len(selected))
        old = selected[idx]
        for cand in all_nums:
            if cand not in selected:
                new_sum = cur - old + cand
                if abs(new_sum - target) < abs(cur - target):
                    selected[idx] = cand
                    cur = new_sum
                    break
    return sorted(selected)


def _warm_seq(count, freq, missing, warm_pool, wfreq=None, rng=None):
    """温号连号 — 温号池内优先包含连号组合"""
    sorted_freq = sorted([(freq[n], n) for n in warm_pool], key=lambda x: -x[0])
    top = [n for _, n in sorted_freq]
    pairs = []
    for i in range(len(top) - 1):
        a, b = top[i], top[i + 1]
        if b == a + 1:
            pairs.append((a, b))
    result = []
    used = set()
    if pairs:
        result.extend(list(pairs[0]))
        used.update(pairs[0])
    for p in pairs[1:]:
        if len(result) >= count:
            break
        for n in p:
            if n not in used and len(result) < count:
                result.append(n)
                used.add(n)
    for n in top:
        if len(result) >= count:
            break
        if n not in used:
            result.append(n)
            used.add(n)
    return sorted(result[:count])


def _warm_composite(count, freq, missing, warm_pool, wfreq=None, rng=None):
    """温号综合 — 温号池内多维度加权评分"""
    wfreq = wfreq or {}
    scores = {}
    max_freq = max(freq[n] for n in warm_pool) if warm_pool else 1
    max_miss = max(missing[n] for n in warm_pool) if warm_pool else 1
    max_wfreq = max(wfreq.get(n, 0) for n in warm_pool) if warm_pool else 1
    if max_wfreq == 0:
        max_wfreq = 1
    for n in warm_pool:
        f_score = (freq.get(n, 0) / max_freq) * 25
        wf_score = (wfreq.get(n, 0) / max_wfreq) * 25
        m = missing.get(n, 0)
        m_score = min(m / max_miss, 0.6) * 20 if max_miss > 0 else 0
        zone_idx = (n - 1) // 20
        z_score = 15 - abs(zone_idx - 1.5) * 4
        oe_score = 10 if n % 2 == 1 else 8
        pos_score = 5 - abs(n - 40) / 40 * 5
        scores[n] = f_score + wf_score + m_score + z_score + oe_score + pos_score
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return sorted([n for n, _ in ranked[:count]])


WARM_RECOMMEND_FUNCS = {
    "warm_hot": _warm_hot,
    "warm_rebound": _warm_rebound,
    "warm_recent": _warm_recent,
    "warm_zone": _warm_zone,
    "warm_oddeven": _warm_oddeven,
    "warm_sum": _warm_sum,
    "warm_seq": _warm_seq,
    "warm_composite": _warm_composite,
}


def _recommend_warm(count, freq, missing, wfreq=None, results=None):
    """基于温号池（频率处于中间60%的中频号码）的多策略推荐。

    wfreq / results 是 Phase 0 去全局化后新加的显式参数：
      - wfreq 提供给 warm_recent / warm_composite；调用方通常先算好一次传进来
      - results 用来为随机策略派生稳定种子；未提供则用零种子（仍确定性）
    """
    wfreq = wfreq or {}
    # 动态计算温号池：取频率排序后中间60%的号码
    sorted_freq = sorted(freq.items(), key=lambda x: x[1])
    n_total = len(sorted_freq)
    lo = max(0, int(n_total * 0.20))
    hi = min(n_total, int(n_total * 0.80))
    warm_pool = set([n for n, _ in sorted_freq[lo:hi]])
    if len(warm_pool) < count:
        # 池太小则从高频区补足
        extra = [n for n, _ in reversed(sorted_freq[:lo])]
        warm_pool.update(extra[:count - len(warm_pool)])

    output = []
    for s in WARM_STRATEGIES:
        rng = random.Random(_stable_seed(results or [], s["id"]))
        nums = WARM_RECOMMEND_FUNCS[s["id"]](count, freq, missing, warm_pool, wfreq=wfreq, rng=rng)
        output.append({
            "id": s["id"],
            "name": s["name"],
            "desc": s["desc"],
            "numbers": nums,
        })
    return output
