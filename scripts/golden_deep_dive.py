#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄金柱深挖 v5 (golden_deep_dive.py) —— 加5个新维度
=================================================================
v5 新增维度：
  1. 市值档（用成交额近似）
  2. 量Z分数档
  3. ATR波动率档
  4. 距20日均线档
  5. 距60日新高档
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

OUT_DIR = ANALYSIS_DIR
RAW_PATH = os.path.join(OUT_DIR, "golden_deep_dive_raw.jsonl")
ALL_RAW = os.path.join(OUT_DIR, "signal_ranking_all_raw.jsonl")
HOLD_LIST = [5, 10, 20]
COST_ROUNDTRIP = 1.1
N_RANDOM = 100
RANDOM_SEED = 42
FLUSH_EVERY = 200
LOG_EVERY = 50


def load_all_codes():
    codes = set()
    if not os.path.exists(ALL_RAW):
        return []
    with open(ALL_RAW, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = json.loads(line)
                if obj.get("code"): codes.add(obj["code"])
            except: continue
    return sorted(codes)


def _fwd_t1(open_arr, close_arr, i, n):
    bi, si = i+1, i+n
    if si >= len(close_arr): return None
    bp = open_arr[bi]
    if bp <= 0: return None
    return (close_arr[si]/bp - 1.0)*100 - COST_ROUNDTRIP


def build_market_state(idx_df):
    idx_df = idx_df.sort_values("日期").reset_index(drop=True)
    close = pd.to_numeric(idx_df["收盘"], errors="coerce")
    ma20 = close.rolling(20, min_periods=1).mean()
    states = []
    for c, m in zip(close, ma20):
        if pd.isna(m) or m <= 0: states.append("sideways")
        elif c > m*1.02: states.append("bull")
        elif c < m*0.98: states.append("bear")
        else: states.append("sideways")
    return dict(zip(idx_df["日期"].astype(str).str[:10], states))


def detect_right_confirm(df, i, window=3):
    n = len(df)
    for j in range(i+1, min(i+1+window, n)):
        po, pc = df["开盘"].iloc[j-1], df["收盘"].iloc[j-1]
        tc, to = df["收盘"].iloc[j], df["开盘"].iloc[j]
        if tc > to and pc < po and tc > max(po, pc):
            return True
    return False


def size_bucket(amount):
    """成交额近似市值：<5000万小盘，5000万-5亿中盘，>5亿大盘"""
    if amount < 5000: return "小盘"
    if amount < 50000: return "中盘"
    return "大盘"


def z_bucket(z):
    if z < 1.0: return "温和"
    if z < 2.0: return "放量"
    return "爆量"


def atr_bucket(pct):
    if pct < 2.5: return "低波动"
    if pct < 4.5: return "中波动"
    return "高波动"


def ma_dist_bucket(pct):
    if pct < -3: return "MA20下"
    if pct < 3: return "MA20旁"
    return "MA20上"


def high_dist_bucket(pct):
    if pct < 3: return "近前高"
    if pct < 10: return "距前高远"
    return "距前高很远"


def analyze_one(code, market_state_map, idx_above_map):
    df = load_kline_json(code)
    if df.empty or len(df) < 30: return []
    df = df.copy()
    df["日期"] = pd.to_datetime(df["日期"])
    for c in ["开盘","收盘","最高","最低","成交量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["lo120"] = df["最低"].rolling(120, min_periods=1).min()
    df["hi120_prev"] = df["最高"].shift(1).rolling(120, min_periods=1).max()
    df = compute_atr(df)
    df = identify_volume_columns(df)
    df = three_day_confirm(df)
    df["位置"] = [classify_position(c,l,h) for c,l,h in zip(df["收盘"], df["lo120"], df["hi120_prev"])]
    df = identify_genes(df)

    # v5新维度
    df["vol20"] = df["成交量"].rolling(20, min_periods=1).mean()
    df["vol_std"] = df["成交量"].rolling(20, min_periods=1).std()
    df["量Z"] = np.where(df["vol_std"]>0, (df["成交量"]-df["vol20"])/df["vol_std"], 0)
    df["ma20"] = df["收盘"].rolling(20, min_periods=1).mean()
    df["距MA20"] = (df["收盘"] - df["ma20"]) / df["ma20"] * 100
    df["hi60"] = df["最高"].rolling(60, min_periods=1).max()
    df["距前高"] = (df["hi60"] - df["收盘"]) / df["收盘"] * 100
    df["成交额"] = df["收盘"] * df["成交量"] / 10000  # 万元

    open_arr = df["开盘"].to_numpy(float)
    close_arr = df["收盘"].to_numpy(float)
    n = len(close_arr)
    max_hold = max(HOLD_LIST)

    seed = RANDOM_SEED + zlib.crc32(str(code).encode()) % 10000
    valid_idx = [i for i in range(20, n-max_hold-1) if close_arr[i] > 0]
    sn = min(N_RANDOM, len(valid_idx))
    if sn == 0: return []
    rand_fwd = {}
    for hold in HOLD_LIST:
        samples = random.Random(seed).sample(valid_idx, sn)
        f = [_fwd_t1(open_arr, close_arr, i, hold) for i in samples]
        f = [x for x in f if x is not None]
        rand_fwd[hold] = float(np.mean(f)) if f else 0.0

    golden = df["黄金柱"].fillna(False).astype(bool).to_numpy()
    recs = []
    for i in range(20, n-max_hold-1):
        if not golden[i]: continue
        ds = df["日期"].iloc[i].strftime("%Y-%m-%d")
        if not idx_above_map.get(ds, True): continue
        for hold in HOLD_LIST:
            f = _fwd_t1(open_arr, close_arr, i, hold)
            if f is None: continue
            recs.append({
                "位置": df["位置"].iloc[i],
                "市场状态": market_state_map.get(ds, "sideways"),
                "右确认": detect_right_confirm(df, i),
                "持有天数": hold,
                "增量": f - rand_fwd[hold],
                # v5新维度
                "市值档": size_bucket(df["成交额"].iloc[i]),
                "量Z档": z_bucket(df["量Z"].iloc[i]),
                "波动率档": atr_bucket(df["ATR_pct"].iloc[i]),
                "MA距离档": ma_dist_bucket(df["距MA20"].iloc[i]),
                "前高距离档": high_dist_bucket(df["距前高"].iloc[i]),
            })
    return recs


def summarize(records, dim):
    rows = []
    for (val, hold), g in records.groupby([dim, "持有天数"]):
        arr = g["增量"].to_numpy(float)
        if arr.size == 0: continue
        rows.append({
            "维度": dim, "分组值": str(val), "持有天数": hold,
            "样本数": int(arr.size),
            "增量中位%": round(float(np.median(arr)), 2),
            "增量均值%": round(float(np.mean(arr)), 2),
            "胜率%": round(float((arr>0).mean()*100), 1),
        })
    df = pd.DataFrame(rows)
    if df.empty: return df
    return df.sort_values(["持有天数","增量中位%"], ascending=[True,False]).reset_index(drop=True)


def load_raw():
    recs, done = [], set()
    if not os.path.exists(RAW_PATH): return recs, done
    with open(RAW_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: obj = json.loads(line)
            except: continue
            if not obj.get("code"): continue
            done.add(obj["code"])
            recs.extend(obj.get("records", []))
    return recs, done


def write_summary(records):
    if not records: return
    s = pd.DataFrame(records)
    dims = ["位置","市场状态","右确认","市值档","量Z档","波动率档","MA距离档","前高距离档"]
    for dim in dims:
        out = summarize(s, dim)
        fname = f"golden_by_{dim}.csv"
        out.to_csv(os.path.join(OUT_DIR, fname), index=False, encoding="utf-8-sig")


def main():
    codes = load_all_codes()
    if not codes: print("无列表"); return
    idx_df = load_kline_json("sh000001")
    if idx_df.empty: print("大盘缺失"); return
    idx_df["日期"] = pd.to_datetime(idx_df["日期"])
    msm = build_market_state(idx_df)
    ic = idx_df.set_index("日期")["收盘"].sort_index()
    im = ic.rolling(20, min_periods=1).mean()
    iam = {d.strftime("%Y-%m-%d"): bool(v) for d,v in (ic>=im).items()}
    print(f"全市场 {len(codes)} 只")

    records, done = load_raw()
    todo = [c for c in codes if c not in done]
    print(f"已完成 {len(done)} | 待跑 {len(todo)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    fh = open(RAW_PATH, "a", encoding="utf-8")
    processed = 0
    try:
        for code in todo:
            try: rec = analyze_one(code, msm, iam)
            except Exception as e:
                print(f"  跳过 {code}: {e}"); rec = []
            for r in rec: r["code"] = code
            records.extend(rec)
            fh.write(json.dumps({"code":code,"records":rec}, ensure_ascii=False)+"\n")
            processed += 1
            if processed % LOG_EVERY == 0: print(f"  进度 {processed}/{len(todo)} | 累计 {len(records)}")
            if processed % FLUSH_EVERY == 0:
                fh.flush(); write_summary(records)
        fh.flush()
    finally:
        fh.close()

    write_summary(records)
    print(f"\n总黄金柱信号: {len(records)}")
    s = pd.DataFrame(records)
    dims = ["位置","市场状态","右确认","市值档","量Z档","波动率档","MA距离档","前高距离档"]
    for dim in dims:
        print(f"\n=== 按{dim} ===")
        print(summarize(s, dim).to_string(index=False))


if __name__ == "__main__":
    main()
