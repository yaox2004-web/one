#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单信号有效性排行榜 (signal_ranking.py)
=====================================
对 phases.py 里识别的每个量学信号，单独算它相对"该股随机日"的增量。
用来找出"哪个单信号真的有 α"。

信号清单（从 phases.py 里的量柱识别 + 基因识别）：
量柱类：倍量柱/高量柱/低量柱/缩量柱/梯量柱/平量柱
王牌柱：黄金柱/将军柱
基因类：百日低量/百日低量群/长阴短柱/假阴真阳/发烧柱/倍量过左峰/缩量回踩
量价类：价升量缩/价跌量缩/量价齐升/量增价跌
环境类：该跌不跌/该涨不涨

每个信号输出：触发次数 / 增量中位数 / 增量均值 / 正比例

输入：data/kline/**/*.json
输出：data/analysis/signal_ranking.csv
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
    classify_position, classify_vp,
)

OUT_PATH = os.path.join(ANALYSIS_DIR, "signal_ranking.csv")
HOLD = 20
N_RANDOM = 100
RANDOM_SEED = 42

CODES_43 = None  # 从 self43.txt 读

def load_codes():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self43.txt")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [x.strip().zfill(6) for x in f if x.strip() and not x.startswith("#")]

# 所有要统计的单信号（列名 = 在 df 里对应列）
SIGNALS = [
    "倍量柱", "高量柱", "低量柱", "缩量柱", "梯量柱", "平量柱",
    "黄金柱", "将军柱",
    "百日低量", "百日低量群", "长阴短柱", "假阴真阳", "发烧柱",
    "倍量过左峰", "缩量回踩",
    "价升量缩", "价跌量缩", "量价齐升", "量增价跌",
    "该跌不跌", "该涨不涨",
]

def _fwd(close, i, n=HOLD):
    if i + n >= len(close) or close[i] <= 0:
        return None
    return (close[i + n] / close[i] - 1.0) * 100

def analyze_one_stock(code, idx_close_map):
    """对单只股票,返回 {signal: [增量列表]}"""
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

    # 大盘涨跌幅
    df["idx_ret"] = df["日期"].map(idx_close_map).pct_change().fillna(0.0)
    df["该跌不跌"] = (df["idx_ret"] < 0) & df["收阳"]
    df["该涨不涨"] = (df["idx_ret"] > 0) & (~df["收阳"])

    # 把中文列映射成信号名（phases 里的列名有的不叫"倍量柱"叫"beiliang"）
    rename = {
        "beiliang": "倍量柱", "gaoliang": "高量柱", "diliang": "低量柱",
        "suoliang": "缩量柱", "tiliang": "梯量柱", "pingliang": "平量柱",
    }
    df = df.rename(columns=rename)

    close = df["收盘"].to_numpy(float)
    n = len(close)

    # 随机基线（固定种子）
    seed = RANDOM_SEED + zlib.crc32(str(code).encode()) % 10000
    rng = random.Random(seed)
    valid_idx = [i for i in range(n - HOLD) if close[i] > 0]
    sample_n = min(N_RANDOM, len(valid_idx))
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

def main():
    codes = load_codes()
    if not codes:
        print("self43.txt 未找到或无内容")
        return
    print(f"共 {len(codes)} 只股票")

    # 加载大盘收盘（用 sh000001）
    idx_df = load_kline_json("sh000001")
    if idx_df.empty:
        print("大盘数据缺失")
        return
    idx_df["日期"] = pd.to_datetime(idx_df["日期"])
    idx_map = idx_df.set_index("日期")["收盘"].to_dict()
    print(f"大盘 {len(idx_map)} 天")

    all_deltas = {}
    for i, code in enumerate(codes):
        print(f"  [{i+1}/{len(codes)}] {code}")
        try:
            r = analyze_one_stock(code, idx_map)
            for sig, deltas in r.items():
                all_deltas.setdefault(sig, []).extend(deltas)
        except Exception as e:
            print(f"    跳过: {type(e).__name__} {e}")

    rows = []
    for sig, deltas in all_deltas.items():
        arr = np.array(deltas)
        rows.append({
            "信号名": sig,
            "触发次数": len(arr),
            "增量中位数": round(float(np.median(arr)), 2),
            "增量均值": round(float(np.mean(arr)), 2),
            "增量正比例": round(float((arr > 0).mean() * 100), 1),
        })
    result = pd.DataFrame(rows).sort_values("增量中位数", ascending=False)
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n已写入: {OUT_PATH}")
    print(result.to_string(index=False))

if __name__ == "__main__":
    main()