#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市场信号排行榜 (signal_ranking_all.py)
========================================
逻辑同 signal_ranking.py（单信号相对"该股随机日"的 20 日增量），
但股票清单改为 data/kline/_stock_list.json 的全部 5220 只（含熊股/横盘股），
样本足够多样，信号的 α 才有机会显形。

分批与断点续跑（应对 GitHub Actions 单 job 6 小时上限）：
- 每只股票的增量追加写入 data/analysis/signal_ranking_all_raw.jsonl（一行一只）
- 每处理 500 只 flush 一次，并把"累计"排行榜写入 signal_ranking_all.csv
- 重跑时自动读 raw.jsonl，跳过已完成的股票，从断点继续
- 单只失败跳过不中断；每 100 只打印一次进度
- 建议 workflow 设 timeout-minutes: 360

输入：data/kline/_stock_list.json + data/kline/**/*.json
输出：data/analysis/signal_ranking_all.csv
      data/analysis/signal_ranking_all_raw.jsonl（断点文件，跑完可删）
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
                    identify_genes, classify_position, classify_vp)

OUT_PATH = os.path.join(ANALYSIS_DIR, "signal_ranking_all.csv")
RAW_PATH = os.path.join(ANALYSIS_DIR, "signal_ranking_all_raw.jsonl")
STOCK_LIST = os.path.join(KLINE_DIR, "_stock_list.json")
HOLD = 20
N_RANDOM = 100
RANDOM_SEED = 42
FLUSH_EVERY = 500
LOG_EVERY = 100
LIMIT = int(os.environ.get("SRA_LIMIT", "0"))

SIGNALS = [
    "倍量柱", "高量柱", "低量柱", "缩量柱", "梯量柱", "平量柱",
    "黄金柱", "将军柱",
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

def _fwd(close, i, n=HOLD):
    if i + n >= len(close) or close[i] <= 0:
        return None
    return (close[i + n] / close[i] - 1.0) * 100

def analyze_one_stock(code, idx_close_map):
    df = load_kline_json(code)
    if df.empty:
        return {}
    df["日期"] = pd.to_datetime(df["日期"])
    for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["lo120"] = df["最低"].rolling(120, min_periods=1).min()
    df["hi120_prev"] = df["最高"].shift(1).rolling(120, min_periods=1).max()

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
    df = df.rename(columns=RENAME)

    close = df["收盘"].to_numpy(float)
    n = len(close)
    seed = RANDOM_SEED + zlib.crc32(str(code).encode()) % 10000
    valid_idx = [i for i in range(n - HOLD) if close[i] > 0]
    sample_n = min(N_RANDOM, len(valid_idx))
    if sample_n == 0:
        return {}
    rand_fwd = [_fwd(close, i) for i in random.Random(seed).sample(valid_idx, sample_n)]
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
        for i in range(20, n - HOLD):
            if not mask[i]:
                continue
            f = _fwd(close, i)
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
        rows.append({
            "信号名": sig,
            "触发次数": int(arr.size),
            "增量中位数": round(float(np.median(arr)), 2),
            "增量均值": round(float(np.mean(arr)), 2),
            "增量正比例": round(float((arr > 0).mean() * 100), 1),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("增量中位数", ascending=False).reset_index(drop=True)
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
        print("大盘数据缺失，无法计算大盘涨跌幅")
        return
    idx_df["日期"] = pd.to_datetime(idx_df["日期"])
    idx_map = idx_df.set_index("日期")["收盘"].to_dict()

    all_deltas, done = load_raw()
    todo = [c for c in codes if c not in done]
    print(f"清单 {len(codes)} 只 | 已完成 {len(done)} | 待跑 {len(todo)}")
    print(f"大盘 {len(idx_map)} 天")

    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    processed = 0
    fh = open(RAW_PATH, "a", encoding="utf-8")
    try:
        for code in todo:
            try:
                r = analyze_one_stock(code, idx_map)
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
    print(result.to_string(index=False))

if __name__ == "__main__":
    main()