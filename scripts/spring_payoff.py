#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫信号兑现率统计 v0.3  (Phase 5)
======================================================================
真实事件格式（2026-10-01 实测确认）:
  {"股票代码": {"日期": {"events": [...], "spring_real": .., "quant_pct": ..}}}
链文件格式:
  {"股票代码": {"日期": {"score": 9, "type": "吸筹", "chain": [...], ...}}}

纯读取型脚本:
  读: data/analysis/wyckoff_events.json
      data/analysis/wyckoff_chain.json
      data/kline/{sh,sz,bj}/{code}.json
  写: data/analysis/payoff_report.json

统计口径:
  - 胜 = T+N 收盘 > 事件日收盘
  - 窗口: T+1 / T+3 / T+5
  - 分组:
      Spring_全体
      Spring_完整链   (Spring后90天内该股出现score>=9的完整吸筹链)
      Spring_非完整链
      Spring_真金     (账本双重确认, 历史不可回测, 攒样本)
      SOS_全体
  - 样本 < 30 标注"样本不足"
======================================================================
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

EVENTS_FILE = "data/analysis/wyckoff_events.json"
CHAIN_FILE  = "data/analysis/wyckoff_chain.json"
KLINE_DIR   = "data/kline"
OUTPUT_FILE = "data/analysis/payoff_report.json"

WINDOWS    = [1, 3, 5]
MIN_SAMPLE = 30
CHAIN_LINK_DAYS  = 90   # Spring后多少自然日内出现完整链算"链内弹簧"
CHAIN_MIN_SCORE  = 9


# ----------------------------------------------------------------------
# 事件读取
# ----------------------------------------------------------------------
def load_events():
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    events = []
    for code, dates in raw.items():
        if not isinstance(dates, dict):
            continue
        for date, payload in dates.items():
            if not isinstance(payload, dict):
                continue
            ev_types = payload.get("events", [])
            spring_real = payload.get("spring_real")
            quant_pct = payload.get("quant_pct")
            for t in ev_types:
                events.append({
                    "code": str(code),
                    "type": str(t),
                    "date": str(date)[:10],
                    "spring_real": spring_real,
                    "quant_pct": quant_pct,
                })

    print(f"[事件] 共解析出 {len(events)} 个事件")
    real_cnt = sum(1 for e in events
                   if e["type"] == "Spring" and e["spring_real"])
    print(f"[事件] Spring中真金弹簧(spring_real=true): {real_cnt} 个")
    return events


# ----------------------------------------------------------------------
# 链读取: {code: [(日期, score), ...] 按日期升序}
# ----------------------------------------------------------------------
def load_chain_scores():
    if not os.path.exists(CHAIN_FILE):
        print(f"[链] 未找到 {CHAIN_FILE}, 跳过完整链分组")
        return {}
    with open(CHAIN_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    chains = {}
    for code, dates in raw.items():
        if not isinstance(dates, dict):
            continue
        recs = []
        for d, payload in dates.items():
            if isinstance(payload, dict) and "score" in payload:
                recs.append((str(d)[:10], float(payload["score"])))
        recs.sort(key=lambda x: x[0])
        if recs:
            chains[str(code)] = recs
    print(f"[链] 已加载 {len(chains)} 只股票的链记录")
    return chains


def chain_completed_after(chain_recs, event_date,
                          days=CHAIN_LINK_DAYS, min_score=CHAIN_MIN_SCORE):
    """Spring事件日之后 days 自然日内, 该股是否出现 score>=min_score 的链记录"""
    try:
        d0 = datetime.strptime(event_date, "%Y-%m-%d")
    except ValueError:
        return False
    limit = (d0 + timedelta(days=days)).strftime("%Y-%m-%d")
    for d, s in chain_recs:
        if d > limit:
            break
        if d >= event_date and s >= min_score:
            return True
    return False


# ----------------------------------------------------------------------
# K线读取: {"name":..,"klines":[[日期,开,收,高,低,量],...]}
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
            rows.append((str(k[0])[:10], float(k[1]), float(k[2])))
    rows.sort(key=lambda x: x[0])
    return rows


def payoff_of(kline, event_date, n):
    dates = [d for d, _, _ in kline]
    if event_date not in dates:
        return None
    idx = dates.index(event_date)
    if idx + n >= len(kline):
        return None
    c0 = kline[idx][2]
    cn = kline[idx + n][2]
    if c0 <= 0:
        return None
    return (cn - c0) / c0


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main():
    print("=" * 70)
    print("威科夫信号兑现率统计 v0.3 (Phase 5)")
    print("=" * 70)

    events = load_events()
    chains = load_chain_scores()

    targets = {"Spring", "SOS"}
    events = [e for e in events if e["type"] in targets]
    print(f"[过滤] 目标信号(Spring/SOS)共 {len(events)} 个")

    results = defaultdict(lambda: defaultdict(list))
    missing_kline = set()
    linked_count = 0

    for ev in events:
        kl = load_kline(ev["code"])
        if not kl:
            missing_kline.add(ev["code"])
            continue

        if ev["type"] == "Spring":
            recs = chains.get(ev["code"], [])
            linked = chain_completed_after(recs, ev["date"])
            if linked:
                linked_count += 1
            groups = ["Spring_全体",
                      "Spring_完整链" if linked else "Spring_非完整链"]
            if ev["spring_real"]:
                groups.append("Spring_真金")
        else:
            groups = ["SOS_全体"]

        for g in groups:
            for n in WINDOWS:
                r = payoff_of(kl, ev["date"], n)
                if r is not None:
                    results[g][n].append(r)

    print(f"[链] Spring中属于完整链(score>={CHAIN_MIN_SCORE}, "
          f"后{CHAIN_LINK_DAYS}天内确认): {linked_count} 个")
    if missing_kline:
        print(f"[警告] {len(missing_kline)} 只股票找不到K线文件 "
              f"(示例: {sorted(missing_kline)[:3]})")

    # ---- 汇总 ---------------------------------------------------------
    report = {"meta": {"window": WINDOWS,
                       "win_def": "T+N收盘>事件日收盘",
                       "min_sample": MIN_SAMPLE,
                       "chain_link_days": CHAIN_LINK_DAYS,
                       "chain_min_score": CHAIN_MIN_SCORE},
              "groups": {}}

    print()
    print("=" * 80)
    print(f"{'分组':<20}{'样本':>8}{'T+1胜率':>10}{'T+3胜率':>10}"
          f"{'T+5胜率':>10}{'T+5均收益':>12}")
    print("-" * 80)

    for g in sorted(results.keys()):
        entry = {}
        n0 = len(results[g][WINDOWS[0]])
        line = f"{g:<20}{n0:>8}"
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

    print("=" * 80)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成: {OUTPUT_FILE}")

    if not report["groups"]:
        print("⚠️  校验失败: 没有任何分组产出")
        sys.exit(1)
    print(f"✅ 终态校验通过: 共 {len(report['groups'])} 个分组, 报告已落盘")


if __name__ == "__main__":
    main()
