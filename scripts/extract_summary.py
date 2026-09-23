#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_summary.py - 股票数据摘要生成器
=================================================
版本: v1.0 (2026-09-23)
用法:
  python3 extract_summary.py sz300476
  python3 extract_summary.py sh601138
  python3 extract_summary.py sh603516
  python3 extract_summary.py all        # 分析重点3只

输出: 300字以内的人话版摘要，供AI分析
"""

import os
import sys
import json
from pathlib import Path

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent.parent
KLINE_DIR = BASE_DIR / "data" / "kline"
WINRATE_PATH = BASE_DIR / "data" / "analysis" / "winrate.json"
LEDGER_DIR = BASE_DIR / "data" / "analysis" / "truth_ledger"

# 重点关注的三只股票
FOCUS_STOCKS = [
    ("sz", "300476", "胜宏科技"),
    ("sh", "601138", "工业富联"),
    ("sh", "603516", "淳中科技"),
]


# ============================================================
# 数据读取
# ============================================================
def load_kline(market, code):
    """读取日线数据"""
    path = KLINE_DIR / market / f"{market}{code}.json"
    if not path.exists():
        path = KLINE_DIR / f"{market}{code}.json"
        if not path.exists():
            return None, None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        klines = data.get('klines', [])
        if len(klines) < 2:
            return None, None
        return klines, data.get('name', code)
    except Exception:
        return None, None


def load_winrate():
    """加载胜率数据"""
    if not WINRATE_PATH.exists():
        return {}
    try:
        with open(WINRATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def load_ledger():
    """加载账本（合并所有月份）"""
    ledger = {}
    if not LEDGER_DIR.exists():
        return ledger
    for f in sorted(LEDGER_DIR.glob("*.json")):
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                monthly = json.load(fp)
            for code, dates in monthly.items():
                if code not in ledger:
                    ledger[code] = {}
                ledger[code].update(dates)
        except Exception:
            continue
    return ledger


# ============================================================
# 特征提取
# ============================================================
def extract_features(klines):
    """提取最新一天特征"""
    today = klines[-1]
    yesterday = klines[-2]

    date_str = today[0]
    close = float(today[2])
    open_p = float(today[1])
    high = float(today[3])
    low = float(today[4])
    vol = float(today[5])
    prev_close = float(yesterday[2])
    prev_vol = float(yesterday[5])

    pct_chg = (close - prev_close) / prev_close * 100 if prev_close else 0
    vol_ratio = vol / prev_vol if prev_vol else 0
    amplitude = (high - low) / prev_close * 100 if prev_close else 0

    # 量能形态
    if pct_chg > 0 and vol_ratio >= 1.8:
        vol_state = "倍量柱（放量上涨）"
    elif pct_chg > 0 and vol_ratio <= 0.8:
        vol_state = "缩量柱（缩量上涨）"
    elif pct_chg < 0 and vol_ratio >= 1.8:
        vol_state = "放量下跌"
    elif pct_chg < 0 and vol_ratio <= 0.8:
        vol_state = "缩量下跌"
    else:
        vol_state = "平量柱"

    # 趋势（近20日均线）
    closes_20 = [float(k[2]) for k in klines[-20:]]
    ma20 = sum(closes_20) / len(closes_20) if closes_20 else close
    trend = "上升趋势" if close > ma20 else "下降趋势"

    # 位置（近120日）
    pos_pct = 50
    if len(klines) >= 120:
        recent = klines[-120:]
        closes_120 = [float(k[2]) for k in recent]
        lows_120 = [float(k[4]) for k in recent]
        highs_120 = [float(k[3]) for k in recent]
        lo = min(lows_120)
        hi = max(highs_120)
        pos_pct = (close - lo) / (hi - lo) * 100 if hi > lo else 50

    if pos_pct < 30:
        position = "低位"
    elif pos_pct > 70:
        position = "高位"
    else:
        position = "中位"

    # 20日高低点
    recent_20 = klines[-20:]
    high_20 = max(float(k[3]) for k in recent_20)
    low_20 = min(float(k[4]) for k in recent_20)

    return {
        "date": date_str,
        "close": round(close, 2),
        "open": round(open_p, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "pct_chg": round(pct_chg, 2),
        "amplitude": round(amplitude, 2),
        "vol_ratio": round(vol_ratio, 2),
        "vol_state": vol_state,
        "trend": trend,
        "ma20": round(ma20, 2),
        "position": position,
        "position_pct": round(pos_pct, 1),
        "high_20": round(high_20, 2),
        "low_20": round(low_20, 2),
    }


def get_top_signals(winrate_data, position, trend, top_n=5):
    """取该位置+趋势下的TOP信号胜率"""
    pos_data = winrate_data.get(position, {})
    trend_data = pos_data.get(trend, {})
    if not trend_data:
        return []

    signals = []
    for sig_name, val in trend_data.items():
        if isinstance(val, dict):
            wr = val.get("win_rate", 0)
            avg = val.get("avg_ret", 0)
            if wr > 0:
                signals.append((sig_name, wr, avg))

    signals.sort(key=lambda x: x[1], reverse=True)
    return signals[:top_n]


def get_ledger_info(ledger, market, code, date_str):
    """从账本取当天真假标签"""
    key = f"{market}{code}"
    if key in ledger and date_str in ledger[key]:
        return ledger[key][date_str]
    return None


# ============================================================
# 摘要生成
# ============================================================
def generate_summary(market, code, name, winrate_data, ledger):
    """生成单只股票摘要"""
    klines, real_name = load_kline(market, code)
    if not klines:
        return f"❌ 未找到 {market}{code} 的数据"

    feat = extract_features(klines)
    signals = get_top_signals(winrate_data, feat['position'], feat['trend'], 5)
    ledger_info = get_ledger_info(ledger, market, code, feat['date'])

    lines = []
    lines.append(f"【{real_name} {market}{code}】")
    lines.append(f"日期: {feat['date']}")
    lines.append(f"收盘: {feat['close']}元 ({feat['pct_chg']:+.2f}%)")
    lines.append(f"开盘: {feat['open']} 最高: {feat['high']} 最低: {feat['low']} 振幅: {feat['amplitude']}%")
    lines.append(f"量能: {feat['vol_state']}（量比{feat['vol_ratio']}）")
    lines.append(f"趋势: {feat['trend']}（MA20={feat['ma20']}）")
    lines.append(f"位置: {feat['position']}（{feat['position_pct']}%分位）")
    lines.append(f"20日区间: {feat['low_20']} ~ {feat['high_20']}")

    if ledger_info:
        verdict = ledger_info.get('verdict', '未知')
        quant = ledger_info.get('quant_pct', 0)
        lines.append(f"真假判定: {verdict}（量化{quant}%）")
    else:
        lines.append(f"真假判定: 账本无记录（默认真金白银）")

    lines.append(f"\n历史同位置({feat['position']})同趋势({feat['trend']})的TOP5信号胜率:")
    if signals:
        for sig, wr, avg in signals:
            lines.append(f"  - {sig}: 胜率{wr}%, 平均收益{avg}%")
    else:
        lines.append(f"  - 暂无匹配数据")

    return "\n".join(lines)


# ============================================================
# 主函数
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 extract_summary.py sz300476    # 胜宏科技")
        print("  python3 extract_summary.py sh601138    # 工业富联")
        print("  python3 extract_summary.py sh603516    # 淳中科技")
        print("  python3 extract_summary.py all         # 分析重点3只")
        return

    arg = sys.argv[1].lower()
    winrate_data = load_winrate()
    ledger = load_ledger()

    print(f"✅ 已加载胜率数据: {len(winrate_data)} 个位置")
    print(f"✅ 已加载账本数据: {len(ledger)} 只股票")
    print()

    if arg == 'all':
        for market, code, name in FOCUS_STOCKS:
            summary = generate_summary(market, code, name, winrate_data, ledger)
            print("=" * 60)
            print(summary)
            print()
    else:
        if arg.startswith(('sh', 'sz')):
            market = arg[:2]
            code = arg[2:]
        else:
            market = 'sh' if arg.startswith('6') else 'sz'
            code = arg

        name = code
        for m, c, n in FOCUS_STOCKS:
            if c == code:
                name = n
                break

        summary = generate_summary(market, code, name, winrate_data, ledger)
        print("=" * 60)
        print(summary)
        print("=" * 60)


if __name__ == '__main__':
    main()
