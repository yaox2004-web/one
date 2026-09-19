#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4c 配对检验 (backtest_paired.py)
================================
对每条信号，计算它相对"该股随机日"的增量（超额收益）。
- 信号日 20 日涨幅 - 该股随机日 20 日涨幅均值 = 增量
- 按 阶段/信号强度/位置 分组汇总（均值/中位数/符号比）

核心：扣掉"该股本身就涨"的 β，看信号有没有 α。
固定随机种子，保证可复现。

输入：data/analysis/signal_log.csv + data/kline/**/*.json
输出：data/analysis/backtest_paired.csv
"""
import os
import random
import sys
import zlib

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_fetcher import ANALYSIS_DIR, load_kline_json  # noqa: E402

SIGNAL_PATH = os.path.join(ANALYSIS_DIR, "signal_log.csv")
OUT_PATH = os.path.join(ANALYSIS_DIR, "backtest_paired.csv")
HOLD = 20
N_RANDOM = 100
RANDOM_SEED = 42
VALID_STAGE = ("建仓", "洗盘", "拉升", "出货")
VALID_STRENGTH = ("强信号", "中信号", "弱信号")
VALID_POS = ("凹底", "低位", "中位", "高位", "过峰")

def _fwd(close, i, n=HOLD):
    if i + n >= len(close) or close[i] <= 0:
        return None
    return (close[i + n] / close[i] - 1.0) * 100

def build_samples(df):
    records = []
    for code, grp in df.groupby("代码"):
        k = load_kline_json(str(code))
        if k.empty:
            continue
        k = k.sort_values("日期").reset_index(drop=True)
        close = pd.to_numeric(k["收盘"], errors="coerce").to_numpy(float)
        n = len(close)
        if n < HOLD + 5:
            continue
        pos_map = {d: idx for idx, d in enumerate(k["日期"].astype(str).str[:10])}
        valid_idx = [i for i in range(n - HOLD) if close[i] > 0]
        seed = RANDOM_SEED + zlib.crc32(str(code).encode()) % 10000
        rng = random.Random(seed)
        sample_n = min(N_RANDOM, len(valid_idx))
        rand_idx = rng.sample(valid_idx, sample_n) if sample_n > 0 else []
        rand_fwd = [_fwd(close, i) for i in rand_idx]
        rand_fwd = [x for x in rand_fwd if x is not None]
        if not rand_fwd:
            continue
        rand_mean = float(np.mean(rand_fwd))
        for _, r in grp.iterrows():
            i = pos_map.get(str(r["日期"])[:10])
            if i is None:
                continue
            sf = _fwd(close, i)
            if sf is None:
                continue
            records.append({
                "阶段": r["阶段"],
                "信号强度": r["信号强度"],
                "位置": r["位置"],
                "信号涨幅": sf,
                "随机基线": rand_mean,
                "增量": sf - rand_mean,
            })
    return pd.DataFrame(records)

def summarize(samples, dim):
    rows = []
    for val, g in samples.groupby(dim):
        inc = g["增量"]
        pos_cnt = int((inc > 0).sum())
        tot = len(inc)
        rows.append({
            "分组维度": dim,
            "分组值": val,
            "样本数": tot,
            "增量均值": round(inc.mean(), 2),
            "增量中位数": round(inc.median(), 2),
            "增量正比例": round(pos_cnt / tot * 100, 1) if tot else 0.0,
        })
    return pd.DataFrame(rows)

def main():
    df = pd.read_csv(SIGNAL_PATH, dtype={"代码": str})
    df = df[df["阶段"].isin(VALID_STAGE)
            & df["信号强度"].isin(VALID_STRENGTH)
            & df["位置"].isin(VALID_POS)]
    print(f"过滤后信号: {len(df)}")
    samples = build_samples(df)
    print(f"有效样本: {len(samples)}")
    if samples.empty:
        print("无有效样本")
        return
    parts = [summarize(samples, d) for d in ("阶段", "信号强度", "位置")]
    result = pd.concat(parts, ignore_index=True)
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"已写入: {OUT_PATH} ({len(result)} 组)")
    inc = samples["增量"]
    print(f"\n[全样本] 增量均值={inc.mean():.2f}% "
          f"中位数={inc.median():.2f}% "
          f"正比例={(inc>0).sum()/len(inc)*100:.1f}%")

if __name__ == "__main__":
    main()