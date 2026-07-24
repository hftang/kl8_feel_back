#!/usr/bin/env python3
"""快乐8 数据分析 Web 应用"""

import os

from flask import Flask, jsonify, render_template, request
from kl8tool import (
    fetch_kl8_data, parse_xml_data, generate_charts, recommend,
    _recommend_warm, frequency_analysis, missing_analysis, recency_weighted_frequency,
    trend_analysis, cluster_analysis, repeat_pattern_analysis
)
import backtest as backtest_mod
import store

# 启动时初始化 DB（幂等）
store.init_db()


def _fetch_and_sync(need_count=100):
    """增量获取数据：先检查本地数据库，只获取缺失的期数。

    逻辑：
    1. 检查本地数据库中已有的期号集合
    2. 联网获取最新数据（XML接口返回的数据）
    3. 找出本地缺失的期数，只插入这些
    4. 返回最近 need_count 期数据（优先从数据库读取）

    返回：(data, source, fetched_count)
      - data: 最近 need_count 期数据列表
      - source: 'local' | 'network' | 'mixed'
      - fetched_count: 本次联网获取并插入的新期数
    """
    local_periods = store.get_periods_set()
    local_count = store.draw_count()
    
    if local_count == 0:
        xml = fetch_kl8_data()
        if not xml:
            return None, 'error', 0
        all_rows = parse_xml_data(xml, 100000)
        if not all_rows:
            return None, 'error', 0
        inserted = store.upsert_draws(all_rows)
        store.evaluate_pending_recommendations()
        data = all_rows[:need_count] if len(all_rows) > need_count else all_rows
        return data, 'network', inserted
    
    latest_local = store.latest_period()
    if latest_local is None:
        xml = fetch_kl8_data()
        if not xml:
            return None, 'error', 0
        all_rows = parse_xml_data(xml, 100000)
        if not all_rows:
            return None, 'error', 0
        inserted = store.upsert_draws(all_rows)
        store.evaluate_pending_recommendations()
        data = all_rows[:need_count] if len(all_rows) > need_count else all_rows
        return data, 'network', inserted
    
    xml = fetch_kl8_data()
    if not xml:
        data = store.all_draws_desc(limit=need_count)
        return data, 'local', 0
    
    all_rows = parse_xml_data(xml, 100000)
    if not all_rows:
        data = store.all_draws_desc(limit=need_count)
        return data, 'local', 0
    
    missing_rows = [row for row in all_rows if str(row['period']) not in local_periods]
    
    if not missing_rows:
        data = store.all_draws_desc(limit=need_count)
        return data, 'local', 0
    
    inserted = store.upsert_draws(missing_rows)
    store.evaluate_pending_recommendations()
    data = store.all_draws_desc(limit=need_count)
    return data, 'mixed', inserted


def _next_period(period_str):
    """猜测下一期期号 —— 简单地对最新期号 +1。"""
    if not period_str:
        return None
    try:
        return str(int(period_str) + 1)
    except (TypeError, ValueError):
        return None


app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False           # Flask <3
app.json.ensure_ascii = False                 # Flask 3.x
app.json.sort_keys = False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/fetch")
def api_fetch():
    results, source, fetched_count = _fetch_and_sync(need_count=100)
    if results is None:
        return jsonify({"error": "获取数据失败，请检查网络连接"}), 502

    if not results:
        return jsonify({"error": "解析数据失败"}), 500

    charts = generate_charts(results)
    return jsonify({
        "data": results,
        "charts": charts,
        "source": source,
        "fetched_count": fetched_count,
        "total_db_count": store.draw_count(),
    })


@app.route("/api/recommend")
def api_recommend():
    count = request.args.get("count", 8, type=int)
    count = max(1, min(8, count))

    results, _, _ = _fetch_and_sync(need_count=100)
    if results is None:
        return jsonify({"error": "获取数据失败"}), 502

    if not results:
        return jsonify({"error": "解析数据失败"}), 500

    full_data = store.all_draws_desc()
    if full_data:
        recs = recommend(count, full_data)
    else:
        recs = recommend(count, results)

    # 落库：把本次推荐记录到 recommendations 表，目标期 = 最新期 + 1
    latest = results[0]["period"]
    target = _next_period(latest)
    store.record_recommendations_batch(recs, target_period=target, source="live")

    return jsonify({"count": count, "recommendations": recs, "target_period": target, "data_source": "full_db" if full_data else "partial"})


@app.route("/api/warm")
def api_warm():
    count = request.args.get("count", 3, type=int)
    count = max(1, min(8, count))

    results, _, _ = _fetch_and_sync(need_count=100)
    if results is None:
        return jsonify({"error": "获取数据失败"}), 502

    if not results:
        return jsonify({"error": "解析数据失败"}), 500

    full_data = store.all_draws_desc()
    analyze_data = full_data if full_data else results

    freq = frequency_analysis(analyze_data)
    missing = missing_analysis(analyze_data)
    wfreq = recency_weighted_frequency(analyze_data)

    recs = _recommend_warm(count, freq, missing, wfreq=wfreq, results=analyze_data)

    latest = results[0]["period"]
    target = _next_period(latest)
    store.record_recommendations_batch(recs, target_period=target, source="live")

    return jsonify({"count": count, "recommendations": recs, "target_period": target, "data_source": "full_db" if full_data else "partial"})


@app.route("/api/ingest", methods=["GET", "POST"])
def api_ingest():
    """拉一次 XML 落库并评估待评估的推荐。返回 DB 现状。"""
    before = store.draw_count()
    all_rows = _ingest_latest()
    if all_rows is None:
        return jsonify({"error": "获取数据失败"}), 502
    return jsonify({
        "draws_before": before,
        "draws_after": store.draw_count(),
        "latest_period": store.latest_period(),
    })


@app.route("/api/recommendations/history")
def api_recommendations_history():
    limit = request.args.get("limit", 100, type=int)
    limit = max(1, min(1000, limit))
    return jsonify({
        "items": store.recommendations_history(limit=limit),
    })


@app.route("/api/backtest")
def api_backtest():
    """走向前回测每个策略在历史数据上的命中率，返回均值/CI/p 值。

    ⚠ 使用现有 XML 里能拉到的历史（通常 100 期左右）。Phase 2 落库后可扩到全量。
    """
    count = request.args.get("count", 8, type=int)
    count = max(1, min(10, count))
    window = request.args.get("window", 50, type=int)
    window = max(10, min(200, window))
    periods = request.args.get("periods", None, type=int)

    # 先把最新数据落库
    _ingest_latest()

    # 从 DB 读全量历史（fallback 到 XML 只在库空的极端情况）
    results = store.all_draws_desc()
    if not results:
        xml = fetch_kl8_data()
        if not xml:
            return jsonify({"error": "获取数据失败"}), 502
        results = parse_xml_data(xml, 100000)

    if not results or len(results) <= window:
        return jsonify({
            "error": f"历史期数不足：现有 {len(results) if results else 0}，需要 > window={window}",
        }), 400

    summary = backtest_mod.run_and_summarize(
        results, count=count, window=window, max_periods=periods
    )
    return jsonify(summary)


if __name__ == "__main__":
    # 监听地址/端口可通过环境变量配置；容器内需 HOST=0.0.0.0 才能对外访问
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5001"))
    app.run(debug=False, host=host, port=port, threaded=True)
