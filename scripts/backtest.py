#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测统计 (backtest.py) —— 【事后验证，不是预测】
读 signal_log.csv，对每条信号用 日期+代码 在日线 JSON 中定位，统计其出现后
5/10/20 个交易日的涨跌幅、后10日胜率、后20日最大回撤，再按 阶段/信号强度/位置
三维度分组汇总。用于事后检验系统区分度，不预测未来、不构成交易信号源。

输入：data/analysis/signal_log.csv + data/kline/**/*.json
输出：data/analysis/backtest_summary.csv（utf-8-sig；涨跌幅/胜率/回撤单位为 %）
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_fetcher import ANALYSIS_DIR, load_kline_json  # noqa: E402

SIGNAL_PATH = os.path.join(ANALYSIS_DIR, "signal_log.csv")
OUT_PATH = os.path.join(ANALYSIS_DIR, "backtest_summary.csv")
HORIZONS = (5, 10, 20)
N_MAX = 20
VALID_STAGE = ("建仓", "洗盘", "拉升", "出货")
VALID_STRENGTH = ("强信号", "中信号", "弱信号")
VALID_POS = ("凹底", "低位", "中位", "高位", "过峰")

def _forward_stats(close, i):
    """信号第 i 行未来表现；未来不足 20 日返回 None。"""
    if i + N_MAX >= len(close):
        return None
    base = close[i]
    if base <= 0:
        return None
    fwd = [(close[i + n] / base - 1.0) * 100 for n in HORIZONS]
    win10 = 100.0 if fwd[1] > 0 else 0.0
    window = close[i + 1:i + N_MAX + 1]
    peak = np.maximum.accumulate(np.concatenate([[base], window]))[1:]
    mdd = ((window / peak) - 1.0).min() * 100
    return fwd[0], fwd[1], fwd[2], win10, mdd

def build_samples(df):
    """逐条信号抽取未来表现，返回长表。"""
    records = []
    for code, grp in df.groupby("代码"):
        k = load_kline_json(str(code))
        if k.empty:
            continue
        k = k.sort_values("日期").reset_index(drop=True)
        close = pd.to_numeric(k["收盘"], errors="coerce").to_numpy(float)
        pos_map = {d: idx for idx, d in enumerate(k["日期"].astype(str).str[:10])}
        for _, r in grp.iterrows():
            i = pos_map.get(str(r["日期"])[:10])
            if i is None:
                continue
            st = _forward_stats(close, i)
            if st is None:
                continue
            records.append({
                "阶段": r["阶段"], "信号强度": r["信号强度"], "位置": r["位置"],
                "fwd5": st[0], "fwd10": st[1], "fwd20": st[2],
                "win10": st[3], "mdd20": st[4],
            })
    return pd.DataFrame(records)

def summarize(samples, dim):
    """按单一维度汇总统计指标。"""
    out = samples.groupby(dim).agg(
        样本数=("fwd5", "size"),
        后5日平均涨跌幅=("fwd5", "mean"),
        后10日平均涨跌幅=("fwd10", "mean"),
        后20日平均涨跌幅=("fwd20", "mean"),
        后10日上涨比例=("win10", "mean"),
        后20日最大回撤均值=("mdd20", "mean"),
    ).reset_index()
    out = out.rename(columns={dim: "分组值"})
    out.insert(0, "分组维度", dim)
    return out

def main():
    df = pd.read_csv(SIGNAL_PATH, dtype={"代码": str})
    df = df[df["阶段"].isin(VALID_STAGE)
            & df["信号强度"].isin(VALID_STRENGTH)
            & df["位置"].isin(VALID_POS)]
    samples = build_samples(df)
    print(f"有效样本: {len(samples)} / {len(df)}")
    parts = [summarize(samples, d) for d in ("阶段", "信号强度", "位置")]
    result = pd.concat(parts, ignore_index=True)
    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"已写入: {OUT_PATH} ({len(result)} 组)")

if __name__ == "__main__":
    main()