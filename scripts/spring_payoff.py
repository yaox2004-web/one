#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫信号兑现率统计 v0.1  (Phase 5)
======================================================================
纯读取型脚本:
  读: data/analysis/wyckoff_events.json   (事件清单)
      data/kline/                        (全市场日线)
  写: data/analysis/payoff_report.json   (兑现率报告)

统计口径 (v0.1):
  - 胜 = T+N 收盘价 > 事件日收盘价
  - 统计窗口: T+1 / T+3 / T+5
  - 分组: Spring全体 / Spring(链score>=9) / SOS全体
  - 样本数 < 30 的分组标注"样本不足"
======================================================================
"""

import json
import os
import sys
from collections import defaultdict

# ----------------------------------------------------------------------
# 路径配置
# ----------------------------------------------------------------------
EVENTS_FILE = "data/analysis/wyckoff_events.json"
KLINE_DIR   = "data/kline"
OUTPUT_FILE = "data/analysis/payoff_report.json"

WINDOWS   = [1, 3, 5]          # T+N 窗口
MIN_SAMPLE = 30                # 样本量门槛
CHAIN_SCORE_THRESHOLD = 9      # 完整链判定线


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def load_events():
    """读事件文件, 自动兼容两种结构:
       A) {"sh600547": {"events": [...]}, ...}   按股票分组
       B) [{"code": "sh600547", "type": "Spring", "date": "..."}, ...] 平铺列表
    """
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    events = []

    if isinstance(raw, dict):
        for code, payload in raw.items():
            ev_list = payload.get("events", []) if isinstance(payload, dict) else []
            for ev in ev_list:
                events.append(_norm_event(ev, code))
    elif isinstance(raw, list):
        for ev in raw:
            events.append(_norm_event(ev, ev.get("code", "")))

    print(f"[事件] 共解析出 {len(events)} 个事件")
    return events


def _norm_event(ev, code):
    """统一事件字段名, 兼容常见命名差异"""
    etype = ev.get("type") or ev.get("event") or ev.get("event_type") or ""
    edate = ev.get("date") or ev.get("event_date") or ev.get("date_str") or ""
    score = ev.get("chain_score") or ev.get("score") or 0
    return {"code": code, "type": str(etype), "date": str(edate), "score": score}


def load_kline(code):
    """读单只股票日线, 支持 csv / json 两种格式
       返回: [(date, close), ...] 按日期升序
    """
    base = os.path.join(KLINE_DIR, code)
    for path in (base + ".csv", base + ".json"):
        if os.path.exists(path):
            return _parse_kline(path)
    return None


def _parse_kline(path):
    rows = []
    if path.endswith(".csv"):
        import csv
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                d = r.get("date") or r.get("trade_date") or r.get("日期") or ""
                c = r.get("close") or r.get("收盘") or r.get("close_price") or ""
                if d and c:
                    rows.append((str(d)[:10], float(c)))
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("data") or data.get("kline") or data.get("daily") or []
        for r in data:
            if isinstance(r, dict):
                d = r.get("date") or r.get("trade_date") or ""
                c = r.get("close") or r.get("收盘") or ""
            elif isinstance(r, (list, tuple)) and len(r) >= 2:
                d, c = r[0], r[1]          # 约定: [date, close, ...]
            else:
                continue
            if d and c:
                rows.append((str(d)[:10], float(c)))

    rows.sort(key=lambda x: x[0])
    return rows


def payoff_of(kline, event_date, n):
    """给定事件日, 计算 T+N 收益率(小数). 数据不足返回 None"""
    dates = [d for d, _ in kline]
    if event_date not in dates:
        return None                       # 事件日不在K线里(停牌/数据缺口)
    idx = dates.index(event_date)
    if idx + n >= len(kline):
        return None                       # 未来数据不足, 跳过
    c0 = kline[idx][1]
    cn = kline[idx + n][1]
    return (cn - c0) / c0


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main():
    print("=" * 70)
    print("威科夫信号兑现率统计 v0.1 (Phase 5)")
    print("=" * 70)

    events = load_events()

    # ---- 只统计目标信号, 过滤掉其他类型 ------------------------------
    targets = {"Spring", "SOS"}
    events = [e for e in events if e["type"] in targets]
    print(f"[过滤] 目标信号(Spring/SOS)共 {len(events)} 个")

    # ---- 逐事件计算 T+1/3/5 收益 ------------------------------------
    results = defaultdict(lambda: defaultdict(list))   # group -> window -> [ret]
    missing_kline, skipped = set(), 0

    for ev in events:
        kl = load_kline(ev["code"])
        if not kl:
            missing_kline.add(ev["code"])
            continue

        # 分组: Spring 按 链score 二分; SOS 全体一组
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
                else:
                    skipped += 1

    if missing_kline:
        print(f"[警告] {len(missing_kline)} 只股票找不到K线文件(示例: "
              f"{sorted(missing_kline)[:3]}...)")

    # ---- 汇总统计 ----------------------------------------------------
    report = {"meta": {"window": WINDOWS, "win_def": "T+N收盘>事件日收盘",
                       "min_sample": MIN_SAMPLE}, "groups": {}}

    print()
    print("=" * 70)
    header = f"{'分组':<20}{'样本':>6}"
    for n in WINDOWS:
        header += f"{'T+%d胜率'%n:>10}"
    header += f"{'T+5均收益':>12}"
    print(header)
    print("-" * 70)

    for g in sorted(results.keys()):
        entry = {}
        line = f"{g:<20}"
        n0 = len(results[g][WINDOWS[0]])
        line += f"{n0:>6}"
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

    print("=" * 70)
    print(f"[统计] 因数据不足跳过的事件窗口数: {skipped}")

    # ---- 落盘 --------------------------------------------------------
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成: {OUTPUT_FILE}")

    # ---- 终态校验 ----------------------------------------------------
    n_groups = len(report["groups"])
    if n_groups == 0:
        print("⚠️  校验失败: 没有任何分组产出——请检查事件文件结构是否被正确解析")
        sys.exit(1)
    print(f"✅ 终态校验通过: 共 {n_groups} 个分组, 报告已落盘")


if __name__ == "__main__":
    main()
