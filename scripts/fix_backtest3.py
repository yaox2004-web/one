#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_backtest3.py — 第三次修补：让回测"够得着"账本
=====================================================
根因（法医结论）：
  主循环上界 n - MAX_WAIT_DAYS - 2 把最近13个交易日排除在回测之外，
  而账本的密集覆盖（9-21~9-30）100% 落在这个盲区里
  → 查询 155697 次、命中 0 次。

修补内容（全部幂等，重复跑自动跳过）：
  1/3 主循环上界放宽到 n：最近的信号也进入回测
     （下游 check_pullback_buy / sell 都有边界保护，不会越界崩溃；
       近端未完成的交易会被现有守卫自然跳过）
  2/3 账本加载时日期键归一化（"2026-09-30 15:00:00" → "2026-09-30"），
     兜住账本键带时间戳的形态（9-10/9-11 的稀疏条目可能就是这种）
  3/3 [账本自证] 升级：输出 命中后 真金/量化/未知 三分类明细
"""

from pathlib import Path

SCRIPT = Path(__file__).parent / "backtest_4d.py"
BAK = Path(__file__).parent / "backtest_4d.py.bak3"

text = SCRIPT.read_text(encoding="utf-8")
changed = []

# ============================================================
# 1/3 主循环上界：n - MAX_WAIT_DAYS - 2  →  n
# ============================================================
OLD_LOOP = "for i in range(START_IDX, n - MAX_WAIT_DAYS - 2):"
NEW_LOOP = "for i in range(START_IDX, n):  # fix3: 放宽上界，最近信号进回测（账本在近端）"
if "fix3: 放宽上界" in text:
    print("✅ 1/3 主循环上界已修补过，跳过")
elif OLD_LOOP in text:
    text = text.replace(OLD_LOOP, NEW_LOOP)
    changed.append("主循环上界放宽到n")
    print("✔ 1/3 主循环上界已放宽（最近13个交易日进入回测）")
else:
    print("⚠ 1/3 未找到主循环原句，请人工检查")

# ============================================================
# 2/3 账本加载：日期键归一化（剥时间戳）
# ============================================================
OLD_LOAD = """            for code, dates in monthly.items():
                if code not in _ledger_cache:
                    _ledger_cache[code] = {}
                _ledger_cache[code].update(dates)"""
NEW_LOAD = """            for code, dates in monthly.items():
                if code not in _ledger_cache:
                    _ledger_cache[code] = {}
                # fix3: 日期键归一化，剥掉可能的时间戳（"2026-09-30 15:00" → "2026-09-30"）
                _ledger_cache[code].update({str(d)[:10]: v for d, v in dates.items()})"""
if "fix3: 日期键归一化" in text:
    print("✅ 2/3 账本日期键归一化已修补过，跳过")
elif OLD_LOAD in text:
    text = text.replace(OLD_LOAD, NEW_LOAD)
    changed.append("账本日期键归一化")
    print("✔ 2/3 账本日期键已归一化（兼容时间戳键形态）")
else:
    print("⚠ 2/3 未找到账本加载片段，请人工检查")

# ============================================================
# 3/3 账本自证升级：三分类明细
# ============================================================
OLD_HITS = "_ledger_hits = [0]"
NEW_HITS = """_ledger_hits = [0]
_ledger_breakdown = {"真金": 0, "量化": 0, "未知": 0}  # fix3: 命中分类自证"""
if "_ledger_breakdown" in text:
    print("✅ 3/3a 分类计数器已修补过，跳过")
elif OLD_HITS in text:
    text = text.replace(OLD_HITS, NEW_HITS, 1)
    changed.append("分类计数器")
    print("✔ 3/3a 分类计数器已添加")
else:
    print("⚠ 3/3a 未找到计数器定义，请人工检查")

OLD_BRANCH = """    if entry is not None:
        _ledger_hits[0] += 1
        # ver=1 旧口径不可信 -> 未知；ver>=2 可信
        if entry.get("ver", 1) < 2:
            result = (None, None)
        else:
            result = (entry.get("is_real"), entry.get("quant_pct", 0))"""
NEW_BRANCH = """    if entry is not None:
        _ledger_hits[0] += 1
        # ver=1 旧口径不可信 -> 未知；ver>=2 可信
        if entry.get("ver", 1) < 2:
            result = (None, None)
            _ledger_breakdown["未知"] += 1  # fix3
        else:
            result = (entry.get("is_real"), entry.get("quant_pct", 0))
            if result[0] is True:
                _ledger_breakdown["真金"] += 1  # fix3
            elif result[0] is False:
                _ledger_breakdown["量化"] += 1  # fix3
            else:
                _ledger_breakdown["未知"] += 1  # fix3"""
if "_ledger_breakdown[\"真金\"] += 1" in text:
    print("✅ 3/3b 命中分类累加已修补过，跳过")
elif OLD_BRANCH in text:
    text = text.replace(OLD_BRANCH, NEW_BRANCH, 1)
    changed.append("命中分类累加")
    print("✔ 3/3b 命中分类累加已添加")
else:
    print("⚠ 3/3b 未找到命中分支，请人工检查")

OLD_PRINT = 'print(f"\\n[账本自证] 查询 {len(_real_money_cache)} 次，命中判定 {_ledger_hits[0]} 次")'
NEW_PRINT = OLD_PRINT + '\n    print(f"[账本自证] 命中分类：真金 {_ledger_breakdown[\'真金\']} / 量化 {_ledger_breakdown[\'量化\']} / 未知 {_ledger_breakdown[\'未知\']}")  # fix3'
if "命中分类：真金" in text:
    print("✅ 3/3c 自证明细打印已修补过，跳过")
elif OLD_PRINT in text:
    text = text.replace(OLD_PRINT, NEW_PRINT, 1)
    changed.append("自证明细打印")
    print("✔ 3/3c 自证明细打印已添加")
else:
    print("⚠ 3/3c 未找到自证打印行，请人工检查")

# ============================================================
# 写回 + 备份 + 语法检查
# ============================================================
if not changed:
    print("\n🎉 全部已修补过，无需改动")
    exit(0)

if not BAK.exists():
    import shutil
    shutil.copy2(SCRIPT, BAK)
    print(f"\n💾 已备份原文件 -> {BAK.name}")

compile(text, str(SCRIPT), "exec")  # 语法检查，失败会抛异常不写文件
SCRIPT.write_text(text, encoding="utf-8")
print("🔍 语法检查通过")
print(f"\n🎉 fix3 完成！本次改动：{len(changed)} 项 → {changed}")
print("   重跑回测，[账本自证] 命中数应跳到数百次")
