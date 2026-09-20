#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄金柱深挖 v2 (golden_deep_dive.py) —— 2026量化时代修正
=================================================================
v2 变更：
  1. T+1约束：次日开盘买
  2. 交易成本1.1%
  3. 大盘MA20过滤：只统计大盘MA20之上的黄金柱
  4. 多周期5/10/20日对比
  5. 按位置/市场状态/右确认三维分组

v1问题：HOLD=20、无T+1、无成本，数字偏乐观
"""
import json
import os
import random
import sys
import zlib

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_fetcher import ANALYSIS_DIR, KLINE_DIR, load_kline_json  # noqa: E402
from phases import (identify_volume_columns, three_day_confirm,  # noqa: E402
                    identify_genes, classify_position, compute_atr)

STOCK_LIST = os.path.join(KLINE_DIR, "_stock_list.json")
HOLD_LIST = [5, 10, 20]
COST_ROUNDTRIP = 1.1
N_RANDOM = 100
RANDOM_SEED = 42

def load_tx_list():
    with open(STOCK_LIST, encoding="utf-8") as f:
        return [s["tx"] for s in json.load(f).get("stocks", []) if s.get("tx")]

def _fwd_t1(open_arr, close_arr, i, n):
    """T+1：次日开盘买，第n日收盘卖，扣成本"""
    buy_idx = i + 1
    sell_idx = i + n
    if sell_idx >= len(close_arr):
        return None
    buy_p = open_arr[buy_idx]
    if buy_p <= 0:
        return None
    return (close_arr[sell_idx] / buy_p - 1.0) * 100 - COST_ROUNDTRIP

def build_market_state(idx_df):
    idx_df = idx_df.sort_values("日期").reset_index(drop=True)
    close = pd.to_numeric(idx_df["收盘"], errors="coerce")
    ma20 = close.rolling(20, min_periods=1).mean()
    states = []
    for c, m in zip(close, ma20):
        if pd.isna(m) or m <= 0:
            states.append("sideways")
        elif c > m * 1.02:
            states.append("bull")
        elif c < m * 0.98:
            states.append("bear")
        else:
            states.append("sideways")
    return dict(zip(idx_df["日期"].astype(str).str[:10], states))

def detect_right_confirm(df, i, window=3):
    """v2：右确认窗口从5天缩短到3天（量化时代节奏快）"""
    n = len(df)
    for j in range(i + 1, min(i + 1 + window, n)):
        prev_o = df["开盘"].iloc[j - 1]
        prev_c = df["收盘"].iloc[j - 1]
        today_c = df["收盘"].iloc[j]
        today_o = df["开盘"].iloc[j]
        if today_c > today_o and prev_c < prev_o and today_c > max(prev_o, prev_c):
            return True
    return False

def analyze_one_stock(code, market_state_map, idx_above_map):
    df = load_kline_json(code)
    if df.empty or len(df) < 30:
        return []
    df["日期"] = pd.to_datetime(df["日期"])
    for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["lo120"] = df["最低"].rolling(120, min_periods=1).min()
    df["hi120_prev"] = df["最高"].shift(1).rolling(120, min_periods=1).max()
    df = compute_atr(df)
    df = identify_volume_columns(df)
    df = three_day_confirm(df)
    df["位置"] = [classify_position(c, l, h)
                  for c, l, h in zip(df["收盘"], df["lo120"], df["hi120_prev"])]
    df = identify_genes(df)

    open_arr = df["开盘"].to_numpy(float)
    close_arr = df["收盘"].to_numpy(float)
    n = len(close_arr)
    max_hold = max(HOLD_LIST)

    seed = RANDOM_SEED + zlib.crc32(str(code).encode()) % 10000
    valid_idx = [i for i in range(20, n - max_hold - 1) if close_arr[i] > 0]
    sample_n = min(N_RANDOM, len(valid_idx))
    if sample_n == 0:
        return []
    rand_fwd = {}
    for hold in HOLD_LIST:
        samples = random.Random(seed).sample(valid_idx, sample_n)
        f = [_fwd_t1(open_arr, close_arr, i, hold) for i in samples]
        f = [x for x in f if x is not None]
        rand_fwd[hold] = float(np.mean(f)) if f else 0.0

    golden = df["黄金柱"].fillna(False).astype(bool).to_numpy()
    recs = []
    for i in range(20, n - max_hold - 1):
        if not golden[i]:
            continue
        date_str = df["日期"].iloc[i].strftime("%Y-%m-%d")
        # v2: 大盘MA20过滤
        if not idx_above_map.get(date_str, True):
            continue
        for hold in HOLD_LIST:
            f = _fwd_t1(open_arr, close_arr, i, hold)
            if f is None:
                continue
            recs.append({
                "位置": df["位置"].iloc[i],
                "市场状态": market_state_map.get(date_str, "sideways"),
                "右确认": detect_right_confirm(df, i),
                "持有天数": hold,
                "增量": f - rand_fwd[hold],
            })
    return recs

def summarize(samples, dim):
    rows = []
    for (val, hold), g in samples.groupby([dim, "持有天数"]):
        arr = g["增量"].to_numpy(float)
        if arr.size == 0:
            continue
        rows.append({
            "分组维度": dim,
            "分组值": str(val),
            "持有天数": hold,
            "样本数": int(arr.size),
            "增量中位数%": round(float(np.median(arr)), 2),
            "增量均值%": round(float(np.mean(arr)), 2),
            "胜率%": round(float((arr > 0).mean() * 100), 1),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["持有天数", "增量中位数%"], ascending=[True, False]).reset_index(drop=True)

def main():
    codes = load_tx_list()
    print(f"共 {len(codes)} 只（v2: T+1+成本{COST_ROUNDTRIP}%+MA20上+持有{HOLD_LIST}日）")

    idx_df = load_kline_json("sh000001")
    if idx_df.empty:
        print("大盘缺失")
        return
    idx_df["日期"] = pd.to_datetime(idx_df["日期"])
    market_state_map = build_market_state(idx_df)
    idx_close = idx_df.set_index("日期")["收盘"].sort_index()
    idx_ma20 = idx_close.rolling(20, min_periods=1).mean()
    idx_above = (idx_close >= idx_ma20)
    idx_above_map = {d.strftime("%Y-%m-%d"): bool(v) for d, v in idx_above.items()}
    print(f"大盘 {len(market_state_map)} 天")

    all_recs = []
    for idx, code in enumerate(codes):
        try:
            all_recs.extend(analyze_one_stock(code, market_state_map, idx_above_map))
        except Exception:
            pass
        if (idx + 1) % 500 == 0:
            print(f"  进度 {idx+1}/{len(codes)} | 累计黄金柱 {len(all_recs)}")

    print(f"\n总黄金柱信号: {len(all_recs)}")
    samples = pd.DataFrame(all_recs)
    if samples.empty:
        print("无样本")
        return

    os.makedirs(ANALYSIS_DIR, exist_ok=True)

    by_pos = summarize(samples, "位置")
    by_pos.to_csv(os.path.join(ANALYSIS_DIR, "golden_by_position.csv"),
                  index=False, encoding="utf-8-sig")
    print("\n=== 按位置 ===")
    print(by_pos.to_string(index=False))

    by_mkt = summarize(samples, "市场状态")
    by_mkt.to_csv(os.path.join(ANALYSIS_DIR, "golden_by_market.csv"),
                  index=False, encoding="utf-8-sig")
    print("\n=== 按市场状态 ===")
    print(by_mkt.to_string(index=False))

    by_cf = summarize(samples, "右确认")
    by_cf.to_csv(os.path.join(ANALYSIS_DIR, "golden_by_confirm.csv"),
                  index=False, encoding="utf-8-sig")
    print("\n=== 按右确认 ===")
    print(by_cf.to_string(index=False))

if __name__ == "__main__":
    main()
