#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单信号有效性排行榜 v4 (signal_ranking.py) —— 2026量化时代·精简版
=================================================================
v4 变更（基于v3回测结论）：
  1. 去掉ATR止损（v3证明是负优化：1.5×ATR太紧，假摔被洗）
  2. 只保留收盘出场（持有到第n日收盘卖）
  3. 信号分级：真信号（黄金柱/将军柱）vs 噪音（其他）
  4. T+1约束 + 交易成本1.1% + 大盘MA20过滤
  5. 多周期5/10/20日对比

回测结论（v3验证）：
  - 黄金柱5日：68.2%胜率，+1.67%增量（409样本）
  - 将军柱5日：64.1%胜率，+1.36%增量（3877样本）
  - 其他所有信号：40-47%胜率，和随机买没区别
"""
import os
import random
import sys
import zlib

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_fetcher import ANALYSIS_DIR, load_kline_json, to_tx  # noqa: E402
from phases import (
    identify_volume_columns, three_day_confirm, identify_genes,
    classify_position, classify_vp, compute_atr,
)

OUT_PATH = os.path.join(ANALYSIS_DIR, "signal_ranking.csv")
HOLD_LIST = [5, 10, 20]
COST_ROUNDTRIP = 1.1
N_RANDOM = 100
RANDOM_SEED = 42

# 真信号白名单（v3回测验证：只有这两个有正alpha）
TRUSTED_SIGNALS = {"黄金柱", "将军柱"}

def load_codes():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self43.txt")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [x.strip().zfill(6) for x in f if x.strip() and not x.startswith("#")]

SIGNALS = [
    "黄金柱", "将军柱",  # 真信号排前面
    "倍量柱", "高量柱", "低量柱", "缩量柱", "梯量柱", "平量柱",
    "百日低量", "百日低量群", "长阴短柱", "假阴真阳", "发烧柱",
    "倍量过左峰", "缩量回踩",
    "价升量缩", "价跌量缩", "量价齐升", "量增价跌",
    "该跌不跌", "该涨不涨",
]

def _fwd_t1(open_arr, close_arr, i, n):
    """T+1：次日开盘买，第n日收盘卖，扣交易成本"""
    buy_idx = i + 1
    sell_idx = i + n
    if sell_idx >= len(close_arr):
        return None
    buy_p = open_arr[buy_idx]
    if buy_p <= 0:
        return None
    return (close_arr[sell_idx] / buy_p - 1.0) * 100 - COST_ROUNDTRIP

def analyze_one_stock(code, idx_close_map, idx_above_ma20_map):
    df = load_kline_json(code)
    if df.empty:
        return {}
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
    df["量价配合"] = [classify_vp(c, cy, v, vy)
                     for c, cy, v, vy in zip(
                         df["收盘"], df["收盘"].shift(1),
                         df["成交量"], df["成交量"].shift(1))]
    df = identify_genes(df)

    df["idx_ret"] = df["日期"].map(idx_close_map).pct_change().fillna(0.0)
    df["该跌不跌"] = (df["idx_ret"] < 0) & df["收阳"]
    df["该涨不涨"] = (df["idx_ret"] > 0) & (~df["收阳"])
    df["大盘MA20上"] = df["日期"].astype(str).str[:10].map(idx_above_ma20_map).fillna(True)

    rename = {
        "beiliang": "倍量柱", "gaoliang": "高量柱", "diliang": "低量柱",
        "suoliang": "缩量柱", "tiliang": "梯量柱", "pingliang": "平量柱",
    }
    df = df.rename(columns=rename)

    open_arr = df["开盘"].to_numpy(float)
    close_arr = df["收盘"].to_numpy(float)
    n = len(close_arr)

    seed = RANDOM_SEED + zlib.crc32(str(code).encode()) % 10000
    rng = random.Random(seed)
    max_hold = max(HOLD_LIST)
    valid_idx = [i for i in range(20, n - max_hold - 1) if close_arr[i] > 0]
    sample_n = min(N_RANDOM, len(valid_idx))

    # 随机基线
    rand_results = {}
    for hold in HOLD_LIST:
        rand_fwd = [_fwd_t1(open_arr, close_arr, i, hold)
                    for i in random.Random(seed).sample(valid_idx, sample_n)]
        rand_fwd = [x for x in rand_fwd if x is not None]
        rand_results[hold] = float(np.mean(rand_fwd)) if rand_fwd else 0.0

    result = {}
    for sig in SIGNALS:
        if sig in ("价升量缩", "价跌量缩", "量价齐升", "量增价跌"):
            mask = (df["量价配合"] == sig).to_numpy()
        elif sig not in df.columns:
            continue
        else:
            mask = df[sig].fillna(False).astype(bool).to_numpy()

        for hold in HOLD_LIST:
            deltas = []
            for i in range(20, n - hold - 1):
                if not mask[i]:
                    continue
                if not df["大盘MA20上"].iloc[i]:
                    continue
                f = _fwd_t1(open_arr, close_arr, i, hold)
                if f is not None:
                    deltas.append(f - rand_results[hold])
            if deltas:
                result[f"{sig}_H{hold}"] = deltas
    return result

def main():
    codes = load_codes()
    if not codes:
        print("self43.txt 未找到或无内容")
        return
    print(f"共 {len(codes)} 只（v4: T+1+成本{COST_ROUNDTRIP}%+大盘MA20上+持有{str(HOLD_LIST)}日）")

    idx_df = load_kline_json("sh000001")
    if idx_df.empty:
        print("大盘数据缺失")
        return
    idx_df["日期"] = pd.to_datetime(idx_df["日期"])
    idx_map = idx_df.set_index("日期")["收盘"].to_dict()
    idx_close = idx_df.set_index("日期")["收盘"].sort_index()
    idx_ma20 = idx_close.rolling(20, min_periods=1).mean()
    idx_above = (idx_close >= idx_ma20)
    idx_above_map = {d.strftime("%Y-%m-%d"): bool(v) for d, v in idx_above.items()}
    print(f"大盘 {len(idx_map)} 天")

    all_deltas = {}
    for i, code in enumerate(codes):
        print(f"  [{i+1}/{len(codes)}] {code}")
        try:
            r = analyze_one_stock(code, idx_map, idx_above_map)
            for sig, deltas in r.items():
                all_deltas.setdefault(sig, []).extend(deltas)
        except Exception as e:
            print(f"    跳过: {type(e).__name__} {e}")

    rows = []
    for sig_key, deltas in all_deltas.items():
        sig_name, hold_str = sig_key.rsplit("_H", 1)
        hold = int(hold_str)
        arr = np.array(deltas)
        # 信号分级
        if sig_name in TRUSTED_SIGNALS:
            grade = "真信号"
        elif float((arr > 0).mean() * 100) >= 50 and float(np.median(arr)) > 0:
            grade = "观察"
        else:
            grade = "噪音"
        rows.append({
            "信号名": sig_name,
            "信号分级": grade,
            "持有天数": hold,
            "触发次数": len(arr),
            "增量中位数%": round(float(np.median(arr)), 2),
            "增量均值%": round(float(np.mean(arr)), 2),
            "胜率%": round(float((arr > 0).mean() * 100), 1),
        })
    result = pd.DataFrame(rows).sort_values(["信号分级", "持有天数", "增量中位数%"],
                                            ascending=[True, True, False])
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n已写入: {OUT_PATH}")
    # 突出真信号
    trusted = result[result["信号分级"] == "真信号"]
    if not trusted.empty:
        print(f"\n{'='*60}")
        print("★ 真信号（v3回测验证有正alpha）")
        print(f"{'='*60}")
        print(trusted.to_string(index=False))

    # 按持有期分别打印
    for hold in HOLD_LIST:
        sub = result[result["持有天数"] == hold].sort_values("增量中位数%", ascending=False)
        print(f"\n=== 持有{hold}日（T+1,成本{COST_ROUNDTRIP}%,大盘MA20上）===")
        print(sub.to_string(index=False))

if __name__ == "__main__":
    main()
