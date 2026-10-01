#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键修补回测统计口径 (fix_backtest_stats.py) v1.1
=================================================
修补对象: scripts/backtest_4d.py 的 winrate 统计块

修补内容（4处门槛 + 4处n注入）:
  1. 出表门槛 >= 5 → >= 30（5样本的胜率置信区间宽达55个百分点，是噪声不是情报）
  2. 每个胜率格子增加 "n": 样本数 字段（报告层可据此打"噪声警示"标签）

幂等设计: 已修补过的文件再跑一次不会有任何变化。

v1.1 (2026-10-01) 修复自检误报:
  v1.0 自检只看"本次替换计数"，遇到半修补状态的文件（如门槛已补、
  n字段未补）时，明明把活干完了却因计数非4+4而 exit(1) 误报失败。
  v1.1 改为【终态校验】: 修补后直接验证目标文件是否包含全部
  4个新门槛 + 4个n字段——在终态即成功，与本次替换了几处无关。
  仅当终态不完整时才报错退出，防止静默失败的初衷不变。
"""

import sys
from pathlib import Path

TARGETS = ["all_returns", "real_returns", "quant_returns", "unknown_returns"]
GATE_OLD = "if len({name}) >= 5:"
GATE_NEW = "if len({name}) >= 30:"
WINRATE_OLD = '"win_rate": round(sum(1 for r in {name} if r > 0) / len({name}) * 100, 1),'
NFIELD_NEW = '"n": len({name}), "win_rate": round(sum(1 for r in {name} if r > 0) / len({name}) * 100, 1),'


def final_state_ok(text):
    """终态校验: 全部4个新门槛 + 全部4个n字段都在 = 修补完成"""
    for name in TARGETS:
        if GATE_NEW.format(name=name) not in text:
            return False
        if '"n": len(%s),' % name not in text:
            return False
    return True


def main():
    # 支持在 scripts/ 目录内直接运行
    target = Path(__file__).parent / "backtest_4d.py"
    if not target.exists():
        print(f"[补丁] ❌ 找不到 {target}")
        sys.exit(1)

    text = target.read_text(encoding="utf-8")

    n_gate = 0
    for name in TARGETS:
        old = GATE_OLD.format(name=name)
        new = GATE_NEW.format(name=name)
        if old in text:
            text = text.replace(old, new, 1)
            n_gate += 1
        elif new in text:
            print(f"[补丁] 门槛已是 >= 30（跳过）: {name}")
        else:
            print(f"[补丁] ⚠️ 未找到门槛模式: {name}（文件结构可能已变，人工检查）")

    n_field = 0
    for name in TARGETS:
        old = WINRATE_OLD.format(name=name)
        new = NFIELD_NEW.format(name=name)
        if old in text:
            text = text.replace(old, new, 1)
            n_field += 1
        elif new in text:
            print(f"[补丁] n 字段已注入（跳过）: {name}")

    target.write_text(text, encoding="utf-8")
    print(f"[补丁] 门槛替换 {n_gate} 处, n 注入 {n_field} 处")

    # v1.1 自检：只认终态，不认过程计数。
    # 无论本次替换了几处（4+4 / 0+0 / 半修补的0+4等），
    # 只要目标文件终态完整即为成功。
    if final_state_ok(text):
        if n_gate + n_field > 0:
            print(f"[补丁] ✅ 修补完成: 本次门槛{n_gate}处 + n字段{n_field}处，终态校验通过")
        else:
            print("[补丁] ✅ 此前已修补过，本次无变化（幂等），终态校验通过")
    else:
        print("[补丁] ❌ 终态校验失败——backtest_4d.py 补后仍不完整，结构与预期不符，需人工核对！")
        sys.exit(1)


if __name__ == "__main__":
    main()
