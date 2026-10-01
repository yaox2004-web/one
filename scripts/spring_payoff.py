#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫信号兑现率统计 v0.5  (Phase 5)
======================================================================
【铁律】信号分组绝不使用未来函数！
  - 信号必须在事件日收盘时已可判定
  - T+N 兑现率是"评分"(合法); 分组条件用事件日之后信息是"偷看"(违法)

v0.5 新增:
  - SOS_前置链背景: 该股30自然日内出现过"前置链Spring"(可交易)
    逻辑: 前置链打底(SC+AR+ST+Spring) + SOS确认 = 完整策略进场点
  - 窗口扩展: T+1/3/5/10/20 (前置链慢热, 巅峰可能在T+5之外)
  - 诊断: 统计SOS被30天窗的捕获情况

分组口径:
  Spring_前置链        (✅) Spring日链快照已含 SC+AR+ST
  Spring_非前置链      (✅)
  SOS_前置链背景       (✅) 30自然日内有前置链Spring
  SOS_无前置链背景     (✅)
  Spring_完整链_回溯   (⚠️仅归因, 含未来信息, 禁止作交易信号)
  Spring_真金 / SOS_全体 / Spring_全体
======================================================================
"""

import json
import os
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta

EVENTS_FILE = "data/analysis/wyckoff_events.json"
CHAIN_FILE  = "data/analysis/wyckoff_chain.json"
KLINE_DIR   = "data/kline"
OUTPUT_FILE = "data/analysis/payoff_report.json"

WINDOWS    = [1, 3, 5, 10, 20]
MIN_SAMPLE = 30
CHAIN_LINK_DAYS  = 90   # 仅回溯归因
CHAIN_MIN_SCORE  = 9    # 仅回溯归因
SOS_LOOKBACK_DAYS = 30  # 前置链Spring → SOS 的最大间隔(自然日)


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
            for t in payload.get("events", []):
                events.append({
                    "code": str(code),
                    "type": str(t),
                    "date": str(date)[:10],
                    "spring_real": payload.get("spring_real"),
                })
    print(f"[事件] 共解析出 {len(events)} 个事件")
    real_cnt = sum(1 for e in events
                   if e["type"] == "Spring" and e["spring_real"])
    print(f"[事件] Spring中真金弹簧(spring_real=true): {real_cnt} 个")
    return events


# ----------------------------------------------------------------------
# 链快照读取
# ----------------------------------------------------------------------
def load_chain_snapshots():
    if not os.path.exists(CHAIN_FILE):
        print(f"[链] 未找到 {CHAIN_FILE}, 前置链/回溯分组跳过")
        return {}
    with open(CHAIN_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    chains = {}
    for code, dates in raw.items():
        if not isinstance(dates, dict):
            continue
        recs = sorted((str(d)[:10], p) for d, p in dates.items()
                      if isinstance(p, dict))
        if recs:
            chains[str(code)] = ([d for d, _ in recs], [p for _, p in recs])
    print(f"[链] 已加载 {len(chains)} 只股票的链快照")
    return chains


def snapshot_at(chains, code, event_date):
    """事件日(含)之前最近一条链快照——当时视角, 无未来函数"""
    if code not in chains:
        return None
    dates, payloads = chains[code]
    i = bisect_right(dates, event_date) - 1
    return payloads[i] if i >= 0 else None


def prechain_ok(snapshot):
    """前置链: 事件日已知 SC+AR+ST 全部出现"""
    if snapshot is None:
        return False
    return {"SC", "AR", "ST"} <= set(snapshot.get("chain", []))


def chain_completed_after(chains, code, event_date,
                          days=CHAIN_LINK_DAYS, min_score=CHAIN_MIN_SCORE):
    """⚠️ 回溯归因专用: 用了未来信息, 严禁作交易信号"""
    if code not in chains:
        return False
    dates, payloads = chains[code]
    try:
        d0 = datetime.strptime(event_date, "%Y-%m-%d")
    except ValueError:
        return False
    limit = (d0 + timedelta(days=days)).strftime("%Y-%m-%d")
    i = bisect_right(dates, event_date) - 1
    for j in range(i + 1, len(dates)):
        if dates[j] > limit:
            break
        if float(payloads[j].get("score", 0)) >= min_score:
            return True
    return False


# ----------------------------------------------------------------------
# K线读取
# ----------------------------------------------------------------------
_kline_cache = {}

def load_kline(code):
    if code in _kline_cache:
        return _kline_cache[code]
    path = os.path.join(KLINE_DIR, code[:2], code + ".json")
    kl = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rows = []
            for k in data.get("klines", []):
                if isinstance(k, (list, tuple)) and len(k) >= 3:
                    rows.append((str(k[0])[:10], float(k[1]), float(k[2])))
            rows.sort(key=lambda x: x[0])
            kl = rows
        except Exception:
            kl = None
    _kline_cache[code] = kl
    return kl


def payoff_of(kline, event_date, n):
    dates = [d for d, _, _ in kline]
    if event_date not in dates:
        return None
    idx = dates.index(event_date)
    if idx + n >= len(kline):
        return None          # 右删失: 数据不够看T+N, 不计入
    c0 = kline[idx][2]
    if c0 <= 0:
        return None
    return (kline[idx + n][2] - c0) / c0


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main():
    print("=" * 70)
    print("威科夫信号兑现率统计 v0.5 (无未来函数版)")
    print("=" * 70)

    events = load_events()
    chains = load_chain_snapshots()

    # ---- 第一步: 标记每个Spring是否前置链, 生成 {code: [前置Spring日期]} ----
    prechain_springs = defaultdict(list)
    n_pre = 0
    for ev in events:
        if ev["type"] != "Spring":
            continue
        if prechain_ok(snapshot_at(chains, ev["code"], ev["date"])):
            prechain_springs[ev["code"]].append(ev["date"])
            n_pre += 1
    for c in prechain_springs:
        prechain_springs[c].sort()
    print(f"[前置] 前置链Spring(可交易): {n_pre} 个, "
          f"分布在 {len(prechain_springs)} 只股票")

    events = [e for e in events if e["type"] in {"Spring", "SOS"}]
    print(f"[过滤] 目标信号(Spring/SOS)共 {len(events)} 个")

    # ---- 第二步: 统计 ----
    results = defaultdict(lambda: defaultdict(list))
    missing_kline = set()
    n_retro = 0
    sos_hit = sos_miss = 0   # 诊断: SOS对30天窗的捕获情况

    for ev in events:
        kl = load_kline(ev["code"])
        if not kl:
            missing_kline.add(ev["code"])
            continue

        if ev["type"] == "Spring":
            is_pre = ev["date"] in prechain_springs.get(ev["code"], [])
            groups = ["Spring_全体",
                      "Spring_前置链" if is_pre else "Spring_非前置链"]
            if chain_completed_after(chains, ev["code"], ev["date"]):
                n_retro += 1
                groups.append("Spring_完整链_回溯")
            if ev["spring_real"]:
                groups.append("Spring_真金")
        else:  # SOS
            # 前置链背景: SOS当天(含)往前30自然日内有前置链Spring
            plist = prechain_springs.get(ev["code"], [])
            try:
                d0 = datetime.strptime(ev["date"], "%Y-%m-%d")
                lo = (d0 - timedelta(days=SOS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
            except ValueError:
                plist = []
            i = bisect_left(plist, lo)
            has_bg = i < len(plist) and plist[i] <= ev["date"]
            if has_bg:
                sos_hit += 1
            else:
                sos_miss += 1
            groups = ["SOS_全体",
                      "SOS_前置链背景" if has_bg else "SOS_无前置链背景"]

        for g in groups:
            for n in WINDOWS:
                r = payoff_of(kl, ev["date"], n)
                if r is not None:
                    results[g][n].append(r)

    print(f"[回溯] 后{CHAIN_LINK_DAYS}天走完score>={CHAIN_MIN_SCORE}链(仅归因): {n_retro} 个")
    print(f"[SOS诊断] 30天窗捕获前置链背景: {sos_hit} 个 / 落在窗外: {sos_miss} 个"
          + ("  ←窗外偏多, 可考虑放宽窗口" if sos_miss > 2 * sos_hit and sos_miss > 30 else ""))
    if missing_kline:
        print(f"[警告] {len(missing_kline)} 只股票找不到K线文件 "
              f"(示例: {sorted(missing_kline)[:3]})")

    # ---- 汇总 ---------------------------------------------------------
    report = {"meta": {"window": WINDOWS,
                       "win_def": "T+N收盘>事件日收盘",
                       "min_sample": MIN_SAMPLE,
                       "iron_rule": "信号分组无未来函数; 回溯分组仅归因",
                       "sos_lookback_days": SOS_LOOKBACK_DAYS,
                       "note": "T+10/T+20存在右删失: 近期事件数据不足不计入",
                       "tradeable": ["Spring_全体", "Spring_前置链",
                                     "Spring_非前置链", "SOS_全体",
                                     "SOS_前置链背景", "SOS_无前置链背景"],
                       "retrospective_only": ["Spring_完整链_回溯"]},
              "groups": {}}

    hdr = f"{'分组':<22}{'样本':>6}" + "".join(
        f"{'T+'+str(n)+'胜率':>10}" for n in WINDOWS) + f"{'T+20均收益':>12}"
    print()
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))

    for g in sorted(results.keys()):
        entry = {}
        n0 = len(results[g][WINDOWS[0]])
        tag = "⚠️回溯" if g.endswith("回溯") else "✅可交易"
        line = f"{g:<22}{n0:>6}"
        for n in WINDOWS:
            rets = results[g][n]
            if rets:
                win = sum(1 for r in rets if r > 0) / len(rets)
                entry[f"T{n}_n"] = len(rets)
                entry[f"T{n}_winrate"] = round(win * 100, 1)
                line += f"{win*100:>9.1f}%"
            else:
                line += f"{'--':>10}"
        rets_max = results[g][max(WINDOWS)]
        if rets_max:
            avg = sum(rets_max) / len(rets_max)
            entry["Tmax_avg_return"] = round(avg * 100, 2)
            line += f"{avg*100:>11.2f}%"
        if n0 < MIN_SAMPLE:
            entry["note"] = "样本不足"
            line += "  (样本不足)"
        print(f"{line}  {tag}")
        entry["tradeable"] = tag == "✅可交易"
        report["groups"][g] = entry

    print("=" * len(hdr))

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
