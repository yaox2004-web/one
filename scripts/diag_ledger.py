#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账本法医诊断器（diag_ledger.py）
================================
一次性统计账本所有条目的 ver / verdict / is_real 分布 + 日期范围 + 样本，
用于定位"回测命中0次"的根因。只读不改，随便跑。
"""

import json
from pathlib import Path
from collections import Counter

LEDGER_DIR = Path(__file__).parent.parent / "data" / "analysis" / "truth_ledger"

ver_counter = Counter()
verdict_counter = Counter()
is_real_counter = Counter()
date_counter = Counter()
total = 0
sample = None

print("=" * 60)
print("账本法医诊断")
print("=" * 60)

files = sorted(LEDGER_DIR.glob("*.json"))
print(f"账本分片文件: {[f.name for f in files]}")

for path in files:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [跳过] {path.name}: {e}")
        continue
    for code, stock in data.items():
        if not isinstance(stock, dict):
            continue
        for date, entry in stock.items():
            if not isinstance(entry, dict):
                continue
            total += 1
            ver_counter[str(entry.get("ver", "无ver字段"))] += 1
            verdict_counter[str(entry.get("verdict", "无verdict字段"))] += 1
            is_real_counter[str(entry.get("is_real", "无is_real字段"))] += 1
            date_counter[str(date)[:10]] += 1
            if sample is None:
                sample = (path.name, code, date, entry)

print(f"\n总条目数: {total}")
print(f"\n[ver 分布]      → {dict(ver_counter)}")
print(f"[verdict 分布]  → {dict(verdict_counter)}")
print(f"[is_real 分布]  → {dict(is_real_counter)}")
print(f"\n[日期分布] → {dict(sorted(date_counter.items()))}")

if sample:
    fname, code, date, entry = sample
    print(f"\n[样本条目] 文件={fname} 股票={code} 日期={date}")
    for k, v in entry.items():
        print(f"    {k} = {v!r}")
else:
    print("\n[!] 账本为空或结构异常！")

print("\n" + "=" * 60)
print("判读指南：")
print("  若 ver 分布全是 '无ver字段' 或 '1' → 旧口径封锁是主因，")
print("     下一步我会给对应的修补脚本")
print("  若 ver=2 且 verdict 有值 → 账本没问题，问题在回测匹配逻辑，")
print("     下一步需要修 backtest_4d.py 的 is_real_money")
print("=" * 60)
