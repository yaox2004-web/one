#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_one_stock.py — 单股轻量分析（纯计算，不调用 AI）
用法: python3 analyze_one_stock.py sh600584
      python3 analyze_one_stock.py 长电科技
      python3 analyze_one_stock.py sh600584 --json
输出: Markdown 报告（stdout），加 --json 参数时只输出结构化数据
"""

import json
import os
import sys
import glob
from datetime import datetime

# ========== 路径配置 ==========
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE_DIR, "data", "kline")
WINRATE_PATH = os.path.join(BASE_DIR, "data", "analysis", "winrate.json")
LEDGER_DIR = os.path.join(BASE_DIR, "data", "analysis", "truth_ledger")

# 股票名称 → 代码映射（可自行扩展）
NAME_MAP = {
    "长电科技": "sh600584",
    "通富微电": "sz002156",
    "工业富联": "sh601138",
    "胜宏科技": "sz300476",
    "立讯精密": "sz002475",
    "中芯国际": "sh688981",
    "北方华创": "sz002371",
    "韦尔股份": "sh603501",
    "上证指数": "sh000001",
}


# ========== 基础工具 ==========
def load_kline(code):
    """
    加载单只股票日线数据。
    路径: data/kline/{市场}/{代码}.json
    格式: {"name": "...", "klines": [[日期,开,收,高,低,量], ...]}
    返回: (rows, name) 或 (None, None)
    """
    market = code[:2]
    path = os.path.join(KLINE_DIR, market, f"{code}.json")
    if not os.path.exists(path):
        return None, None

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    stock_name = data.get("name", "")
    klines = data.get("klines", [])
    if not klines:
        return None, stock_name

    rows = []
    for item in klines:
        if len(item) < 6:
            continue
        try:
            date = str(item[0])
            open_p = float(item[1])
            close_p = float(item[2])
            high_p = float(item[3])
            low_p = float(item[4])
            vol = float(item[5])
            if close_p <= 0:
                continue
            rows.append({
                "date": date,
                "open": open_p,
                "close": close_p,
                "high": high_p,
                "low": low_p,
                "volume": vol,
            })
        except (ValueError, TypeError):
            continue

    if not rows:
        return None, stock_name

    rows.sort(key=lambda r: r["date"])
    return rows, stock_name


def resolve_code(user_input):
    """把用户输入解析成代码"""
    s = user_input.strip().lower()
    if s in NAME_MAP:
        return NAME_MAP[s]
    if s.startswith(("sh", "sz", "bj")) and len(s) == 8:
        return s
    if s.isdigit() and len(s) == 6:
        if s.startswith(("6", "9")):
            return "sh" + s
        elif s.startswith(("0", "2", "3")):
            return "sz" + s
        elif s.startswith(("4", "8")):
            return "bj" + s
    return None


# ========== 技术指标（纯标准库） ==========
def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def atr(highs, lows, closes, n=14):
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-n:]) / n


def classify_volume(vol, vol_ma5):
    if not vol_ma5 or vol_ma5 <= 0:
        return "数据不足"
    ratio = vol / vol_ma5
    if ratio >= 2.0:
        return f"倍量柱（{ratio:.1f}倍）"
    if ratio >= 1.5:
        return f"放量柱（{ratio:.1f}倍）"
    if ratio <= 0.5:
        return f"缩量柱（{ratio:.1f}倍）"
    if ratio <= 0.8:
        return f"温和缩量（{ratio:.1f}倍）"
    return f"平量柱（{ratio:.1f}倍）"


def classify_position(close, highs, lows, window=120):
    n = min(window, len(highs), len(lows))
    if n < 20:
        return "数据不足", None, None
    h = max(highs[-n:])
    l = min(lows[-n:])
    if h <= l:
        return "数据异常", h, l
    pct = (close - l) / (h - l) * 100
    if pct < 30:
        pos = "低位"
    elif pct < 70:
        pos = "中位"
    else:
        pos = "高位"
    return pos, h, l


def classify_trend(closes, ma_period=20):
    ma = sma(closes, ma_period)
    if ma is None:
        return "数据不足", None
    if closes[-1] > ma * 1.02:
        return "上升", ma
    if closes[-1] < ma * 0.98:
        return "下降", ma
    return "震荡", ma


def infer_intent(vol_desc, pos, trend):
    is_big = "倍量" in vol_desc or "放量" in vol_desc
    is_shrink = "缩量" in vol_desc
    if pos == "低位" and is_big and trend in ("上升", "震荡"):
        return "建仓/试盘"
    if pos == "低位" and is_shrink:
        return "洗盘/吸筹"
    if pos == "中位" and is_big and trend == "上升":
        return "拉升"
    if pos == "高位" and is_big:
        return "出货/派发"
    if pos == "高位" and is_shrink and trend == "下降":
        return "出货确认"
    return "信号不明确"


def check_ledger(code):
    """
    查账本。格式: {股票代码: {日期: {特征}}}
    返回: {"date": "2026-09-22", "is_real": true, ...} 或 None
    """
    if not os.path.isdir(LEDGER_DIR):
        return None
    latest_date = None
    latest_feat = None
    files = sorted(glob.glob(os.path.join(LEDGER_DIR, "*.json")))
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                ledger = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(ledger, dict):
            continue
        stock_data = ledger.get(code)
        if not isinstance(stock_data, dict):
            continue
        for date_str, feat in stock_data.items():
            if not isinstance(feat, dict):
                continue
            if latest_date is None or date_str > latest_date:
                latest_date = date_str
                latest_feat = feat
    if latest_date is None:
        return None
    result = {"date": latest_date}
    result.update(latest_feat)
    return result


def load_winrate():
    if not os.path.exists(WINRATE_PATH):
        return None
    try:
        with open(WINRATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def lookup_winrate(winrate, pos, trend, vol_desc):
    if not winrate:
        return []
    results = []
    keys_to_try = [
        f"{pos}_{trend}",
        f"{pos}",
        f"{trend}",
        "倍量柱" if "倍量" in vol_desc else None,
        "缩量柱" if "缩量" in vol_desc else None,
    ]
    keys_to_try = [k for k in keys_to_try if k]

    def search(obj, depth=0):
        if depth > 4:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys_to_try and isinstance(v, (int, float)):
                    results.append((k, v))
                elif isinstance(v, (dict, list)):
                    search(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                search(item, depth + 1)

    search(winrate)
    return results[:5]


# ========== AI 研判数据区 ==========
def build_pending_data(code, name, rows, vol_desc, pos, trend, intent,
                       support, resistance, ledger, matched_winrate, chg):
    """构建供 OpenMinis Agent 拿去调 AI 的结构化数据"""
    last = rows[-1]
    pending = {
        "stock_code": code,
        "stock_name": name,
        "date": last["date"],
        "close": round(last["close"], 2),
        "change_pct": round(chg, 2),
        "volume_desc": vol_desc,
        "position": pos,
        "trend": trend,
        "intent_inferred": intent,
        "support": round(support, 2) if support else None,
        "resistance": round(resistance, 2) if resistance else None,
        "ledger": None,
        "winrate_hits": [],
    }
    if ledger:
        pending["ledger"] = {
            "verdict": ledger.get("verdict"),
            "is_real": ledger.get("is_real"),
            "cv": ledger.get("cv"),
            "corr": ledger.get("corr"),
            "tail_ratio": ledger.get("tail_ratio"),
        }
    for k, v in matched_winrate:
        pending["winrate_hits"].append({"key": k, "value": v})
    return pending


# ========== 报告生成 ==========
def build_report(code, name, rows):
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    vols = [r["volume"] for r in rows]
    dates = [r["date"] for r in rows]

    last = rows[-1]
    close = last["close"]
    prev_close = closes[-2] if len(closes) >= 2 else close
    chg = (close - prev_close) / prev_close * 100 if prev_close else 0.0

    vol_ma5 = sma(vols, 5)
    vol_desc = classify_volume(last["volume"], vol_ma5)

    pos, range_high, range_low = classify_position(close, highs, lows)
    trend, ma20 = classify_trend(closes)
    atr_val = atr(highs, lows, closes, 14)

    intent = infer_intent(vol_desc, pos, trend)

    n = min(60, len(lows))
    support = min(lows[-n:]) if n > 0 else None
    resistance = max(highs[-n:]) if n > 0 else None

    ledger = check_ledger(code)
    winrate = load_winrate()
    matched_winrate = lookup_winrate(winrate, pos, trend, vol_desc)

    lines = []
    lines.append(f"# {name}（{code}）单股分析")
    lines.append("")
    lines.append(f"> 数据截止：{dates[-1]} | 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## 一、行情快照")
    lines.append("")
    lines.append("| 项目 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 最新价 | {close:.2f} |")
    lines.append(f"| 涨跌幅 | {chg:+.2f}% |")
    lines.append(f"| 成交量 | {last['volume']:.0f} |")
    lines.append(f"| 5日均量 | {vol_ma5:.0f} |" if vol_ma5 else "| 5日均量 | 数据不足 |")
    lines.append(f"| ATR(14) | {atr_val:.2f} |" if atr_val else "| ATR(14) | 数据不足 |")
    lines.append("")
    lines.append("## 二、量柱与位置")
    lines.append("")
    lines.append(f"- **量柱形态**：{vol_desc}")
    lines.append(f"- **位置**：{pos}" + (f"（区间 {range_low:.2f} ~ {range_high:.2f}）" if range_low and range_high else ""))
    lines.append(f"- **趋势**：{trend}" + (f"（MA20 = {ma20:.2f}）" if ma20 else ""))
    lines.append(f"- **主力意图推断**：{intent}")
    lines.append("")
    lines.append("## 三、关键位")
    lines.append("")
    lines.append(f"- 支撑位（近60日最低）：{support:.2f}" if support else "- 支撑位：数据不足")
    lines.append(f"- 压力位（近60日最高）：{resistance:.2f}" if resistance else "- 压力位：数据不足")
    lines.append("")
    lines.append("## 四、账本判定")
    lines.append("")
    if ledger:
        lines.append(f"- 最近记录日期：{ledger.get('date', 'N/A')}")
        if "verdict" in ledger:
            lines.append(f"- 判定：**{ledger['verdict']}**")
        if "is_real" in ledger:
            lines.append(f"- 是否真金白银：{ledger['is_real']}")
        if "quant_pct" in ledger:
            lines.append(f"- 量化占比：{ledger['quant_pct']}%")
        if "cv" in ledger:
            lines.append(f"- CV：{ledger['cv']}")
        if "corr" in ledger:
            lines.append(f"- 量价相关：{ledger['corr']}")
        if "tail_ratio" in ledger:
            lines.append(f"- 尾盘占比：{ledger['tail_ratio']}")
    else:
        lines.append("- 账本中暂无该股记录")
    lines.append("")
    lines.append("## 五、胜率参考")
    lines.append("")
    if matched_winrate:
        for k, v in matched_winrate:
            lines.append(f"- {k}：{v:.1%}" if isinstance(v, float) and v <= 1 else f"- {k}：{v}")
    else:
        lines.append("- 未匹配到对应维度的胜率数据")
    lines.append("")

    # 待研判数据区
    pending = build_pending_data(
        code, name, rows, vol_desc, pos, trend, intent,
        support, resistance, ledger, matched_winrate, chg
    )
    lines.append("<!-- PENDING_AI_DATA_START -->")
    lines.append("```json")
    lines.append(json.dumps(pending, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("<!-- PENDING_AI_DATA_END -->")
    lines.append("")
    lines.append("---")
    lines.append("*本报告由 analyze_one_stock.py 纯本地计算生成。AI 研判请由 Agent 调用大模型生成。*")
    return "\n".join(lines)


# ========== 主入口 ==========
def main():
    args = sys.argv[1:]
    json_mode = "--json" in args
    if json_mode:
        args = [a for a in args if a != "--json"]

    if not args:
        print("用法: python3 analyze_one_stock.py <股票代码或名称>")
        print("      python3 analyze_one_stock.py sh600584 --json")
        sys.exit(1)

    user_input = args[0].strip()
    code = resolve_code(user_input)
    if not code:
        print(f"无法解析输入：{user_input}")
        sys.exit(1)

    rows, stock_name = load_kline(code)
    if not rows:
        print(f"未找到 {code} 的日线数据。")
        sys.exit(1)

    if len(rows) < 20:
        print(f"{code} 数据不足 20 根，无法分析。")
        sys.exit(1)

    name = stock_name
    if not name:
        for k, v in NAME_MAP.items():
            if v == code:
                name = k
                break
    if not name:
        name = code

    if json_mode:
        # 只输出结构化数据，供 Agent 调 AI 用
        closes = [r["close"] for r in rows]
        highs = [r["high"] for r in rows]
        lows = [r["low"] for r in rows]
        vols = [r["volume"] for r in rows]
        last = rows[-1]
        close = last["close"]
        prev_close = closes[-2] if len(closes) >= 2 else close
        chg = (close - prev_close) / prev_close * 100 if prev_close else 0.0
        vol_ma5 = sma(vols, 5)
        vol_desc = classify_volume(last["volume"], vol_ma5)
        pos, range_high, range_low = classify_position(close, highs, lows)
        trend, ma20 = classify_trend(closes)
        intent = infer_intent(vol_desc, pos, trend)
        n = min(60, len(lows))
        support = min(lows[-n:]) if n > 0 else None
        resistance = max(highs[-n:]) if n > 0 else None
        ledger = check_ledger(code)
        winrate = load_winrate()
        matched_winrate = lookup_winrate(winrate, pos, trend, vol_desc)
        pending = build_pending_data(
            code, name, rows, vol_desc, pos, trend, intent,
            support, resistance, ledger, matched_winrate, chg
        )
        print(json.dumps(pending, ensure_ascii=False, indent=2))
    else:
        print(build_report(code, name, rows))


if __name__ == "__main__":
    main()
