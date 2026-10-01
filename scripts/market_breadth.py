#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场宽度分析 (market_breadth.py) v1.2
=================================================
【矿脉C】全市场日线二次加工——回答"指数涨，是普涨还是权重股独舞？"

数据源: data/kline/{sh,sz}/*.json（只统计沪深，北交所不参与——
         流动性差、波动特性不同，混入会污染宽度信号）

核心输出（每日）:
  adv_ratio   上涨家数占比（>0.55健康 / <0.45疲弱）
  idx_ret     上证指数当日涨幅%
  divergence  背离标记: 指数涨但宽度塌 = 权重股独舞，牛市判定要打折
  adv_ma5     宽度5日均线（平滑噪声）

写入: data/analysis/market_breadth.json（每次全量重算覆盖——是分析产物，不是账本）
"""

import json
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data"
INDEX_PATH = DATA_DIR / "kline" / "sh" / "sh000001.json"
OUT_PATH = DATA_DIR / "analysis" / "market_breadth.json"

MARKETS = ["sh", "sz"]   # 只统计沪深（北交所不参与）
LOOKBACK_DAYS = 120      # 只统计最近N个交易日
MIN_STOCKS_PER_DAY = 10  # 当日有效样本下限（停牌潮保护）
DIVERG_ADV_HIGH = 0.55   # 宽度高阈值
DIVERG_ADV_LOW = 0.45    # 宽度低阈值
DIVERG_IDX_RET = 0.1     # 指数涨跌幅阈值%（过滤噪音）


def main():
    print("=" * 60)
    print("市场宽度分析（矿脉C：沪深全市场日线二次加工）")
    print("=" * 60)

    if not INDEX_PATH.exists():
        print("[宽度] ❌ 上证指数日线缺失，退出")
        return

    # ---- 指数日历 ----
    with open(INDEX_PATH, 'r') as f:
        idx_kl = json.load(f).get('klines', [])
    idx_dates = [str(k[0])[:10] for k in idx_kl]
    idx_close = [float(k[2]) for k in idx_kl]
    cutoff = idx_dates[-LOOKBACK_DAYS] if len(idx_dates) > LOOKBACK_DAYS else idx_dates[0]
    print(f"[宽度] 指数日历 {len(idx_dates)} 天，统计起点 {cutoff}")

    # ---- 沪深全市场逐股统计涨跌家数 ----
    updown = defaultdict(lambda: [0, 0])
    n_scanned = 0
    for mkt in MARKETS:
        d = DATA_DIR / "kline" / mkt
        if not d.exists():
            continue
        for fp in d.glob("*.json"):
            stem = fp.stem
            if stem == "sh000001" or stem.startswith("sz399"):
                continue  # 指数不参与宽度统计
            n_scanned += 1
            try:
                with open(fp, 'r') as f:
                    kl = json.load(f).get('klines', [])
            except Exception:
                continue
            for i in range(1, len(kl)):
                dt = str(kl[i][0])[:10]
                if dt < cutoff:
                    continue
                try:
                    c, p = float(kl[i][2]), float(kl[i - 1][2])
                except Exception:
                    continue
                if c > p:
                    updown[dt][0] += 1
                elif c < p:
                    updown[dt][1] += 1
    print(f"[宽度] 扫描 {n_scanned} 只股票（仅沪深）")

    # ---- 合成每日宽度 + 背离判定 ----
    out = {}
    ma_window = []
    for i in range(1, len(idx_dates)):
        dt = idx_dates[i]
        up, down = updown.get(dt, [0, 0])
        if up + down < MIN_STOCKS_PER_DAY:
            continue  # 数据稀疏日（如半日市/数据缺失），不计
        adv = up / (up + down)
        iret = (idx_close[i] / idx_close[i - 1] - 1) * 100
        divergence = (adv > DIVERG_ADV_HIGH and iret < -DIVERG_IDX_RET) or \
                     (adv < DIVERG_ADV_LOW and iret > DIVERG_IDX_RET)
        ma_window.append(adv)
        adv_ma5 = sum(ma_window[-5:]) / len(ma_window[-5:])
        out[dt] = {
            "adv_ratio": round(adv, 3),
            "up": up, "down": down,
            "idx_ret": round(iret, 2),
            "adv_ma5": round(adv_ma5, 3),
            "divergence": bool(divergence),
        }

    # ---- 写盘（原子写）----
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    tmp.replace(OUT_PATH)

    # ---- 控制台摘要 ----
    days = sorted(out)
    n_div = sum(1 for d in days if out[d]["divergence"])
    print(f"[宽度] 有效交易日 {len(days)} 天，其中背离日 {n_div} 天")
    print(f"[宽度] 最近5个交易日：")
    for dt in days[-5:]:
        b = out[dt]
        flag = " ⚠️背离" if b["divergence"] else ""
        print(f"    {dt}  上涨占比 {b['adv_ratio']:>5.0%}  指数 {b['idx_ret']:>+5.1f}%{flag}")
    if days and out[days[-1]]["divergence"]:
        print("[宽度] ⚠️ 最新交易日存在宽度背离：回测的'牛市'环境判定需打折！")
    print(f"✅ 已生成 {OUT_PATH}")


if __name__ == "__main__":
    main()
