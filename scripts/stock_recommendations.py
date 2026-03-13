#!/usr/bin/env python3
"""
Daily Stock Pick — TikTok FinTok 热门股票推荐
数据来源：StockTwits trending + Yahoo Finance trending + Reddit WSB
每天早上 6:06 北京时间自动运行，生成推荐并创建 GitHub Issue
"""

import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf

CST = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── 数据源 1：StockTwits Trending ────────────────────────────────────────────
def fetch_stocktwits_trending() -> list[str]:
    """StockTwits 实时热门 ticker（对标 TikTok FinTok 话题）。"""
    url = "https://api.stocktwits.com/api/2/trending/symbols.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        symbols = [s["symbol"] for s in resp.json().get("symbols", [])]
        print(f"  StockTwits trending: {symbols}")
        return symbols
    except Exception as e:
        print(f"[WARN] StockTwits 失败: {e}", file=sys.stderr)
        return []


# ── 数据源 2：Yahoo Finance Trending ────────────────────────────────────────
def fetch_yahoo_trending() -> list[str]:
    """Yahoo Finance 热门 ticker。"""
    url = "https://query1.finance.yahoo.com/v1/finance/trending/US?count=20"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        quotes = (
            resp.json()
            .get("finance", {})
            .get("result", [{}])[0]
            .get("quotes", [])
        )
        symbols = [q["symbol"] for q in quotes if "." not in q.get("symbol", ".")]
        print(f"  Yahoo trending:      {symbols}")
        return symbols
    except Exception as e:
        print(f"[WARN] Yahoo trending 失败: {e}", file=sys.stderr)
        return []


# ── 数据源 3：Reddit r/wallstreetbets 热词 ───────────────────────────────────
_TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')
_IGNORE = {
    "A", "I", "AM", "IT", "AT", "BE", "DO", "GO", "IF", "IN", "IS", "ME",
    "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE", "AI",
    "DD", "EV", "FD", "GG", "OP", "OG", "PM", "TD", "THE", "CEO", "IPO",
    "ETF", "ATH", "SEC", "IRS", "GDP", "IMO", "LOL", "WTF", "EOD", "AH",
    "DRS", "GME", "AMC",   # 留着 GME / AMC 太老，可视情况移除
}

def fetch_wsb_trending() -> list[str]:
    """从 Reddit WSB 热帖标题中提取高频 ticker。"""
    url = "https://www.reddit.com/r/wallstreetbets/hot.json?limit=50"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        posts = resp.json()["data"]["children"]
        counter: Counter = Counter()
        for p in posts:
            text = p["data"]["title"] + " " + p["data"].get("selftext", "")
            for m in _TICKER_RE.findall(text):
                if m not in _IGNORE:
                    counter[m] += 1
        symbols = [s for s, _ in counter.most_common(15)]
        print(f"  WSB hot tickers:     {symbols}")
        return symbols
    except Exception as e:
        print(f"[WARN] Reddit WSB 失败: {e}", file=sys.stderr)
        return []


# ── 合并热度排名 ─────────────────────────────────────────────────────────────
def get_trending_symbols(top_n: int = 20) -> list[str]:
    """
    三个来源加权合并：StockTwits × 3，Yahoo × 2，WSB × 1
    模拟 TikTok FinTok 热度排行
    """
    counter: Counter = Counter()

    for sym in fetch_stocktwits_trending():
        counter[sym] += 3
    for sym in fetch_yahoo_trending():
        counter[sym] += 2
    for sym in fetch_wsb_trending():
        counter[sym] += 1

    # 过滤非美股 / 异常符号
    ranked = [
        s for s, _ in counter.most_common()
        if re.match(r'^[A-Z]{1,5}$', s)
    ]
    return ranked[:top_n]


# ── 技术面分析 ───────────────────────────────────────────────────────────────
def analyze(symbol: str) -> dict | None:
    try:
        tk   = yf.Ticker(symbol)
        hist = tk.history(period="60d")
        if hist.empty or len(hist) < 20:
            return None

        info  = tk.fast_info
        close = hist["Close"]
        vol   = hist["Volume"]

        price    = float(close.iloc[-1])
        prev     = float(close.iloc[-2])
        ma20     = float(close.tail(20).mean())
        ma5      = float(close.tail(5).mean())
        avg_vol  = float(vol.tail(20).mean())
        cur_vol  = float(vol.iloc[-1])
        vol_ratio = cur_vol / avg_vol if avg_vol else 1

        # RSI-14
        delta = close.diff().dropna()
        gain  = delta.clip(lower=0).tail(14).mean()
        loss  = (-delta.clip(upper=0)).tail(14).mean()
        rsi   = 100 - 100 / (1 + gain / loss) if loss != 0 else 50

        change_pct = (price - prev) / prev * 100
        vs_ma20    = (price - ma20) / ma20 * 100

        # ── 综合评分（满分 6）──
        score = 0
        if rsi < 35:           score += 2   # 超卖
        elif rsi < 45:         score += 1
        if price > ma20:       score += 1   # 站上均线
        if ma5 > ma20:         score += 1   # 短期动能
        if vol_ratio > 1.5:    score += 1   # 成交量放大（社媒热度催化）
        if change_pct > 0:     score += 1

        signal = "🟢 买入" if score >= 5 else ("🟡 持有" if score >= 3 else "🔴 观望")

        return {
            "symbol":     symbol,
            "price":      round(price, 2),
            "change_pct": round(change_pct, 2),
            "ma20":       round(ma20, 2),
            "rsi":        round(rsi, 1),
            "vs_ma20":    round(vs_ma20, 2),
            "vol_ratio":  round(vol_ratio, 2),
            "score":      score,
            "signal":     signal,
        }
    except Exception as e:
        print(f"[WARN] {symbol} 分析失败: {e}", file=sys.stderr)
        return None


# ── 报告生成 ─────────────────────────────────────────────────────────────────
def build_report(results: list[dict], raw_trending: list[str]) -> str:
    now = datetime.now(CST)
    lines = [
        f"# 📈 Daily Stock Pick — {now.strftime('%Y-%m-%d')}",
        f"> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} CST  "
        f"· 数据来源：StockTwits / Yahoo Finance / Reddit WSB（对标 TikTok FinTok 热榜）\n",
        "---",
        "## 🔥 今日社媒热门 Ticker（原始榜单）",
        "```",
        "  ".join(raw_trending),
        "```\n",
        "---",
        "## 📊 技术面分析\n",
        "| 排名 | 代码 | 现价 | 涨跌 | RSI | 均线偏离 | 量比 | 信号 | 评分 |",
        "|:----:|------|-----:|-----:|----:|--------:|-----:|------|:----:|",
    ]

    top_picks = []
    for i, d in enumerate(results, 1):
        lines.append(
            f"| {i} "
            f"| **{d['symbol']}** "
            f"| ${d['price']} "
            f"| {'+' if d['change_pct'] >= 0 else ''}{d['change_pct']}% "
            f"| {d['rsi']} "
            f"| {'+' if d['vs_ma20'] >= 0 else ''}{d['vs_ma20']}% "
            f"| {d['vol_ratio']}x "
            f"| {d['signal']} "
            f"| {d['score']}/6 |"
        )
        if d["score"] >= 5:
            top_picks.append(d)

    lines.append("\n---\n## ⭐ 今日精选 Pick\n")
    if top_picks:
        for d in sorted(top_picks, key=lambda x: -x["score"]):
            lines.append(
                f"### {d['symbol']}  {d['signal']}\n"
                f"- 现价：**${d['price']}**，当日 {'+' if d['change_pct'] >= 0 else ''}{d['change_pct']}%\n"
                f"- RSI：{d['rsi']}{'（超卖区间 ⚡）' if d['rsi'] < 35 else ''}\n"
                f"- 偏离 MA20：{'+' if d['vs_ma20'] >= 0 else ''}{d['vs_ma20']}%\n"
                f"- 成交量比：{d['vol_ratio']}x 均量\n"
                f"- 综合评分：**{d['score']}/6**\n"
            )
    else:
        best = sorted(results, key=lambda x: -x["score"])[:3]
        lines.append("今日暂无强买入信号（评分 < 5），观察候选：\n")
        for d in best:
            lines.append(f"- **{d['symbol']}**  {d['signal']}  评分 {d['score']}/6")

    lines += [
        "\n---",
        "## 说明",
        "- **评分 6 分制**：RSI 超卖 +2、站上 MA20 +1、短期动能 +1、量比 >1.5x +1、当日上涨 +1",
        "- **量比 >1.5x**：社媒热度催化，成交放量",
        "- *本报告仅供学习参考，不构成投资建议*",
    ]
    return "\n".join(lines)


# ── 创建 GitHub Issue ────────────────────────────────────────────────────────
def create_github_issue(title: str, body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("缺少 GITHUB_TOKEN / GITHUB_REPOSITORY，打印报告：")
        print(body)
        return

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"title": title, "body": body, "labels": ["stock-report", "automated"]},
        timeout=30,
    )
    if resp.status_code == 201:
        print(f"✅ Issue 已创建: {resp.json()['html_url']}")
    else:
        print(f"❌ 创建 Issue 失败 ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main():
    print("🔍 正在抓取社媒热门 Ticker（对标 TikTok FinTok）...")
    trending = get_trending_symbols(top_n=20)
    if not trending:
        print("❌ 未获取到任何热门 ticker，退出。", file=sys.stderr)
        sys.exit(1)

    print(f"\n📋 共 {len(trending)} 只候选，开始技术面分析...")
    results = []
    for sym in trending:
        data = analyze(sym)
        if data:
            results.append(data)
            print(f"  {sym:6s}  ${data['price']}  RSI={data['rsi']}  {data['signal']}")

    if not results:
        print("❌ 所有 ticker 数据获取失败。", file=sys.stderr)
        sys.exit(1)

    # 按综合评分排序
    results.sort(key=lambda x: -x["score"])

    report = build_report(results, trending)
    now    = datetime.now(CST)
    title  = f"📈 Daily Stock Pick {now.strftime('%Y-%m-%d')} — TikTok FinTok 热榜精选"
    create_github_issue(title, report)


if __name__ == "__main__":
    main()
