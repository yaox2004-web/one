#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键修补 backtest_4d.py（小白版，幂等可重复运行）
用法：python3 fix_backtest.py
自动备份原文件为 backtest_4d.py.bak，语法检查失败自动还原。"""
from pathlib import Path

SCRIPT = Path(__file__).parent / "backtest_4d.py"

NEW_FUNC = '''def is_real_money(market, code, trade_date):
    """真假判定 v2.2：只认账本（ver>=2），账本无记录=未知(None)。
    修复：日期双格式匹配（2026-09-30 / 09-30）+ 命中计数自证。"""
    trade_date = str(trade_date)[:10]
    cache_key = f"{market}{code}_{trade_date}"
    if cache_key in _real_money_cache:
        return _real_money_cache[cache_key]

    ledger = _load_ledger()
    key = f"{market}{code}"
    dates = ledger.get(key, {})
    # 双格式匹配：账本键可能是 "2026-09-30" 也可能是 "09-30"
    entry = dates.get(trade_date) or dates.get(trade_date[5:])

    if entry is not None:
        _ledger_hits[0] += 1
        # ver=1 旧口径不可信 -> 未知；ver>=2 可信
        if entry.get("ver", 1) < 2:
            result = (None, None)
        else:
            result = (entry.get("is_real"), entry.get("quant_pct", 0))
        _real_money_cache[cache_key] = result
        return result

    # 账本无此日记录 -> 未知（不再用1分钟数据兜底，口径唯一）
    result = (None, None)
    _real_money_cache[cache_key] = result
    return result

'''

def main():
    if not SCRIPT.exists():
        print(f"❌ 找不到 {SCRIPT}")
        print("   请把 fix_backtest.py 放在和 backtest_4d.py 同一个目录再运行")
        return

    text = SCRIPT.read_text(encoding="utf-8")

    # 幂等检查：已修补过就直接退出
    if "_ledger_hits" in text and "双格式匹配" in text:
        print("✅ backtest_4d.py 已修补过，无需重复修补")
        return

    # 备份
    backup = SCRIPT.with_suffix(".py.bak")
    backup.write_text(text, encoding="utf-8")
    print(f"💾 已备份原文件 -> {backup.name}")

    ok = True

    # ---- 1/4 添加命中计数器 ----
    if "_ledger_cache = None" in text:
        text = text.replace("_ledger_cache = None",
                            "_ledger_cache = None\n_ledger_hits = [0]", 1)
        print("  ✔ 1/4 添加命中计数器")
    else:
        print("  ✘ 1/4 未找到计数器插入点（文件结构不符？）")
        ok = False

    # ---- 2/4 整体替换 is_real_money 函数 ----
    start = text.find("def is_real_money")
    end = text.find("def get_atr_threshold")
    if start != -1 and end != -1 and start < end:
        text = text[:start] + NEW_FUNC + text[end:]
        print("  ✔ 2/4 替换 is_real_money（只认账本，删1分钟兜底，加双格式匹配）")
    else:
        print("  ✘ 2/4 未找到 is_real_money 函数边界")
        ok = False

    # ---- 3/4 放宽主循环上界 ----
    old3 = "for i in range(START_IDX, n - 60 - MAX_WAIT_DAYS - 2):"
    new3 = "for i in range(START_IDX, n - MAX_WAIT_DAYS - 2):"
    if old3 in text:
        text = text.replace(old3, new3, 1)
        print("  ✔ 3/4 放宽主循环上界（最近一个季度的信号进入回测）")
    else:
        print("  ⚠ 3/4 未找到主循环行（可能已改过），跳过")

    # ---- 4/4 收尾处加账本命中自证 ----
    marker4 = 'print("\\n" + "=" * 70)'
    idx4 = text.find(marker4)
    if idx4 != -1:
        inject = ('print(f"\\n[账本自证] 查询 {len(_real_money_cache)} 次，'
                  '命中判定 {_ledger_hits[0]} 次")\n    ')
        text = text[:idx4] + inject + text[idx4:]
        print("  ✔ 4/4 添加账本命中自证日志")
    else:
        print("  ⚠ 4/4 未找到收尾插入点，跳过")

    # ---- 语法检查，失败自动还原 ----
    try:
        compile(text, str(SCRIPT), "exec")
        print("🔍 语法检查通过")
    except SyntaxError as e:
        print(f"❌ 语法检查失败: {e}，已还原备份，原文件未受影响")
        SCRIPT.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        return

    if ok:
        SCRIPT.write_text(text, encoding="utf-8")
        print("\n🎉 修补完成！可以重跑回测了")
        print("   验收看两处：日志里的 [账本自证] 命中次数 > 0；")
        print("   winrate.json 出现 _真金 / _量化 后缀的分组")
    else:
        print("\n❌ 修补未完成，原文件已还原为备份内容，请把本输出发给助手")

if __name__ == "__main__":
    main()
