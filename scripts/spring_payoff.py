#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫信号兑现率统计 v0.1  (Phase 5)
======================================================================
纯读取型脚本:
  读: data/analysis/wyckoff_events.json          (事件清单)
      data/kline/{sh,sz,bj}/{code}.json          (全市场日线)
      日线格式: {"name":..., "klines": [[日期,开,收,高,低,量], ...]}
  写: data/analysis/payoff_report.json           (兑现率报告)

统计口径 (v0.1):
  - 胜 = T+N 收盘价 > 事件日收盘价
  - 统计窗口: T+1 / T+3 / T+5
  - 分组: Spring全体 / Spring(链score>=9 / <9) / SOS全体
  - 样本数 < 30 的分组标注"样本不足"
======================================================================
"""

import json
import os
import sys
from collections import defaultdict

EVENTS_FILE = "data/analysis/wyckoff_events.json"
KLINE_DIR   = "data/kline"
OUTPUT_FILE = "data/analysis/payoff_report.json"

WINDOWS   = [1, 3, 5]
MIN_SAMPLE = 30
CHAIN_SCORE_THRESHOLD = 9


# ----------------------------------------------------------------------
# 事件读取（自动兼容多种结构）
# ----------------------------------------------------------------------
def load_events():
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    events = []

    def harvest(payload, default_code=""):
        """从一个事件列表/字典里尽可能收集事件"""
        if isinstance(payload, dict):
            # 可能是单个事件
            t = payload.get("type") or payload.get("event") or payload.get("event_type")
            if t:
                return [_norm_event(payload, payload.get("code") or default_code)]
            # 可能是 {"events": [...]} 或按类型分组 {"Spring": [...]}
            out = []
            for key, val in payload.items():
                if isinstance(val, list):
                    for ev in val:
                        if isinstance(ev, dict):
                            ev.setdefault("type", key) if key in (
                                "SC", "AR", "ST", "Spring", "SOS", "LPS",
                                "BC", "UTAD", "SOW") else None
                            out.extend(harvest(ev, default_code))
                elif isinstance(val, dict):
                    out.extend(harvest(val, default_code))
            return out
        elif isinstance(payload, list):
            out = []
            for ev in payload:
                out.extend(harvest(ev, default_code))
            return out
        return []

    if isinstance(raw, dict):
        # 结构A: 按股票分组 {"sh600547": {...}, ...}
        if all(isinstance(v, (dict, list)) for v in raw.values()) and not any(
                k in raw for k in ("events", "groups")):
            for code, payload in raw.items():
                events.extend(harvest(payload, code))
        else:
            events.extend(harvest(raw))
    elif isinstance(raw, list):
        events.extend(harvest(raw))

    print(f"[事件] 共解析出 {len(events)} 个事件")
    if events:
        types = {}
        for e in events:
            types[e["type"]] = types.get(e["type"], 0) + 1
        print(f"[事件] 类型分布: {dict(sorted(types.items(), key=lambda x: -x[1]))}")
    return events


def _norm_event(ev, code):
    etype = ev.get("type") or ev.get("event") or ev.get("event_type") or "未知"
    edate = ev.get("date") or ev.get("event_date") or ev.get("date_str") or ""
    score = ev.get("chain_score") or ev.get("score") or 0
    return {"code": str(code), "type": str(etype), "date": str(edate)[:10], "score": score}


# ----------------------------------------------------------------------
# K线读取（真实格式: data/kline/{sh,sz,bj}/{code}.json）
#   klines 元素: [日期, 开, 收, 高, 低, 量]，日期可能带时分秒
# ----------------------------------------------------------------------
def load_kline(code):
    path = os.path.join(KLINE_DIR, code[:2], code + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    rows = []
    for k in data.get("klines", []):
        if isinstance(k, (list, tuple)) and len(k) >= 3:
            d = str(k[0])[:10]           # 取 YYYY-MM-DD
            c = float(k[2])              # 收盘价在第3位
            rows.append((d, c))
    rows.sort(key=lambda x: x[0])
    return rows


def payoff_of(kline, event_date, n):
    dates = [d for d, _ in kline]
    if event_date not in dates:
        return None
    idx = dates.index(event_date)
    if idx + n >= len(kline):
        return None
    c0 = kline[idx][1]
    cn = kline[idx + n][1]
    if c0 <= 0:
        return None
    return (cn - c0) / c0


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main():
    print("=" * 70)
    print("威科夫信号兑现率统计 v0.1 (Phase 5)")
    print("=" * 70)

    events = load_events()

    targets = {"Spring", "SOS"}
    events = [e for e in events if e["type"] in targets]
    print(f"[过滤] 目标信号(Spring/SOS)共 {len(events)} 个")

    results = defaultdict(lambda: defaultdict(list))
    missing_kline, missing_date, no_future = set(), 0, 0

    for ev in events:
        kl = load_kline(ev["code"])
        if not kl:
            missing_kline.add(ev["code"])
            continue

        if ev["type"] == "Spring":
            groups = ["Spring_全体",
                      "Spring_链score>=9" if ev["score"] >= CHAIN_SCORE_THRESHOLD
                      else "Spring_链score<9"]
        else:
            groups = ["SOS_全体"]

        for g in groups:
            for n in WINDOWS:
                r = payoff_of(kl, ev["date"], n)
                if r is not None:
                    results[g][n].append(r)

    if missing_kline:
        print(f"[警告] {len(missing_kline)} 只股票找不到K线文件 "
              f"(示例: {sorted(missing_kline)[:3]})")

    # ---- 汇总 ---------------------------------------------------------
    report = {"meta": {"window": WINDOWS,
                       "win_def": "T+N收盘>事件日收盘",
                       "min_sample": MIN_SAMPLE},
              "groups": {}}

    print()
    print("=" * 78)
    print(f"{'分组':<20}{'样本':>6}{'T+1胜率':>10}{'T+3胜率':>10}"
          f"{'T+5胜率':>10}{'T+5均收益':>12}")
    print("-" * 78)

    for g in sorted(results.keys()):
        entry = {}
        n0 = len(results[g][WINDOWS[0]])
        line = f"{g:<20}{n0:>6}"
        for n in WINDOWS:
            rets = results[g][n]
            if rets:
                win = sum(1 for r in rets if r > 0) / len(rets)
                entry[f"T{n}_n"] = len(rets)
                entry[f"T{n}_winrate"] = round(win * 100, 1)
                line += f"{win*100:>9.1f}%"
            else:
                line += f"{'--':>10}"
        rets5 = results[g][5]
        if rets5:
            avg5 = sum(rets5) / len(rets5)
            entry["T5_avg_return"] = round(avg5 * 100, 2)
            line += f"{avg5*100:>11.2f}%"
        if n0 < MIN_SAMPLE:
            entry["note"] = "样本不足"
            line += "  (样本不足)"
        print(line)
        report["groups"][g] = entry

    print("=" * 78)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成: {OUTPUT_FILE}")

    if not report["groups"]:
        print("⚠️  校验失败: 没有任何分组产出——事件结构未解析成功，需对照日志调整")
        sys.exit(1)
    print(f"✅ 终态校验通过: 共 {len(report['groups'])} 个分组, 报告已落盘")


if __name__ == "__main__":
    main()
