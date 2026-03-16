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
import numpy as np

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
    "DRS", "GME", "AMC",
}

def fetch_wsb_trending() -> list[str]:
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
    counter: Counter = Counter()
    for sym in fetch_stocktwits_trending():
        counter[sym] += 3
    for sym in fetch_yahoo_trending():
        counter[sym] += 2
    for sym in fetch_wsb_trending():
        counter[sym] += 1
    ranked = [
        s for s, _ in counter.most_common()
        if re.match(r'^[A-Z]{1,5}$', s)
    ]
    return ranked[:top_n]


# ── 宏观数据 ─────────────────────────────────────────────────────────────────
def fetch_macro_data() -> dict:
    """抓取 SPY/QQQ/DIA/VIX/DXY 当日数据。"""
    macro = {}
    for sym in ["SPY", "QQQ", "DIA", "^VIX", "DX-Y.NYB"]:
        try:
            tk   = yf.Ticker(sym)
            hist = tk.history(period="5d")
            if hist.empty:
                continue
            price = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
            chg   = (price - prev) / prev * 100
            label = sym.replace("^", "").replace("-Y.NYB", "")
            macro[label] = {"price": round(price, 2), "change": round(chg, 2)}
        except Exception as e:
            print(f"[WARN] 宏观数据 {sym} 失败: {e}", file=sys.stderr)
    return macro


# ── EMA 辅助 ─────────────────────────────────────────────────────────────────
def _ema(series, span: int):
    return series.ewm(span=span, adjust=False).mean()


# ── 技术面分析（完整版）───────────────────────────────────────────────────────
def analyze(symbol: str) -> dict | None:
    try:
        tk   = yf.Ticker(symbol)
        hist = tk.history(period="1y")
        if hist.empty or len(hist) < 60:
            return None

        close  = hist["Close"]
        high   = hist["High"]
        low    = hist["Low"]
        vol    = hist["Volume"]

        price    = float(close.iloc[-1])
        open_p   = float(hist["Open"].iloc[-1])
        high_p   = float(high.iloc[-1])
        low_p    = float(low.iloc[-1])
        prev     = float(close.iloc[-2])

        # ── 均线 ──
        ma5   = float(close.tail(5).mean())
        ma20  = float(close.tail(20).mean())
        ma60  = float(close.tail(60).mean())
        ma200 = float(close.mean()) if len(close) >= 200 else float(close.mean())

        # ── 涨跌幅 ──
        change_day  = (price - prev) / prev * 100
        week_start  = float(close.iloc[-6]) if len(close) >= 6 else prev
        change_week = (price - week_start) / week_start * 100

        # ── 成交量 ──
        avg_vol20 = float(vol.tail(20).mean())
        cur_vol   = float(vol.iloc[-1])
        vol_ratio = cur_vol / avg_vol20 if avg_vol20 else 1

        # ── RSI-14 ──
        delta = close.diff().dropna()
        gain  = delta.clip(lower=0).rolling(14).mean().iloc[-1]
        loss  = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
        rsi   = 100 - 100 / (1 + gain / loss) if loss and loss != 0 else 50

        # ── MACD (12,26,9) ──
        ema12    = _ema(close, 12)
        ema26    = _ema(close, 26)
        macd_line   = ema12 - ema26
        signal_line = _ema(macd_line, 9)
        macd_val    = float(macd_line.iloc[-1])
        signal_val  = float(signal_line.iloc[-1])
        macd_prev   = float(macd_line.iloc[-2])
        sig_prev    = float(signal_line.iloc[-2])
        if macd_prev < sig_prev and macd_val > signal_val:
            macd_status = "🟢 金叉"
        elif macd_prev > sig_prev and macd_val < signal_val:
            macd_status = "🔴 死叉"
        elif macd_val > signal_val:
            macd_status = "📈 多头排列"
        else:
            macd_status = "📉 空头排列"

        # ── 布林带 (20, 2) ──
        bb_mid  = float(close.tail(20).mean())
        bb_std  = float(close.tail(20).std())
        bb_up   = round(bb_mid + 2 * bb_std, 2)
        bb_low  = round(bb_mid - 2 * bb_std, 2)
        bb_mid  = round(bb_mid, 2)
        if price >= bb_up * 0.99:
            bb_pos = "上轨附近（超买警惕）"
        elif price <= bb_low * 1.01:
            bb_pos = "下轨附近（超卖关注）"
        else:
            bb_pos = "中轨区间"

        # ── 支撑位 / 阻力位（近 30 日高低点）──
        recent = close.tail(30)
        resistance = sorted([
            round(float(recent.nlargest(1).iloc[0]), 2),
            round(float(recent.nlargest(3).iloc[-1]), 2),
        ])
        support = sorted([
            round(float(recent.nsmallest(1).iloc[0]), 2),
            round(float(recent.nsmallest(3).iloc[-1]), 2),
        ])

        # ── 均线关系描述 ──
        def vs_ma(p, m, label):
            diff = (p - m) / m * 100
            pos  = "站上" if p > m else "跌破"
            return f"{pos} {label}（{'+' if diff >= 0 else ''}{diff:.1f}%）"

        ma_status = [
            vs_ma(price, ma5, "MA5"),
            vs_ma(price, ma20, "MA20"),
            vs_ma(price, ma60, "MA60"),
            vs_ma(price, ma200, "MA200"),
        ]

        # ── RSI 状态 ──
        if rsi >= 70:
            rsi_status = "超买 ⚠️"
        elif rsi <= 30:
            rsi_status = "超卖 ⚡"
        else:
            rsi_status = "中性"

        # ── 综合评分（满分 6）──
        score = 0
        if rsi < 35:           score += 2
        elif rsi < 45:         score += 1
        if price > ma20:       score += 1
        if ma5 > ma20:         score += 1
        if vol_ratio > 1.5:    score += 1
        if change_day > 0:     score += 1

        signal = "🟢 买入" if score >= 5 else ("🟡 持有" if score >= 3 else "🔴 观望")

        # ── 期权数据 ──
        call_vol, put_vol, unusual_opts = 0, 0, []
        try:
            exps = tk.options
            if exps:
                chain = tk.option_chain(exps[0])
                call_vol = int(chain.calls["volume"].fillna(0).sum())
                put_vol  = int(chain.puts["volume"].fillna(0).sum())
                # 异常期权：成交量 > openInterest * 3 且成交量 > 1000
                for _, row in chain.calls.iterrows():
                    if row.get("volume", 0) > max(row.get("openInterest", 1) * 3, 1000):
                        unusual_opts.append(
                            f"CALL ${row['strike']:.0f} 到期{exps[0]} 量{int(row['volume'])}"
                        )
                for _, row in chain.puts.iterrows():
                    if row.get("volume", 0) > max(row.get("openInterest", 1) * 3, 1000):
                        unusual_opts.append(
                            f"PUT  ${row['strike']:.0f} 到期{exps[0]} 量{int(row['volume'])}"
                        )
        except Exception:
            pass

        cp_ratio = (call_vol / put_vol) if put_vol > 0 else None

        # ── 基本面 / 情绪面（yfinance info）──
        info = {}
        try:
            info = tk.info or {}
        except Exception:
            pass

        short_float    = info.get("shortPercentOfFloat")
        analyst_rating = info.get("recommendationKey", "N/A")
        target_price   = info.get("targetMeanPrice")
        analyst_count  = info.get("numberOfAnalystOpinions", 0)
        inst_own       = info.get("institutionalOwnershipPercent") or info.get("heldPercentInstitutions")
        sector         = info.get("sector", "N/A")
        next_earnings  = info.get("earningsDate") or info.get("earningsTimestamp")

        # ── 近期新闻（最多 3 条）──
        news_items = []
        try:
            raw_news = tk.news or []
            for n in raw_news[:3]:
                title    = n.get("title", "")
                pub_time = n.get("providerPublishTime", 0)
                if pub_time:
                    dt = datetime.fromtimestamp(pub_time, tz=CST).strftime("%m-%d %H:%M")
                else:
                    dt = "--"
                news_items.append(f"[{dt}] {title}")
        except Exception:
            pass

        # ── 盘前盘后 ──
        pre_price  = info.get("preMarketPrice")
        post_price = info.get("postMarketPrice")

        return {
            "symbol":        symbol,
            "sector":        sector,
            # 市场表现
            "price":         round(price, 2),
            "open_p":        round(open_p, 2),
            "high_p":        round(high_p, 2),
            "low_p":         round(low_p, 2),
            "change_day":    round(change_day, 2),
            "change_week":   round(change_week, 2),
            "cur_vol":       int(cur_vol),
            "avg_vol20":     int(avg_vol20),
            "vol_ratio":     round(vol_ratio, 2),
            "pre_price":     pre_price,
            "post_price":    post_price,
            # 技术面
            "ma5":           round(ma5, 2),
            "ma20":          round(ma20, 2),
            "ma60":          round(ma60, 2),
            "ma200":         round(ma200, 2),
            "ma_status":     ma_status,
            "rsi":           round(rsi, 1),
            "rsi_status":    rsi_status,
            "macd_val":      round(macd_val, 3),
            "signal_val":    round(signal_val, 3),
            "macd_status":   macd_status,
            "support":       support,
            "resistance":    resistance,
            "bb_up":         bb_up,
            "bb_mid":        bb_mid,
            "bb_low":        bb_low,
            "bb_pos":        bb_pos,
            # 期权
            "call_vol":      call_vol,
            "put_vol":       put_vol,
            "cp_ratio":      round(cp_ratio, 2) if cp_ratio else None,
            "unusual_opts":  unusual_opts[:3],
            # 情绪面
            "short_float":   short_float,
            "analyst_rating": analyst_rating,
            "target_price":  target_price,
            "analyst_count": analyst_count,
            "inst_own":      inst_own,
            "next_earnings": next_earnings,
            "news":          news_items,
            # 评分
            "score":         score,
            "signal":        signal,
            "vs_ma20":       round((price - ma20) / ma20 * 100, 2),
        }
    except Exception as e:
        print(f"[WARN] {symbol} 分析失败: {e}", file=sys.stderr)
        return None


# ── 格式化大数字 ─────────────────────────────────────────────────────────────
def _fmt_vol(v: int) -> str:
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v/1_000:.0f}K"
    return str(v)


# ── 报告生成 ─────────────────────────────────────────────────────────────────
def build_report(results: list[dict], raw_trending: list[str], macro: dict) -> str:
    now = datetime.now(CST)
    lines = [
        f"# 📈 Daily US Stock — {now.strftime('%Y-%m-%d')}",
        f"> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} CST  "
        f"· 数据来源：StockTwits / Yahoo Finance / Reddit WSB\n",
        "---",
    ]

    # ── 5. 宏观联动 ──
    lines += ["## 🌐 宏观联动\n", "| 指标 | 现价 | 日涨跌 |", "|------|-----:|------:|"]
    macro_labels = {"SPY": "SPY（标普500ETF）", "QQQ": "QQQ（纳指ETF）",
                    "DIA": "DIA（道指ETF）", "VIX": "VIX 恐慌指数", "DX": "DXY 美元指数"}
    for k, label in macro_labels.items():
        key = "DX" if k == "DX" else k
        if key in macro:
            m = macro[key]
            sign = "+" if m["change"] >= 0 else ""
            lines.append(f"| {label} | {m['price']} | {sign}{m['change']}% |")
    lines.append("")

    # ── 热门榜单 ──
    lines += [
        "---",
        "## 🔥 今日社媒热门 Ticker（原始榜单）",
        "```",
        "  ".join(raw_trending),
        "```\n",
        "---",
        "## 📊 综合评分一览\n",
        "| 排名 | 代码 | 现价 | 日涨跌 | 周涨跌 | RSI | 量比 | MACD | 信号 | 评分 |",
        "|:----:|------|-----:|------:|------:|----:|-----:|------|------|:----:|",
    ]

    for i, d in enumerate(results, 1):
        lines.append(
            f"| {i} "
            f"| **{d['symbol']}** "
            f"| ${d['price']} "
            f"| {'+' if d['change_day'] >= 0 else ''}{d['change_day']}% "
            f"| {'+' if d['change_week'] >= 0 else ''}{d['change_week']}% "
            f"| {d['rsi']} ({d['rsi_status'].split()[0]}) "
            f"| {d['vol_ratio']}x "
            f"| {d['macd_status']} "
            f"| {d['signal']} "
            f"| {d['score']}/6 |"
        )

    lines.append("\n---\n## 🔍 个股详细分析\n")

    for d in results:
        sym = d["symbol"]
        lines += [
            f"<details>",
            f"<summary><b>{sym}</b>  {d['signal']}  评分 {d['score']}/6  （{d.get('sector','N/A')}）</summary>\n",

            # 1. 市场表现
            f"### 1️⃣ 市场表现",
            f"| | 数值 |",
            f"|---|---|",
            f"| 收盘价 | **${d['price']}** |",
            f"| 开盘价 | ${d['open_p']} |",
            f"| 最高价 | ${d['high_p']} |",
            f"| 最低价 | ${d['low_p']} |",
            f"| 日涨跌 | {'+' if d['change_day'] >= 0 else ''}{d['change_day']}% |",
            f"| 周涨跌 | {'+' if d['change_week'] >= 0 else ''}{d['change_week']}% |",
            f"| 当日成交量 | {_fmt_vol(d['cur_vol'])} |",
            f"| 20日均量 | {_fmt_vol(d['avg_vol20'])} |",
            f"| 量比 | **{d['vol_ratio']}x** {'🔥 显著放量' if d['vol_ratio'] > 1.5 else ('💤 缩量' if d['vol_ratio'] < 0.7 else '正常')} |",
        ]

        # 盘前盘后
        pre_str  = f"${d['pre_price']}"  if d.get("pre_price")  else "暂无"
        post_str = f"${d['post_price']}" if d.get("post_price") else "暂无"
        lines += [
            f"| 盘前价 | {pre_str} |",
            f"| 盘后价 | {post_str} |",
            "",
        ]

        # 2. 技术面快照
        lines += [
            f"### 2️⃣ 技术面快照",
            f"**关键均线**",
            f"| 均线 | 数值 | 价格关系 |",
            f"|------|-----:|---------|",
            f"| MA5 | ${d['ma5']} | {d['ma_status'][0]} |",
            f"| MA20 | ${d['ma20']} | {d['ma_status'][1]} |",
            f"| MA60 | ${d['ma60']} | {d['ma_status'][2]} |",
            f"| MA200 | ${d['ma200']} | {d['ma_status'][3]} |",
            "",
            f"**指标**",
            f"- RSI(14)：**{d['rsi']}** — {d['rsi_status']}",
            f"- MACD：{d['macd_status']}  (MACD={d['macd_val']}, Signal={d['signal_val']})",
            f"- 布林带：上轨 ${d['bb_up']} / 中轨 ${d['bb_mid']} / 下轨 ${d['bb_low']} — 当前位于**{d['bb_pos']}**",
            "",
            f"**支撑位**：${d['support'][0]}  /  ${d['support'][1]}",
            f"**阻力位**：${d['resistance'][0]}  /  ${d['resistance'][1]}",
            "",
        ]

        # 3. 关键事件与催化剂
        lines.append(f"### 3️⃣ 关键事件与催化剂")
        if d.get("news"):
            lines.append("**近期新闻**")
            for n in d["news"]:
                lines.append(f"- {n}")
        else:
            lines.append("- 暂无近期新闻数据")

        if d.get("next_earnings"):
            try:
                ts = d["next_earnings"]
                if isinstance(ts, (int, float)):
                    dt_str = datetime.fromtimestamp(ts, tz=CST).strftime("%Y-%m-%d")
                else:
                    dt_str = str(ts)
                lines.append(f"\n📅 下次财报：**{dt_str}**")
            except Exception:
                pass
        lines.append("")

        # 4. 期权与资金流向
        lines.append(f"### 4️⃣ 期权与资金流向")
        if d["call_vol"] or d["put_vol"]:
            cp = f"{d['cp_ratio']:.2f}" if d["cp_ratio"] else "N/A"
            lines += [
                f"| | 数值 |",
                f"|---|---|",
                f"| Call 成交量 | {_fmt_vol(d['call_vol'])} |",
                f"| Put 成交量 | {_fmt_vol(d['put_vol'])} |",
                f"| Call/Put 比 | **{cp}** {'（偏多）' if d['cp_ratio'] and d['cp_ratio'] > 1 else '（偏空）'} |",
            ]
            if d["unusual_opts"]:
                lines.append("\n**异常期权活动**")
                for o in d["unusual_opts"]:
                    lines.append(f"- {o}")
        else:
            lines.append("- 期权数据暂不可用")
        lines.append("")

        # 6. 情绪面
        lines.append(f"### 6️⃣ 情绪面")
        if d.get("analyst_rating") and d["analyst_rating"] != "N/A":
            tp = f"${d['target_price']:.2f}" if d.get("target_price") else "N/A"
            upside = ""
            if d.get("target_price"):
                up = (d["target_price"] - d["price"]) / d["price"] * 100
                upside = f"（较现价 {'+' if up >= 0 else ''}{up:.1f}%）"
            lines += [
                f"- 分析师评级：**{d['analyst_rating'].upper()}**（{d['analyst_count']} 位分析师）",
                f"- 目标价：{tp} {upside}",
            ]
        if d.get("short_float") is not None:
            sf = d["short_float"] * 100 if d["short_float"] < 1 else d["short_float"]
            lines.append(f"- 空头比例（Short Float）：**{sf:.1f}%** {'⚠️ 高做空' if sf > 15 else ''}")
        if d.get("inst_own") is not None:
            io = d["inst_own"] * 100 if d["inst_own"] < 1 else d["inst_own"]
            lines.append(f"- 机构持仓比例：{io:.1f}%")
        lines.append("")

        # 7. 操盘策略建议
        lines.append(f"### 7️⃣ 操盘策略建议")

        # 短线观点
        if d["change_day"] > 1 and d["vol_ratio"] > 1.5:
            short_view = "放量上涨，短线动能较强，关注能否守住日内高点。"
        elif d["change_day"] < -2:
            short_view = "当日大幅下跌，注意逢低布局需等反弹确认信号。"
        else:
            short_view = "震荡整理，等待方向选择。"

        # 中线观点
        if d["price"] > d["ma20"] and d["price"] > d["ma60"]:
            mid_view = "中线多头结构完整，均线多头排列，持有或逢低加仓。"
        elif d["price"] < d["ma20"] and d["price"] < d["ma60"]:
            mid_view = "中线处于均线下方，空头结构，谨慎持多。"
        else:
            mid_view = "中线均线交织，方向不明，以观望为主。"

        # 关键操作位
        entry  = d["support"][1]
        target = d["resistance"][0]
        stop   = round(d["support"][0] * 0.99, 2)

        # 风险提示
        risks = []
        if d["rsi"] > 65:
            risks.append("RSI 偏高，短期回调风险")
        if d["vol_ratio"] < 0.7:
            risks.append("成交量萎缩，上涨缺乏动能")
        if d.get("short_float") and (d["short_float"] * 100 if d["short_float"] < 1 else d["short_float"]) > 15:
            risks.append("高空头比例，存在逼空或持续下压风险")
        if not risks:
            risks.append("宏观环境变化、财报超预期偏差")

        lines += [
            f"- **短线**：{short_view}",
            f"- **中线**：{mid_view}",
            f"- **关键操作位**：参考建仓 ${entry} / 目标 ${target} / 止损 ${stop}",
            f"- **风险提示**：{'；'.join(risks)}",
            "",
            "</details>\n",
        ]

    # 精选 Pick
    top_picks = [d for d in results if d["score"] >= 5]
    lines += ["---\n## ⭐ 今日精选 Pick\n"]
    if top_picks:
        for d in sorted(top_picks, key=lambda x: -x["score"]):
            lines.append(
                f"### {d['symbol']}  {d['signal']}\n"
                f"- 现价：**${d['price']}**，日涨跌 {'+' if d['change_day'] >= 0 else ''}{d['change_day']}%，"
                f"周涨跌 {'+' if d['change_week'] >= 0 else ''}{d['change_week']}%\n"
                f"- RSI：{d['rsi']} {d['rsi_status']}  |  MACD：{d['macd_status']}\n"
                f"- 布林带：{d['bb_pos']}\n"
                f"- 量比：{d['vol_ratio']}x  |  综合评分：**{d['score']}/6**\n"
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


# ── 发送邮件 ─────────────────────────────────────────────────────────────────
def send_email(subject: str, body_md: str) -> None:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    sender   = os.environ.get("EMAIL_FROM")
    password = os.environ.get("EMAIL_PASSWORD")
    receiver = os.environ.get("EMAIL_TO")

    if not all([sender, password, receiver]):
        print("⚠️  未配置邮件环境变量，直接打印报告：")
        print(body_md)
        return

    html = body_md
    html = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html)
    html = html.replace("\n", "<br>\n")
    html = f"<html><body style='font-family:monospace'>\n{html}\n</body></html>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = receiver
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(html,    "html",  "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, receiver, msg.as_string())
        print(f"✅ 邮件已发送至 {receiver}")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}", file=sys.stderr)
        sys.exit(1)


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main():
    print("🌐 正在获取宏观数据...")
    macro = fetch_macro_data()

    print("🔍 正在抓取社媒热门 Ticker（对标 TikTok FinTok）...")
    trending = get_trending_symbols(top_n=20)
    if not trending:
        print("❌ 未获取到任何热门 ticker，退出。", file=sys.stderr)
        sys.exit(1)

    print(f"\n📋 共 {len(trending)} 只候选，开始详细分析...")
    results = []
    for sym in trending:
        data = analyze(sym)
        if data:
            results.append(data)
            print(
                f"  {sym:6s}  ${data['price']}  "
                f"日{'+' if data['change_day'] >= 0 else ''}{data['change_day']}%  "
                f"RSI={data['rsi']}({data['rsi_status'].split()[0]})  "
                f"MACD={data['macd_status']}  "
                f"{data['signal']}"
            )

    if not results:
        print("❌ 所有 ticker 数据获取失败。", file=sys.stderr)
        sys.exit(1)

    results.sort(key=lambda x: -x["score"])

    report = build_report(results, trending, macro)
    now    = datetime.now(CST)
    title  = f"📈 Daily US Stock {now.strftime('%Y-%m-%d')} — TikTok FinTok 热榜精选"
    send_email(title, report)


if __name__ == "__main__":
    main()
