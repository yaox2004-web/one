#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账本横向截面分析 (cross_section.py) v1.1
=================================================
【矿脉B】账本二次加工——同一交易日，305只股票互相对比。

纵向（账本已有）: 和自己过去20天比 → "今天和平时比"
横向（本脚本）  : 和全市场今天比     → "全市场都好就它掉队" ← 独立情报

核心输出（每有效交易日）:
  median     全市场各字段中位数（当日的"环境基准线"）
  stocks     每只股票各字段的截面分位（0=全市场最低, 1=最高）
  quant_env  量化环境指数（当日 quant_pct 均值，越高量化越活跃）

字段清单【动态检测】：v3.0 上线后 vwap_hold_ratio 等新字段自动纳入，无需改本脚本。
防脏数据：某字段当日有效样本 < MIN_STOCKS 时不算该字段分位。
v1.1 (2026-10-01): 新增 INDEX_CODES 样本级排除——指数迁移遗留记录(sh000001等)
                   不再参与个股截面（中位数/分位/quant_env 均受影响，虽仅~0.3%
                   但会持续污染 v3.0 行为指纹字段分布）。
                   样本级排除(INDEX_CODES)与字段级排除(EXCLUDE_FIELDS)各司其职。

只读账本、只写 data/analysis/cross_section.json（分析产物，可随时全量重算）。
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict, Counter

LEDGER_DIR = Path(__file__).parent.parent / "data" / "analysis" / "truth_ledger"
OUT_PATH = Path(__file__).parent.parent / "data" / "analysis" / "cross_section.json"

MIN_STOCKS = 50          # 有效交易日下限（过滤稀疏日，如9-10仅1条）
EXCLUDE_FIELDS = {"ver"}  # 字段级排除：版本号不是特征
INDEX_CODES = {"sh000001", "sz399001", "sz399006"}  # 样本级排除：指数不是个股（与 record_truth.py 口径一致）


def main():
    print("=" * 60)
    print("账本横向截面分析（矿脉B：同日全市场对比）")
    print("=" * 60)

    if not LEDGER_DIR.exists():
        print("[截面] ❌ 账本目录不存在，退出")
        return

    # ---- 载入全部分片 → {date: {code: entry}} ----
    by_date = defaultdict(dict)
    n_records = 0
    n_index_skipped = 0
    for fp in sorted(LEDGER_DIR.glob("*.json")):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                monthly = json.load(f)
        except Exception as e:
            print(f"[截面] 读取 {fp.name} 失败: {e}")
            continue
        for code, dmap in monthly.items():
            if code in INDEX_CODES:          # 样本级排除：指数不参与个股截面
                n_index_skipped += len(dmap)
                continue
            for d, entry in dmap.items():
                by_date[str(d)[:10]][code] = entry
                n_records += 1
    print(f"[截面] 账本载入 {n_records} 条记录，覆盖 {len(by_date)} 个日期")
    if n_index_skipped:
        print(f"[截面] 已排除指数记录 {n_index_skipped} 条（样本级守卫）")

    # ---- 动态检测数值字段（v3.0 新字段自动纳入）----
    field_counter = Counter()
    for stocks in by_date.values():
        for e in stocks.values():
            for k, v in e.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    field_counter[k] += 1
    fields = [k for k in field_counter if k not in EXCLUDE_FIELDS]
    print(f"[截面] 检测到数值字段: {fields}")

    # ---- 逐日计算截面分位 ----
    out = {}
    skipped = []
    for d in sorted(by_date):
        stocks = by_date[d]
        if len(stocks) < MIN_STOCKS:
            skipped.append(d)
            continue
        day = {"n": len(stocks), "median": {}, "stocks": {}}
        for fld in fields:
            vals = [(c, e[fld]) for c, e in stocks.items()
                    if isinstance(e.get(fld), (int, float))]
            if len(vals) < MIN_STOCKS:
                continue  # 防脏数据：样本不足不算该字段
            vs = sorted(v for _, v in vals)
            day["median"][fld] = round(vs[len(vs) // 2], 3)
            for c, v in vals:
                day["stocks"].setdefault(c, {})[fld] = round(
                    sum(1 for x in vs if x < v) / len(vs), 3)
        qenv = [e["quant_pct"] for e in stocks.values()
                if isinstance(e.get("quant_pct"), (int, float))]
        day["quant_env"] = round(float(np.mean(qenv)), 1) if qenv else None
        out[d] = day

    # ---- 写盘（原子写）----
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    tmp.replace(OUT_PATH)

    # ---- 控制台摘要 ----
    days = sorted(out)
    print(f"[截面] 有效交易日 {len(days)} 个，跳过稀疏日 {len(skipped)} 个: {skipped}")
    if days:
        last = days[-1]
        b = out[last]
        env_trend = [out[d]["quant_env"] for d in days[-5:] if out[d]["quant_env"] is not None]
        print(f"[截面] 最新 {last}: n={b['n']}, 量化环境指数={b['quant_env']}")
        print(f"        当日中位数: " + ", ".join(f"{k}={v}" for k, v in b["median"].items()))
        if len(env_trend) >= 2:
            print(f"        近5日量化环境: {env_trend} "
                  f"({'↗ 量化趋活跃' if env_trend[-1] > env_trend[0] else '↘ 量化趋沉寂'})")
    print(f"✅ 已生成 {OUT_PATH}")


if __name__ == "__main__":
    main()
