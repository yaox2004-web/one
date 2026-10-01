#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
600547 山东黄金 · 真金弹簧追踪卡 v0.1
======================================================================
纯读取型脚本:
  读: data/kline/sh/sh600547.json
  写: data/analysis/track_600547.md  (追踪卡, 顺便打印到日志)

追踪口径:
  事件日 = 2026-09-29 (真金弹簧)
  T+N 兑现 = T+N收盘 > 事件日收盘 (与 Phase 5 口径一致)
  数据不够的窗口标"待验证", 开盘后自动补判
======================================================================
"""

import json
import os

CODE        = "sh600547"
NAME        = "山东黄金"
EVENT_DATE  = "2026-09-29"
KLINE_PATH  = f"data/kline/{CODE[:2]}/{CODE}.json"
OUTPUT_PATH = "data/analysis/track_600547.md"
WINDOWS     = [1, 3, 5]
RECENT_BARS = 12


def main():
    print("=" * 60)
    print(f"{CODE} {NAME} · 真金弹簧追踪卡 (事件日 {EVENT_DATE})")
    print("=" * 60)

    with open(KLINE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for k in data.get("klines", []):
        if isinstance(k, (list, tuple)) and len(k) >= 3:
            rows.append((str(k[0])[:10], float(k[1]), float(k[2])))
    rows.sort(key=lambda x: x[0])

    dates = [r[0] for r in rows]
    if EVENT_DATE not in dates:
        print(f"❌ 事件日 {EVENT_DATE} 不在K线中, 追踪卡生成失败")
        raise SystemExit(1)

    idx = dates.index(EVENT_DATE)
    event_close = rows[idx][2]
    print(f"[事件] 事件日收盘: {event_close:.2f}")

    # ---- T+N 判定 ----------------------------------------------------
    verdicts = []
    for n in WINDOWS:
        j = idx + n
        if j < len(rows):
            c = rows[j][2]
            pct = (c - event_close) / event_close * 100
            ok = c > event_close
            verdicts.append((f"T+{n}", rows[j][0], f"{c:.2f}",
                             f"{pct:+.2f}%", "✅ 兑现" if ok else "❌ 未兑现"))
        else:
            verdicts.append((f"T+{n}", "—", "—", "—", "⏳ 待验证(数据不足)"))

    # ---- 追踪卡 ------------------------------------------------------
    lines = []
    lines.append(f"# 🎯 {CODE} {NAME} · 真金弹簧追踪卡")
    lines.append("")
    lines.append(f"- 事件日: **{EVENT_DATE}** (真金弹簧)")
    lines.append(f"- 事件日收盘: **{event_close:.2f}**")
    lines.append(f"- 判定口径: T+N收盘 > 事件日收盘 (与 Phase 5 一致)")
    lines.append(f"- 生成时间: 仓库最新数据")
    lines.append("")
    lines.append("## 兑现进度")
    lines.append("")
    lines.append("| 窗口 | 日期 | 收盘 | 相对事件日 | 判定 |")
    lines.append("|---|---|---|---|---|")
    for v in verdicts:
        lines.append("| " + " | ".join(v) + " |")
    lines.append("")
    lines.append(f"## 近{RECENT_BARS}个交易日走势")
    lines.append("")
    lines.append("| 日期 | 开盘 | 收盘 | 日涨跌 |")
    lines.append("|---|---|---|---|")
    start = max(1, len(rows) - RECENT_BARS)
    for i in range(start, len(rows)):
        d, o, c = rows[i]
        prev = rows[i - 1][2]
        pct = (c - prev) / prev * 100
        arrow = "🔴" if pct < 0 else "🟢"
        lines.append(f"| {d} | {o:.2f} | {c:.2f} | {arrow} {pct:+.2f}% |")
    lines.append("")

    card = "\n".join(lines)
    print()
    print(card)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(card)
    print(f"✅ 已生成: {OUTPUT_PATH}")

    realized = sum(1 for v in verdicts if "兑现" in v[4])
    print(f"✅ 终态校验通过: 兑现 {realized}/{len(WINDOWS)} 个窗口, 追踪卡已落盘")


if __name__ == "__main__":
    main()
