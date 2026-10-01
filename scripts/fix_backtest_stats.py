#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键修补回测统计口径 (fix_backtest_stats.py) v1.0
=================================================
修补对象: scripts/backtest_4d.py 的 winrate 统计块

修补内容（4处门槛 + 4处n注入）:
  1. 出表门槛 >= 5 → >= 30（5样本的胜率置信区间宽达55个百分点，是噪声不是情报）
  2. 每个胜率格子增加 "n": 样本数 字段（报告层可据此打"噪声警示"标签）

幂等设计: 已修补过的文件再跑一次不会有任何变化。
自检: 模式匹配数 != 4 时打印警告并以非零码退出，防止静默失败。
"""

import sys
from pathlib import Path

TARGETS = ["all_returns", "real_returns", "quant_returns", "unknown_returns"]
GATE_OLD = "if len({name}) >= 5:"
GATE_NEW = "if len({name}) >= 30:"
WINRATE_OLD = '"win_rate": round(sum(1 for r in {name} if r > 0) / len({name}) * 100, 1),'
NFIELD_NEW = '"n": len({name}), "win_rate": round(sum(1 for r in {name} if r > 0) / len({name}) * 100, 1),'


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

    # 自检：首次运行必须 4+4 全中；之后幂等运行 0+0 也算正常
    if (n_gate + n_field) == 0:
        already = GATE_NEW.format(name=TARGETS[0]) in text and '"n": len(all_returns),' in text
        if already:
            print("[补丁] ✅ 此前已修补过，本次无变化（幂等）")
        else:
            print("[补丁] ❌ 首次运行但零匹配——backtest_4d.py 结构与预期不符，需人工核对！")
            sys.exit(1)
    elif n_gate != 4 or n_field != 4:
        print("[补丁] ⚠️ 部分匹配成功——可能文件版本混杂，建议人工核对后再提交")
        sys.exit(1)
    else:
        print("[补丁] ✅ 修补完成: 4处门槛(5→30) + 4处n字段")


if __name__ == "__main__":
    main()
