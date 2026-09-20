#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市场信号排行榜 v2 (signal_ranking_all.py) —— 2026量化时代修正
=================================================================
v2 变更：
  1. T+1约束：次日开盘买
  2. 交易成本1.1%
  3. 大盘MA20过滤：只统计大盘MA20之上的信号
  4. 持有5日（量化时代信号衰减快，重点看5日）
  5. 保留断点续跑机制（5220只×6小时）

输入：data/kline/_stock_list.json + data/kline/**/*.json
输出：data/analysis/signal_ranking_all.csv
      data/analysis/signal_ranking_all_raw.jsonl（断点文件）
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
                    identify_genes, classify_position, classify_vp, compute_atr)

OUT_PATH = os.path.join(ANALYSIS_DIR, "signal_ranking_all.csv")
RAW_PATH = os.path.join(ANALYSIS_DIR, "signal_ranking_all_raw.jsonl")
STOCK_LIST = os.path.join(KLINE_DIR, "_stock_list.json")
HOLD = 5
COST_ROUNDTRIP = 1.1
N_RANDOM = 100
RANDOM_SEED = 42
FLUSH_EVERY = 500
LOG_EVERY = 100
LIMIT = int(os.environ.get("SRA_LIMIT", "0"))

TRUSTED_SIGNALS = {"黄金柱", "将军柱"}

SIGNALS = [
    "黄金柱", "将军柱",
    "倍量柱", "高量柱", "低量柱", "缩量柱", "梯量柱", "平量柱",
    "百日低量", "百日低量群", "长阴短柱", "假阴真阳", "发烧柱",
    "倍量过左峰", "缩量回踩",
    "价升量缩", "价跌量缩", "量价齐升", "量增价跌",
    "该跌不跌", "该涨不涨",
]

RENAME = {
    "beiliang": "倍量柱", "gaoliang": "高量柱", "diliang": "低量柱",
    "suoliang": "缩量柱", "tiliang": "梯量柱", "pingliang": "平量柱",
}

def load_tx_list():
    with open(STOCK_LIST, encoding="utf-8") as f:
        payload = json.load(f)
    return [s["tx"] for s in payload.get("stocks", []) if s.get("tx")]

def _fwd_t1(open_arr, close_arr, i, n=HOLD):
    """T+1：次日开盘买，第n日收盘卖，扣成本"""
    buy_idx = i + 1
    sell_idx = i + n
    if sell_idx >= len(close_arr):
        return None
    buy_p = open_arr[buy_idx]
    if buy_p <= 0:
        return None
    return (close_arr[sell_idx] / buy_p - 1.0) * 100 - COST_ROUNDTRIP

def analyze_one_stock(code, idx_close_map, idx_above_map):
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
    df["大盘MA20上"] = df["日期"].astype(str).str[:10].map(idx_above_map).fillna(True)
    df = df.rename(columns=RENAME)

    open_arr = df["开盘"].to_numpy(float)
    close_arr = df["收盘"].to_numpy(float)
    n = len(close_arr)

    seed = RANDOM_SEED + zlib.crc32(str(code).encode()) % 10000
    valid_idx = [i for i in range(20, n - HOLD - 1) if close_arr[i] > 0]
    sample_n = min(N_RANDOM, len(valid_idx))
    if sample_n == 0:
        return {}
    rand_fwd = [_fwd_t1(open_arr, close_arr, i) for i in random.Random(seed).sample(valid_idx, sample_n)]
    rand_fwd = [x for x in rand_fwd if x is not None]
    if not rand_fwd:
        return {}
    rand_mean = float(np.mean(rand_fwd))

    result = {}
    for sig in SIGNALS:
        if sig in ("价升量缩", "价跌量缩", "量价齐升", "量增价跌"):
            mask = (df["量价配合"] == sig).to_numpy()
        elif sig not in df.columns:
            continue
        else:
            mask = df[sig].fillna(False).astype(bool).to_numpy()
        deltas = []
        for i in range(20, n - HOLD - 1):
            if not mask[i]:
                continue
            if not df["大盘MA20上"].iloc[i]:
                continue
            f = _fwd_t1(open_arr, close_arr, i)
            if f is not None:
                deltas.append(f - rand_mean)
        if deltas:
            result[sig] = deltas
    return result

def build_summary(all_deltas):
    rows = []
    for sig, deltas in all_deltas.items():
        arr = np.asarray(deltas, dtype=float)
        if arr.size == 0:
            continue
        grade = "真信号" if sig in TRUSTED_SIGNALS else "噪音"
        rows.append({
            "信号名": sig,
            "信号分级": grade,
            "触发次数": int(arr.size),
            "增量中位数%": round(float(np.median(arr)), 2),
            "增量均值%": round(float(np.mean(arr)), 2),
            "胜率%": round(float((arr > 0).mean() * 100), 1),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["信号分级", "增量中位数%"], ascending=[True, False]).reset_index(drop=True)
    return df

def write_summary(all_deltas):
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    build_summary(all_deltas).to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

def load_raw():
    all_deltas = {}
    done = set()
    if not os.path.exists(RAW_PATH):
        return all_deltas, done
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
            for sig, vals in (obj.get("signals") or {}).items():
                all_deltas.setdefault(sig, []).extend(vals)
    return all_deltas, done

def main():
    if not os.path.exists(STOCK_LIST):
        print(f"清单缺失: {STOCK_LIST}")
        return
    codes = load_tx_list()
    if LIMIT > 0:
        codes = codes[:LIMIT]

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

    all_deltas, done = load_raw()
    todo = [c for c in codes if c not in done]
    print(f"清单 {len(codes)} 只 | 已完成 {len(done)} | 待跑 {len(todo)}")
    print(f"（v2: T+1+成本{COST_ROUNDTRIP}%+MA20上+持有{HOLD}日）")

    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    processed = 0
    fh = open(RAW_PATH, "a", encoding="utf-8")
    try:
        for code in todo:
            try:
                r = analyze_one_stock(code, idx_map, idx_above_map)
            except Exception as e:
                print(f"  跳过 {code}: {type(e).__name__} {e}")
                r = {}
            rec = {sig: [round(float(x), 4) for x in vals]
                   for sig, vals in r.items() if vals}
            for sig, vals in rec.items():
                all_deltas.setdefault(sig, []).extend(vals)
            fh.write(json.dumps({"code": code, "signals": rec},
                                ensure_ascii=False) + "\n")
            processed += 1
            if processed % LOG_EVERY == 0:
                print(f"  进度 {processed}/{len(todo)} | "
                      f"累计股票 {len(done) + processed}")
            if processed % FLUSH_EVERY == 0:
                fh.flush()
                write_summary(all_deltas)
                print(f"  [checkpoint] 已写 {OUT_PATH}")
        fh.flush()
    finally:
        fh.close()

    write_summary(all_deltas)
    result = build_summary(all_deltas)
    print(f"\n已写入: {OUT_PATH}")
    trusted = result[result["信号分级"] == "真信号"]
    if not trusted.empty:
        print(f"\n★ 真信号：")
        print(trusted.to_string(index=False))
    print(f"\n全部信号：")
    print(result.to_string(index=False))

if __name__ == "__main__":
    main()
