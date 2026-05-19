#!/usr/bin/env python3
"""快乐8 数据分析 Web 应用"""

from flask import Flask, jsonify, render_template, request
from kl8tool import fetch_kl8_data, parse_xml_data, generate_charts, recommend

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/fetch")
def api_fetch():
    xml = fetch_kl8_data()
    if not xml:
        return jsonify({"error": "获取数据失败，请检查网络连接"}), 502

    results = parse_xml_data(xml, 50)
    if not results:
        return jsonify({"error": "解析数据失败"}), 500

    charts = generate_charts(results)
    return jsonify({
        "data": results,
        "charts": charts,
    })


@app.route("/api/recommend")
def api_recommend():
    count = request.args.get("count", 8, type=int)
    count = max(1, min(8, count))

    xml = fetch_kl8_data()
    if not xml:
        return jsonify({"error": "获取数据失败"}), 502

    results = parse_xml_data(xml, 50)
    if not results:
        return jsonify({"error": "解析数据失败"}), 500

    recs = recommend(count, results)
    return jsonify({"count": count, "recommendations": recs})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
