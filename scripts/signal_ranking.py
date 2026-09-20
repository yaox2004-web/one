#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单信号有效性排行榜 v3 (signal_ranking.py) —— 2026量化时代·ATR止损版
=================================================================
v3 新增：ATR止损回测
  1. T+1：次日开盘买
  2. 交易成本1.1%
  3. 多周期5/10/20日
  4. 大盘MA20过滤
  5. v3新增：ATR止损（持有期内跌破 买入价-1.5×ATR14 就止损卖出）

对比两种出场方式：
  - 收盘出场：持有到第n日收盘卖（原方法）
  - ATR止损出场：持有期内触及止损价就卖（v3新增）
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
ATR_STOP_MULT = 1.5     # v3: 止损 = 买入价 - 1.5×ATR14
N_RANDOM = 100
RANDOM_SEED = 42

def load_codes():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self43.txt")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [x.strip().zfill(6) for x in f if x.strip() and not x.startswith("#")]

SIGNALS = [
    "倍量柱", "高量柱", "低量柱", "缩量柱", "梯量柱", "平量柱",
    "黄金柱", "将军柱",
    "百日低量", "百日低量群", "长阴短柱", "假阴真阳", "发烧柱",
    "倍量过左峰", "缩量回踩",
    "价升量缩", "价跌量缩", "量价齐升", "量增价跌",
    "该跌不跌", "该涨不涨",
]

def _fwd_close(open_arr, close_arr, i, n):
    """T+1 收盘出场：次日开盘买，第n日收盘卖"""
    buy_idx = i + 1
    sell_idx = i + n
    if sell_idx >= len(close_arr):
        return None
    buy_p = open_arr[buy_idx]
    if buy_p <= 0:
        return None
    return (close_arr[sell_idx] / buy_p - 1.0) * 100 - COST_ROUNDTRIP

def _fwd_atr_stop(open_arr, close_arr, low_arr, atr_arr, i, n, atr_mult=ATR_STOP_MULT):
    """T+1 + ATR止损：次日开盘买，持有期内跌破止损价就止损"""
    buy_idx = i + 1
    if buy_idx >= len(close_arr):
        return None
    buy_p = open_arr[buy_idx]
    if buy_p <= 0:
        return None
    atr_i = atr_arr[i] if not np.isnan(atr_arr[i]) else buy_p * 0.03
    stop_p = buy_p - atr_i * atr_mult
    # 检查持有期内是否触及止损
    for j in range(buy_idx + 1, min(i + n + 1, len(low_arr))):
        if low_arr[j] <= stop_p:
            return (stop_p / buy_p - 1.0) * 100 - COST_ROUNDTRIP
    # 没触及止损，按第n日收盘卖
    sell_idx = i + n
    if sell_idx >= len(close_arr):
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

    df = compute_atr(df)  # v3: 算ATR
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
    low_arr = df["最低"].to_numpy(float)
    atr_arr = df["ATR14"].to_numpy(float)
    n = len(close_arr)

    seed = RANDOM_SEED + zlib.crc32(str(code).encode()) % 10000
    rng = random.Random(seed)
    max_hold = max(HOLD_LIST)
    valid_idx = [i for i in range(20, n - max_hold - 1) if close_arr[i] > 0]
    sample_n = min(N_RANDOM, len(valid_idx))

    # 随机基线：两种出场方式
    rand_close = {}
    rand_stop = {}
    for hold in HOLD_LIST:
        samples = random.Random(seed).sample(valid_idx, sample_n)
        f1 = [_fwd_close(open_arr, close_arr, i, hold) for i in samples]
        f1 = [x for x in f1 if x is not None]
        f2 = [_fwd_atr_stop(open_arr, close_arr, low_arr, atr_arr, i, hold) for i in samples]
        f2 = [x for x in f2 if x is not None]
        rand_close[hold] = float(np.mean(f1)) if f1 else 0.0
        rand_stop[hold] = float(np.mean(f2)) if f2 else 0.0

    result = {}
    for sig in SIGNALS:
        if sig in ("价升量缩", "价跌量缩", "量价齐升", "量增价跌"):
            mask = (df["量价配合"] == sig).to_numpy()
        elif sig not in df.columns:
            continue
        else:
            mask = df[sig].fillna(False).astype(bool).to_numpy()

        for hold in HOLD_LIST:
            # 收盘出场
            deltas_close = []
            # ATR止损出场
            deltas_stop = []
            for i in range(20, n - hold - 1):
                if not mask[i]:
                    continue
                if not df["大盘MA20上"].iloc[i]:
                    continue
                f1 = _fwd_close(open_arr, close_arr, i, hold)
                if f1 is not None:
                    deltas_close.append(f1 - rand_close[hold])
                f2 = _fwd_atr_stop(open_arr, close_arr, low_arr, atr_arr, i, hold)
                if f2 is not None:
                    deltas_stop.append(f2 - rand_stop[hold])
            if deltas_close:
                result[f"{sig}_H{hold}_收盘出场"] = deltas_close
            if deltas_stop:
                result[f"{sig}_H{hold}_ATR止损"] = deltas_stop
    return result

def main():
    codes = load_codes()
    if not codes:
        print("self43.txt 未找到或无内容")
        return
    print(f"共 {len(codes)} 只（v3: T+1+成本{COST_ROUNDTRIP}%+ATR止损{ATR_STOP_MULT}倍+多周期{str(HOLD_LIST)}）")

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
        parts = sig_key.rsplit("_H", 1)
        sig_name = parts[0]
        rest = parts[1] if len(parts) > 1 else "20_收盘出场"
        hold_str, exit_mode = rest.split("_", 1) if "_" in rest else (rest, "收盘出场")
        hold = int(hold_str)
        arr = np.array(deltas)
        rows.append({
            "信号名": sig_name,
            "持有天数": hold,
            "出场方式": exit_mode,
            "触发次数": len(arr),
            "增量中位数%": round(float(np.median(arr)), 2),
            "增量均值%": round(float(np.mean(arr)), 2),
            "增量正比例%": round(float((arr > 0).mean() * 100), 1),
        })
    result = pd.DataFrame(rows).sort_values(["信号名", "持有天数", "出场方式"])
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n已写入: {OUT_PATH}")
    for hold in HOLD_LIST:
        for mode in ["收盘出场", "ATR止损"]:
            sub = result[(result["持有天数"] == hold) & (result["出场方式"] == mode)] \
                .sort_values("增量中位数%", ascending=False)
            if not sub.empty:
                print(f"\n=== 持有{hold}日 / {mode} ===")
                print(sub[["信号名", "触发次数", "增量中位数%", "增量正比例%"]].to_string(index=False))

if __name__ == "__main__":
    main()
