#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账本版本迁移器（migrate_ledger_ver.py）
========================================
给所有缺少 ver 字段的存量记录补发 ver=2 身份证。
- 幂等：已有 ver 的记录自动跳过，重复跑无副作用
- 安全：每个分片文件首次修改前自动备份 .bak
- 透明：加 ver_source 标记，说明这是迁移来的
只跑一次即可，之后永远跳过。
"""

import json
import shutil
from pathlib import Path

LEDGER_DIR = Path(__file__).parent.parent / "data" / "analysis" / "truth_ledger"

print("=" * 60)
print("账本版本迁移：补发 ver=2 身份证")
print("=" * 60)

if not LEDGER_DIR.exists():
    print(f"[!] 账本目录不存在: {LEDGER_DIR}")
    exit(0)

files = sorted(LEDGER_DIR.glob("*.json"))
if not files:
    print("[!] 没有找到账本分片文件")
    exit(0)

total_migrated = 0
total_skipped = 0

for path in files:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [跳过] {path.name}: {e}")
        continue

    migrated = 0
    skipped = 0
    for code, stock in data.items():
        if not isinstance(stock, dict):
            continue
        for date, entry in stock.items():
            if not isinstance(entry, dict):
                continue
            if "ver" in entry:
                skipped += 1
                continue
            # 补发身份证：is_real 字段可信（True/False 均有明确判定）
            entry["ver"] = 2
            entry["ver_source"] = "migrate_v1_20261001"
            migrated += 1

    if migrated == 0:
        print(f"  {path.name}: 全部已有 ver（跳过 {skipped} 条），无需迁移")
        total_skipped += skipped
        continue

    # 首次修改前备份
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"  [备份] {path.name} -> {bak.name}")

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"  {path.name}: 迁移 {migrated} 条，跳过 {skipped} 条")
    total_migrated += migrated
    total_skipped += skipped

print("\n" + "=" * 60)
print(f"迁移完成：补发 {total_migrated} 条，原有 ver 跳过 {total_skipped} 条")
if total_migrated > 0:
    print(">>> 下一步：重跑回测，[账本自证] 命中数应 > 0")
else:
    print(">>> 无需迁移（可能已迁移过）")
print("=" * 60)
