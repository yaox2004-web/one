#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账本心跳检查 (ledger_heartbeat.py) v1.0
=================================================
防止"管道静默死亡"：数据源接口变更、1分钟拉取全空、记账悄悄失效——
这些情况以前只会让工作流"无变化"地绿着跑完。

真相锚点: data/kline/sh/sh000001.json 的最新日期
         （指数日线每天都拉，它有而账本没有 = 账本断更）

判定:
  账本最新日期 >= 指数最新日期 → ✅ 放行 (exit 0)
  账本为空 / 落后于指数        → ❌ exit 1 → 工作流标红 → Actions 自动发告警邮件

注意: 周末/节假日指数日线不会有新日期，此时账本也不该有新日期，
     两边同步旧 → 依然放行。所以本检查无假期误报。
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
LEDGER_DIR = DATA_DIR / "analysis" / "truth_ledger"
INDEX_PATH = DATA_DIR / "kline" / "sh" / "sh000001.json"


def main():
    # ---- 真相锚：指数日历最新日 ----
    try:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            idx_kl = json.load(f).get('klines', [])
        idx_last = str(idx_kl[-1][0])[:10]
    except Exception as e:
        print(f"[心跳] ❌ 指数日线读取失败（数据源可能故障）: {e}")
        sys.exit(1)

    # ---- 账本最新日 ----
    ledger_last = None
    if LEDGER_DIR.exists():
        for fp in sorted(LEDGER_DIR.glob("*.json")):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    monthly = json.load(f)
            except Exception:
                continue
            for code, dmap in monthly.items():
                if dmap:
                    d = max(str(d)[:10] for d in dmap.keys())
                    if ledger_last is None or d > ledger_last:
                        ledger_last = d

    print(f"[心跳] 指数最新日: {idx_last}")
    print(f"[心跳] 账本最新日: {ledger_last}")

    if ledger_last is None:
        print("[心跳] ❌ 账本为空或全部不可读——管道已死，人工介入！")
        sys.exit(1)
    if ledger_last < idx_last:
        print(f"[心跳] ❌ 账本落后指数 {idx_last}——记账链路断更，人工介入！")
        sys.exit(1)

    print("[心跳] ✅ 心跳正常")


if __name__ == "__main__":
    main()
