#!/usr/bin/env python3
"""
美股每日推荐脚本
每天早上 9 点（北京时间）自动运行，生成推荐并创建 GitHub Issue
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf

# ── 推荐池：可自由增减 ──────────────────────────────────────────────────
WATCHLIST = {
    "科技": ["AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA"],
    "金融": ["JPM", "BAC", "GS", "V", "MA"],
    "消费": ["MCD", "SBUX", "NKE", "COST"],
    "医疗": ["JNJ", "UNH", "PFE", "ABBV"],
    "ETF":  ["SPY", "QQQ", "ARKK", "XLF", "XLK"],
}

CST = timezone(timedelta(hours=8))


def fetch_ticker_data(symbol: str) -> dict | None:
    """拉取单只股票数据，计算简单技术指标。"""
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="60d")
        if hist.empty or len(hist) < 20:
            return None

        info = tk.fast_info
        close = hist["Close"]
        price = float(close.iloc[-1])
        prev  = float(close.iloc[-2])
        ma20  = float(close.tail(20).mean())
        ma5   = float(close.tail(5).mean())

        # RSI-14
        delta = close.diff().dropna()
        gain  = delta.clip(lower=0).tail(14).mean()
        loss  = (-delta.clip(upper=0)).tail(14).mean()
        rsi   = 100 - 100 / (1 + gain / loss) if loss != 0 else 50

        change_pct = (price - prev) / prev * 100
        vs_ma20    = (price - ma20) / ma20 * 100

        # 简单打分：RSI 超卖+价格站上均线 → 买入信号
        score = 0
        if rsi < 35:
            score += 2
        elif rsi < 45:
            score += 1
        if price > ma20:
            score += 1
        if ma5 > ma20:
            score += 1
        if change_pct > 0:
            score += 1

        signal = "🟢 买入" if score >= 4 else ("🟡 持有" if score >= 2 else "🔴 观望")

        return {
            "symbol":     symbol,
            "price":      round(price, 2),
            "change_pct": round(change_pct, 2),
            "ma20":       round(ma20, 2),
            "rsi":        round(rsi, 1),
            "vs_ma20":    round(vs_ma20, 2),
            "score":      score,
            "signal":     signal,
        }
    except Exception as e:
        print(f"[WARN] {symbol} 数据获取失败: {e}", file=sys.stderr)
        return None


def build_report(results_by_sector: dict) -> str:
    """生成 Markdown 格式的推荐报告。"""
    now = datetime.now(CST)
    lines = [
        f"# 📈 美股每日推荐 — {now.strftime('%Y-%m-%d')}",
        f"> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} CST\n",
        "---",
        "## 说明",
        "- **评分** 满分 5 分，≥4 🟢买入，≥2 🟡持有，其余 🔴观望",
        "- **RSI** < 35 超卖区间，> 70 超买区间",
        "- 本报告仅供参考，不构成投资建议\n",
        "---",
    ]

    top_picks = []

    for sector, items in results_by_sector.items():
        if not items:
            continue
        lines.append(f"\n## {sector}\n")
        lines.append("| 代码 | 现价 | 涨跌 | RSI | 均线偏离 | 信号 | 评分 |")
        lines.append("|------|-----:|-----:|----:|--------:|------|:----:|")
        for d in sorted(items, key=lambda x: -x["score"]):
            lines.append(
                f"| **{d['symbol']}** "
                f"| ${d['price']} "
                f"| {'+' if d['change_pct'] >= 0 else ''}{d['change_pct']}% "
                f"| {d['rsi']} "
                f"| {'+' if d['vs_ma20'] >= 0 else ''}{d['vs_ma20']}% "
                f"| {d['signal']} "
                f"| {d['score']}/5 |"
            )
            if d["score"] >= 4:
                top_picks.append(d)

    if top_picks:
        lines.append("\n---\n## ⭐ 今日重点关注\n")
        for d in sorted(top_picks, key=lambda x: -x["score"]):
            lines.append(
                f"- **{d['symbol']}**  现价 ${d['price']}，"
                f"RSI {d['rsi']}，评分 {d['score']}/5  {d['signal']}"
            )
    else:
        lines.append("\n---\n## ⭐ 今日重点关注\n")
        lines.append("- 今日暂无强买入信号，建议观望或持仓等待。")

    lines.append("\n---")
    lines.append("*数据来源：Yahoo Finance · 自动生成，请结合基本面独立判断*")
    return "\n".join(lines)


def create_github_issue(title: str, body: str) -> None:
    """通过 GitHub REST API 创建 Issue。"""
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("缺少 GITHUB_TOKEN 或 GITHUB_REPOSITORY，跳过创建 Issue。")
        print(body)
        return

    url  = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title":  title,
        "body":   body,
        "labels": ["stock-report", "automated"],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code == 201:
        data = resp.json()
        print(f"✅ Issue 已创建: {data['html_url']}")
    else:
        print(f"❌ 创建 Issue 失败 ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)


def main():
    print("⏳ 开始拉取行情数据...")
    results_by_sector = {}
    for sector, symbols in WATCHLIST.items():
        items = []
        for sym in symbols:
            data = fetch_ticker_data(sym)
            if data:
                items.append(data)
                print(f"  {sym}: ${data['price']}  RSI={data['rsi']}  {data['signal']}")
        results_by_sector[sector] = items

    report = build_report(results_by_sector)

    now   = datetime.now(CST)
    title = f"📈 美股推荐 {now.strftime('%Y-%m-%d')}"
    create_github_issue(title, report)


if __name__ == "__main__":
    main()
