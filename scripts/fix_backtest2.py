#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给已修补的 backtest_4d.py 再加一道日期归一化保险（幂等）
兜住紧凑格式 20260930 -> 2026-09-30"""
from pathlib import Path

SCRIPT = Path(__file__).parent / "backtest_4d.py"

def main():
    if not SCRIPT.exists():
        print("❌ 找不到 backtest_4d.py")
        return
    text = SCRIPT.read_text(encoding="utf-8")
    if "trade_date[4:6]" in text:
        print("✅ 已含日期归一化保险，跳过")
        return
    old = "    trade_date = str(trade_date)[:10]"
    new = (old + "\n"
           "    if len(trade_date) == 8 and trade_date.isdigit():\n"
           "        trade_date = f\"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}\"")
    if old not in text:
        print("⚠️ 未找到锚点（fix_backtest.py 可能还没跑？先跑那个）")
        return
    backup = SCRIPT.with_suffix(".py.bak2")
    backup.write_text(text, encoding="utf-8")
    text = text.replace(old, new, 1)
    try:
        compile(text, str(SCRIPT), "exec")
    except SyntaxError as e:
        print(f"❌ 语法失败已还原: {e}")
        SCRIPT.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        return
    SCRIPT.write_text(text, encoding="utf-8")
    print("🎉 日期归一化保险已加上（20260930 也能匹配账本了）")

if __name__ == "__main__":
    main()
