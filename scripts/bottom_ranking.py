#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
波段抄底新规则验证 (bottom_ranking.py) v1
=================================================================
4个新抄底信号，全市场5220只回测：
  1. RSI底背离（股价新低但RSI不新低+放量阳）
  2. 缩量极致+阳盖阴（量<20日均量50%+次日阳盖阴）
  3. 布林带下轨反弹（触下轨+RSI<30+放量阳）
  4. OBV底背离（股价新低但OBV不新低）
T+1+成本1.1%+MA20过滤+持有5日
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_fetcher import ANALYSIS_DIR, KLINE_DIR, load_kline_json  # noqa: E402

OUT_DIR = ANALYSIS_DIR
RAW_PATH = os.path.join(OUT_DIR, "bottom_ranking_raw.jsonl")
ALL_RAW = os.path.join(OUT_DIR, "signal_ranking_all_raw.jsonl")
COST = 1.1
HOLD = 5
FLUSH_EVERY = 200
LOG_EVERY = 50


def load_all_codes():
    codes = set()
    if not os.path.exists(ALL_RAW):
        return []
    with open(ALL_RAW, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("code"):
                    codes.add(obj["code"])
            except Exception:
                continue
    return sorted(codes)


def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi


def calc_boll(close, period=20, num_std=2):
    ma = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    return upper, ma, lower


def calc_obv(close, vol):
    direction = np.sign(close.diff().fillna(0))
    return (direction * vol).cumsum()


def detect_new_low(series, window=60):
    """当日是否创window日新低"""
    return series <= series.rolling(window, min_periods=window).min()


def detect_divergence(price_series, indicator_series, lookback=60, bars_back=30):
    """
    底背离：价格创lookback日新低，但指标没有创lookback日新低
    简化版：找最近两个价格低点，如果价格创新低但指标低点更高=背离
    """
    n = len(price_series)
    result = np.zeros(n, dtype=bool)
    price = price_series.values
    ind = indicator_series.values

    for i in range(lookback + bars_back, n):
        # 最近bars_back天内的最低点
        recent_price = price[i - bars_back:i + 1]
        prev_price = price[i - bars_back - lookback:i - bars_back + 1]
        if len(prev_price) < 10:
            continue
        recent_min = np.nanmin(recent_price)
        prev_min = np.nanmin(prev_price)
        # 价格创新低
        if recent_min >= prev_min * 0.995:
            continue
        # 找价格最低点对应的指标值
        recent_idx = np.argmin(recent_price)
        prev_idx = np.argmin(prev_price)
        # 指标没有创新低
        recent_ind = ind[i - bars_back + recent_idx]
        prev_ind = ind[i - bars_back - lookback + prev_idx]
        if np.isnan(recent_ind) or np.isnan(prev_ind):
            continue
        if recent_ind > prev_ind:
            result[i] = True
    return pd.Series(result, index=price_series.index)


def analyze_one(code, idx_above_map):
    df = load_kline_json(code)
    if df.empty or len(df) < 100:
        return {}
    df = df.copy()
    df["日期"] = pd.to_datetime(df["日期"])
    for c in ["开盘", "收盘", "最高", "最低", "成交量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    close = df["收盘"]
    vol = df["成交量"]
    open_ = df["开盘"]
    high = df["最高"]
    low = df["最低"]

    # RSI(14)
    rsi = calc_rsi(close, 14)
    # 布林带(20,2)
    boll_up, boll_mid, boll_low = calc_boll(close, 20, 2)
    # OBV
    obv = calc_obv(close, vol)
    # 量5均
    vol5 = vol.rolling(5, min_periods=1).mean()
    vol20 = vol.rolling(20, min_periods=1).mean()

    # 信号1：RSI底背离（背离+次日放量阳）
    rsi_div = detect_divergence(close, rsi, 60, 30)
    next_vol_up = vol.shift(-1) > vol5.shift(-1) * 1.5
    next_yang = close.shift(-1) > open_.shift(-1)
    sig_rsi = rsi_div & next_vol_up & next_yang

    # 信号2：缩量极致+阳盖阴（今日量<20均量50%，且在MA20附近，次日阳盖阴）
    ma20 = close.rolling(20, min_periods=1).mean()
    vol_extreme = vol < vol20 * 0.5
    near_ma20 = (close >= ma20 * 0.97) & (close <= ma20 * 1.03)
    next_yang_gai = (close.shift(-1) > open_.shift(-1)) & \
                    (close.shift(-1) > close.shift(-2)) & \
                    (close.shift(-1) > open_.shift(-2))
    sig_vol_extreme = vol_extreme & near_ma20 & next_yang_gai

    # 信号3：布林带下轨反弹（触下轨+RSI<30+次日放量阳）
    touch_lower = close <= boll_low * 1.005
    rsi_oversold = rsi < 30
    next_vol_up2 = vol.shift(-1) > vol5.shift(-1) * 1.3
    next_yang2 = close.shift(-1) > open_.shift(-1)
    sig_boll = touch_lower & rsi_oversold & next_vol_up2 & next_yang2

    # 信号4：OBV底背离
    obv_div = detect_divergence(close, obv, 60, 30)
    next_vol_up3 = vol.shift(-1) > vol5.shift(-1) * 1.3
    next_yang3 = close.shift(-1) > open_.shift(-1)
    sig_obv = obv_div & next_vol_up3 & next_yang3

    # 计算前向收益（T+1）
    results = {}
    signals = {
        "RSI底背离": sig_rsi,
        "缩量极致阳盖": sig_vol_extreme,
        "布林下轨反弹": sig_boll,
        "OBV底背离": sig_obv,
    }

    for name, sig in signals.items():
        sig = sig.fillna(False).to_numpy()
        rets = []
        for i in range(20, len(df) - HOLD - 1):
            if not sig[i]:
                continue
            date_str = df["日期"].iloc[i].strftime("%Y-%m-%d")
            if not idx_above_map.get(date_str, True):
                continue
            buy_idx = i + 1
            sell_idx = i + HOLD
            if sell_idx >= len(close):
                continue
            buy_p = close.iloc[buy_idx]
            sell_p = close.iloc[sell_idx]
            if buy_p <= 0:
                continue
            r = (sell_p / buy_p - 1.0) * 100 - COST
            rets.append(r)
        results[name] = rets

    return results


def load_raw():
    all_results = {}
    done = set()
    if not os.path.exists(RAW_PATH):
        return all_results, done
    with open(RAW_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            code = obj.get("code")
            if not code:
                continue
            done.add(code)
            for k, v in obj.get("results", {}).items():
                all_results.setdefault(k, []).extend(v)
    return all_results, done


def summarize(all_results):
    rows = []
    for name, rets in sorted(all_results.items()):
        if not rets:
            rows.append({"信号名": name, "触发次数": 0,
                         "增量中位数%": 0, "增量均值%": 0, "胜率%": 0})
            continue
        arr = np.array(rets)
        rows.append({
            "信号名": name,
            "触发次数": len(arr),
            "增量中位数%": round(float(np.median(arr)), 2),
            "增量均值%": round(float(np.mean(arr)), 2),
            "胜率%": round(float((arr > 0).mean() * 100), 1),
        })
    df = pd.DataFrame(rows).sort_values("增量中位数%", ascending=False)
    return df


def main():
    codes = load_all_codes()
    if not codes:
        print("未找到全市场列表")
        return

    idx_df = load_kline_json("sh000001")
    if idx_df.empty:
        print("大盘缺失")
        return
    idx_df["日期"] = pd.to_datetime(idx_df["日期"])
    idx_close = idx_df.set_index("日期")["收盘"].sort_index()
    idx_ma20 = idx_close.rolling(20, min_periods=1).mean()
    idx_above = (idx_close >= idx_ma20)
    idx_above_map = {d.strftime("%Y-%m-%d"): bool(v) for d, v in idx_above.items()}
    print(f"全市场 {len(codes)} 只 | 大盘 {len(idx_above_map)} 天")

    all_results, done = load_raw()
    todo = [c for c in codes if c not in done]
    print(f"已完成 {len(done)} | 待跑 {len(todo)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    processed = 0
    fh = open(RAW_PATH, "a", encoding="utf-8")
    try:
        for code in todo:
            try:
                results = analyze_one(code, idx_above_map)
            except Exception as e:
                print(f"  跳过 {code}: {type(e).__name__} {e}")
                results = {}
            for k, v in results.items():
                all_results.setdefault(k, []).extend(v)
            fh.write(json.dumps({"code": code, "results": results},
                                ensure_ascii=False) + "\n")
            processed += 1
            if processed % LOG_EVERY == 0:
                print(f"  进度 {processed}/{len(todo)}")
            if processed % FLUSH_EVERY == 0:
                fh.flush()
        fh.flush()
    finally:
        fh.close()

    df = summarize(all_results)
    out_csv = os.path.join(OUT_DIR, "bottom_ranking.csv")
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n已写入: {out_csv}")
    print("\n=== 4个新抄底信号（全市场5220只，T+1+成本1.1%+MA20上+持有5日）===")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
