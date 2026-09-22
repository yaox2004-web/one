#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量化系统 AI 研判模块

功能流程:
  1. 读取本地信号胜率库 data/analysis/winrate.json
  2. 读取持仓股最新 K 线 data/kline/{code}.json
  3. 提取最新一天特征(涨跌幅 / 量能变化 / 主力意图 / 命中信号胜率)
  4. 拼接 Prompt, 调用 DeepSeek(OpenAI 兼容) 生成 100 字以内研判
  5. 结果写入 data/analysis/ai_comment_YYYYMMDD.json

依赖: pandas, requests
环境变量: DEEPSEEK_API_KEY (请自行配置, 脚本不内置任何密钥)
"""

import os
import json
import glob
import datetime

import requests
import pandas as pd


# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WINRATE_PATH = os.path.join(BASE_DIR, "data", "analysis", "winrate.json")
KLINE_DIR = os.path.join(BASE_DIR, "data", "kline")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "analysis")

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# 持仓股列表: 按需增删, 文件名对应 data/kline/{code}.json
# 可选 name 用于输出可读名称
HOLDINGS = [
    {"code": "sh600584", "name": "长电科技"},
]

# K 线字段名兼容映射(兼容英文与 akshare 中文列名)
COLUMN_ALIASES = {
    "date": ["date", "日期", "时间", "day", "trade_date", "datetime"],
    "open": ["open", "开盘", "开盘价"],
    "close": ["close", "收盘", "收盘价"],
    "high": ["high", "最高", "最高价"],
    "low": ["low", "最低", "最低价"],
    "volume": ["volume", "vol", "成交量", "量", "amount_vol"],
    "pct_change": ["pct_change", "pct_chg", "涨跌幅", "change_pct", "pct"],
    "intent": ["intent", "main_intent", "主力意图", "zhuli", "main"],
}

# winrate.json 字段关键词, 用于递归定位标签与胜率
POSITION_KEYS = ("position", "位置", "loc", "level")
TREND_KEYS = ("trend", "趋势", "direction")
SIGNAL_KEYS = ("signal", "信号", "pattern", "形态", "name", "名称", "type")
WINRATE_KEYS = ("winrate", "win_rate", "胜率", "winratio", "rate")


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _to_float(value):
    """把数字或 '52%' / '0.52' 之类的字符串统一转成 float(百分数按 0-100 保留)。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    is_percent = text.endswith("%")
    text = text.rstrip("%")
    try:
        num = float(text)
    except ValueError:
        return None
    # 百分比字符串保持原数量级, 小数形式(<=1)自动放大到百分数
    if is_percent:
        return num
    if 0 < num <= 1:
        return round(num * 100, 2)
    return num


def _find_column(df, aliases):
    """在 DataFrame 中按别名(大小写不敏感)找到真实列名。"""
    lowered = {str(c).lower(): c for c in df.columns}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------

def load_winrate(path):
    """读取胜率库, 返回扁平化的信号条目列表 [{位置, 趋势, 信号, 胜率}, ...]。"""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return _flatten_winrate(raw)


def _flatten_winrate(node, ctx=None, acc=None):
    """递归遍历胜率 JSON, 把带胜率的节点抽成统一结构。"""
    if ctx is None:
        ctx = {}
    if acc is None:
        acc = []

    if isinstance(node, dict):
        local = dict(ctx)
        rate = None

        for key, value in node.items():
            lk = str(key).lower()
            if isinstance(value, (str, int, float)):
                if any(t in lk for t in POSITION_KEYS):
                    local["位置"] = str(value)
                elif any(t in lk for t in TREND_KEYS):
                    local["趋势"] = str(value)
                elif any(t in lk for t in SIGNAL_KEYS):
                    local["信号"] = str(value)
            if any(t in lk for t in WINRATE_KEYS):
                rate = _to_float(value)

        if rate is not None:
            entry = dict(local)
            entry["胜率"] = rate
            acc.append(entry)

        for value in node.values():
            if isinstance(value, (dict, list)):
                _flatten_winrate(value, local, acc)

    elif isinstance(node, list):
        for item in node:
            _flatten_winrate(item, ctx, acc)

    return acc


def load_kline(path):
    """读取单只股票 K 线, 归一化列名并按日期升序返回 DataFrame。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    records = raw
    if isinstance(raw, dict):
        for key in ("data", "klines", "kline", "list", "items", "records", "result"):
            if key in raw and isinstance(raw[key], list):
                records = raw[key]
                break

    if not records:
        return pd.DataFrame()

    # 兼容二维数组格式, 常见顺序: [日期, 开盘, 收盘, 最高, 最低, 成交量]
    if isinstance(records[0], (list, tuple)):
        width = len(records[0])
        names = ["date", "open", "close", "high", "low", "volume"][:width]
        df = pd.DataFrame(records, columns=names)
    else:
        df = pd.DataFrame(records)

    df = df.rename(columns={c: str(c).strip() for c in df.columns})

    rename_map = {}
    for standard, aliases in COLUMN_ALIASES.items():
        col = _find_column(df, aliases)
        if col is not None and col != standard:
            rename_map[col] = standard
    df = df.rename(columns=rename_map)

    if "date" in df.columns:
        df["date"] = df["date"].astype(str)
        df = df.sort_values("date").reset_index(drop=True)

    for col in ("open", "close", "high", "low", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# ---------------------------------------------------------------------------
# 特征提取
# ---------------------------------------------------------------------------

def extract_features(df):
    """从 K 线中提取最新一天的关键特征。"""
    if df.empty or "close" not in df.columns:
        return None

    df = df.dropna(subset=["close"]).reset_index(drop=True)
    if df.empty:
        return None

    latest = df.iloc[-1]
    close = float(latest["close"])

    # 涨跌幅: 优先用数据自带字段, 否则用前后收盘价计算
    pct_change = None
    if "pct_change" in df.columns:
        pct_change = _to_float(latest.get("pct_change"))
    if pct_change is None and len(df) >= 2:
        prev_close = float(df.iloc[-2]["close"])
        if prev_close:
            pct_change = round((close - prev_close) / prev_close * 100, 2)

    # 量能变化: 相对前一日
    vol_ratio = None
    vol_state = "未知"
    if "volume" in df.columns and len(df) >= 2:
        last_vol = _to_float(latest.get("volume"))
        prev_vol = _to_float(df.iloc[-2].get("volume"))
        if last_vol and prev_vol:
            vol_ratio = round(last_vol / prev_vol, 2)
            if vol_ratio >= 2:
                vol_state = "倍量"
            elif vol_ratio <= 0.5:
                vol_state = "缩量"
            else:
                vol_state = "平量"

    # 主力意图: 若数据中存在对应字段则直接取用
    intent = None
    if "intent" in df.columns:
        value = latest.get("intent")
        if value is not None and str(value).strip() not in ("", "nan", "None"):
            intent = str(value).strip()

    # 趋势判断: 收盘价与 MA5 / MA20 的关系
    trend = "未知"
    if len(df) >= 20:
        ma5 = df["close"].rolling(5).mean().iloc[-1]
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        if close > ma5 > ma20:
            trend = "上升"
        elif close < ma5 < ma20:
            trend = "下降"
        else:
            trend = "震荡"

    # 位置判断: 近 60 日区间相对位置
    position = "未知"
    window = df.tail(60)
    if len(window) >= 20 and "high" in df.columns and "low" in df.columns:
        high = float(pd.to_numeric(window["high"], errors="coerce").max())
        low = float(pd.to_numeric(window["low"], errors="coerce").min())
        if high > low:
            ratio = (close - low) / (high - low)
            if ratio >= 0.7:
                position = "高位"
            elif ratio <= 0.3:
                position = "低位"
            else:
                position = "中位"

    return {
        "date": str(latest.get("date", "")),
        "close": round(close, 2),
        "pct_change": pct_change,
        "vol_ratio": vol_ratio,
        "vol_state": vol_state,
        "intent": intent,
        "trend": trend,
        "position": position,
    }


def match_winrate(entries, position, trend):
    """按位置 + 趋势匹配历史胜率, 返回 (平均胜率, 命中信号名列表)。"""
    if not entries:
        return None, []

    matched = []
    for entry in entries:
        entry_pos = str(entry.get("位置", ""))
        entry_trend = str(entry.get("趋势", ""))

        # 位置/趋势任一维度存在时必须匹配, 为空视为通配
        if entry_pos and position != "未知" and entry_pos not in position:
            continue
        if entry_trend and trend != "未知" and entry_trend not in trend:
            continue
        matched.append(entry)

    if not matched:
        return None, []

    rates = [e["胜率"] for e in matched if e.get("胜率") is not None]
    if not rates:
        return None, []

    signals = []
    for entry in matched:
        name = entry.get("信号")
        if name and name not in signals:
            signals.append(name)

    return round(sum(rates) / len(rates), 2), signals


# ---------------------------------------------------------------------------
# Prompt 与大模型调用
# ---------------------------------------------------------------------------

def build_prompt(stock, feature, winrate, signals):
    """把特征拼成一段清晰的中文 Prompt。"""
    lines = [
        f"请对持仓个股 {stock.get('name', '')}({stock['code']}) 做客观研判。",
        "",
        "【最新交易日特征】",
        f"- 日期: {feature['date']}",
        f"- 最新收盘价: {feature['close']}",
        f"- 当日涨跌幅: {feature['pct_change'] if feature['pct_change'] is not None else '未知'}%",
        f"- 量能变化: {feature['vol_state']}",
    ]
    if feature["vol_ratio"] is not None:
        lines.append(f"- 相对昨日成交量倍数: {feature['vol_ratio']}")
    lines.append(f"- 当前趋势: {feature['trend']}")
    lines.append(f"- 当前价格位置: {feature['position']}")
    lines.append(f"- 主力意图: {feature['intent'] or '数据缺失'}")

    if winrate is not None:
        signal_text = "、".join(signals) if signals else "综合信号"
        lines.append(f"- 命中信号: {signal_text}, 历史同类胜率约 {winrate}%")
    else:
        lines.append("- 命中信号: 暂无匹配的胜率数据")

    lines += [
        "",
        "请给出 100 字以内的客观研判, 包含当前多空状态、量价关系与后续关注要点。",
        "要求语言精炼、不夸大、不做绝对涨跌承诺, 直接输出研判正文。",
    ]
    return "\n".join(lines)


def call_deepseek(prompt):
    """调用 DeepSeek(OpenAI 兼容) 接口, 返回研判文本。"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("未设置环境变量 DEEPSEEK_API_KEY, 无法调用大模型")

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一名严谨的量化投研助手, 输出客观、克制、可读的技术研判。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 300,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    today = datetime.date.today().strftime("%Y%m%d")

    entries = load_winrate(WINRATE_PATH)
    print(f"[AI研判] 信号胜率条目: {len(entries)}")

    results = {}
    for stock in HOLDINGS:
        code = stock["code"]
        print(f"[AI研判] 处理 {code} ...")

        kline_path = os.path.join(KLINE_DIR, f"{code}.json")
        if not os.path.exists(kline_path):
            results[code] = {"error": f"未找到 K 线文件: {kline_path}"}
            continue

        try:
            df = load_kline(kline_path)
            feature = extract_features(df)
            if feature is None:
                results[code] = {"error": "K 线数据为空或缺少收盘价字段"}
                continue

            winrate, signals = match_winrate(entries, feature["position"], feature["trend"])
            prompt = build_prompt(stock, feature, winrate, signals)
            comment = call_deepseek(prompt)

            results[code] = {
                "name": stock.get("name", ""),
                "feature": feature,
                "matched_winrate": winrate,
                "matched_signals": signals,
                "ai_comment": comment,
            }
            print(f"[AI研判] {code} 完成")

        except Exception as exc:  # 单只股票失败不影响整体输出
            results[code] = {"error": str(exc)}
            print(f"[AI研判] {code} 失败: {exc}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"ai_comment_{today}.json")
    payload = {
        "date": today,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": DEEPSEEK_MODEL,
        "stocks": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[AI研判] 结果已保存: {output_path}")


if __name__ == "__main__":
    main()
