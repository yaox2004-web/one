#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOS_前置链背景 解剖器 v0.2 (diag_sos13.py)
==========================================
v0.2修复: 链快照的已确认事件在 'chain' 键(列表)里,
         v0.1猜成了 events/confirmed/done, 导致前置链重建=0。
         真实结构(探针实测): {日期: {"score":..,"type":..,"chain":[..],...}}

目的: payoff报告里"SOS_前置链背景" n=13、T+20胜率76.9%,
     长得太美。逐个掏出来看, 防止"少数股票刷出来的假美人"。

纯诊断: 只读不写账本, 不碰地基。
版本: v0.2 (2026-10-02)
"""

import os
import sys
import json
import traceback
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter

EVENTS_PATH = 'data/analysis/wyckoff_events.json'
CHAIN_PATH = 'data/analysis/wyckoff_chain.json'
KLINE_DIR = 'data/kline'
OUT_PATH = 'data/analysis/sos13_anatomy.json'
WINDOWS = [1, 3, 5, 10, 20]
CAL_WINDOW = 30   # 日历30天窗
TD_WINDOW = 30    # 交易日30天窗
TARGET_N = 13     # payoff报告的样本数
PRE_SPRING_EXPECTED = 98  # payoff的前置链Spring口径

BJ = timezone(timedelta(hours=8))


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def looks_like_date(s):
    s = str(s)
    return len(s) >= 10 and s[4] == '-' and s[7] == '-'


def parse_d(s):
    return datetime.strptime(s[:10], '%Y-%m-%d')


def probe(name, obj, max_chars=400):
    print(f"[探针] {name} 顶层类型: {type(obj).__name__}", end='')
    try:
        if isinstance(obj, dict):
            keys = list(obj.keys())
            print(f", 共 {len(keys)} 键, 前5: {keys[:5]}")
            if keys:
                s = json.dumps(obj[keys[0]], ensure_ascii=False, default=str)
                print(f"[探针] 首键'{keys[0]}'预览: {s[:max_chars]}")
        elif isinstance(obj, list):
            print(f", 共 {len(obj)} 项")
    except Exception as e:
        print(f" (预览失败: {e})")


def extract_events_from_entry(entry):
    """事件条目: {"events": ["SOS"], "spring_real":.., "quant_pct":..}"""
    if isinstance(entry, list):
        return [str(x) for x in entry]
    if isinstance(entry, dict):
        v = entry.get('events')
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str):
            return [v]
        return [str(k) for k in entry.keys()]
    return []


def normalize_events(raw):
    """{code: {日期: 条目}} → {code: [(日期, [事件名...]), ...]}"""
    out = {}
    for code, val in raw.items():
        pairs = [(k[:10], extract_events_from_entry(v))
                 for k, v in val.items() if looks_like_date(k)]
        if pairs:
            out[str(code)] = pairs
    return out


def snapshot_confirmed(snap):
    """链快照: {"score":..,"type":..,"chain":["BC","UTAD"],...} → 事件集合"""
    conf = set()
    if not isinstance(snap, dict):
        return conf
    v = snap.get('chain')
    if isinstance(v, list):
        conf |= {str(x) for x in v}
    elif isinstance(v, str):
        conf.add(v)
    # 兜底: 万一还有别的形态
    for key in ('events', 'confirmed', 'done'):
        w = snap.get(key)
        if isinstance(w, list):
            conf |= {str(x) for x in w}
        elif isinstance(w, str):
            conf.add(w)
    return conf


def chain_has_sc_ar_st(chain, code, date):
    """事件日视角: 事件日(含)之前最近的链快照里, SC+AR+ST是否都在chain里"""
    snaps = chain.get(code)
    if not snaps:
        return False
    chosen = None
    for d, snap in snaps:
        if d <= date:
            chosen = snap
        else:
            break
    if chosen is None:
        return False
    conf = {str(x).lower() for x in snapshot_confirmed(chosen)}
    return ('sc' in conf) and ('ar' in conf) and ('st' in conf)


def load_kline(code):
    code = str(code)
    paths = []
    if len(code) == 8 and code[:2] in ('sh', 'sz', 'bj'):
        paths.append(f'{KLINE_DIR}/{code[:2]}/{code}.json')
    else:
        for m in ('sh', 'sz', 'bj'):
            paths.append(f'{KLINE_DIR}/{m}/{m}{code}.json')
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                ks = data.get('klines', [])
                dates = [str(x[0])[:10] for x in ks]
                closes = [float(x[2]) for x in ks]
                idx = {d: i for i, d in enumerate(dates)}
                return {'dates': dates, 'closes': closes, 'idx': idx,
                        'name': data.get('name', '')}
            except Exception:
                return None
    return None


def main():
    print('=' * 86)
    print('SOS_前置链背景 13样本解剖 v0.2 (chain键修复版)')
    print('=' * 86)

    if not os.path.exists(EVENTS_PATH):
        print(f"[失败] 找不到 {EVENTS_PATH}")
        sys.exit(1)
    raw_ev = load_json(EVENTS_PATH)
    probe('wyckoff_events.json', raw_ev)
    if not os.path.exists(CHAIN_PATH):
        print(f"[失败] 找不到 {CHAIN_PATH}")
        sys.exit(1)
    raw_ch = load_json(CHAIN_PATH)
    probe('wyckoff_chain.json', raw_ch)

    # ---------- 1. 事件 ----------
    events = normalize_events(raw_ev)
    total = sum(len(v) for v in events.values())
    print(f"[事件] 归一化: {len(events)} 只股票, {total} 条事件日记录")
    sos_list, spring_list = [], []
    for code, pairs in events.items():
        for d, evs in pairs:
            low = [e.lower() for e in evs]
            if 'sos' in low:
                sos_list.append((code, d))
            if 'spring' in low:
                spring_list.append((code, d))
    print(f"[事件] SOS: {len(sos_list)} 个 | Spring: {len(spring_list)} 个")
    if not sos_list or not spring_list:
        print("[失败] 没找到SOS或Spring事件")
        sys.exit(1)

    # ---------- 2. 链快照 → 前置链Spring(重建) ----------
    chain = {}
    for code, val in raw_ch.items():
        snaps = [(k[:10], v) for k, v in val.items()
                 if looks_like_date(k) and isinstance(v, dict)]
        snaps.sort(key=lambda x: x[0])
        if snaps:
            chain[str(code)] = snaps
    print(f"[链] 链快照: {len(chain)} 只股票")

    pre_springs = defaultdict(list)
    for code, d in spring_list:
        if chain_has_sc_ar_st(chain, code, d):
            pre_springs[code].append(d)
    n_pre = sum(len(v) for v in pre_springs.values())
    print(f"[链] 前置链Spring(重建): {n_pre} 个  (payoff口径{PRE_SPRING_EXPECTED}, "
          f"{'✅对齐' if abs(n_pre - PRE_SPRING_EXPECTED) <= 5 else '⚠️有偏差,但仍可解剖'})")
    if n_pre == 0:
        print("[失败] 前置链重建仍为0! 把[探针]输出贴回给AI")
        sys.exit(1)

    # ---------- 3. K线 ----------
    need = set(c for c, _ in sos_list) | set(pre_springs.keys())
    kl = {}
    for code in need:
        rec = load_kline(code)
        if rec:
            kl[code] = rec
    print(f"[K线] 预加载 {len(kl)}/{len(need)} 只")

    def td_gap(code, s, d):
        rec = kl.get(code)
        if not rec:
            return None
        i, j = rec['idx'].get(s), rec['idx'].get(d)
        if i is None or j is None or j <= i:
            return None
        return j - i

    # ---------- 4. 匹配前置链背景 ----------
    matched_cal, matched_td = [], []
    for code, d in sos_list:
        for s in pre_springs.get(code, []):
            if s < d and (parse_d(d) - parse_d(s)).days <= CAL_WINDOW:
                matched_cal.append((code, d, s))
                break
    for code, d in sos_list:
        for s in pre_springs.get(code, []):
            g = td_gap(code, s, d)
            if g is not None and g <= TD_WINDOW:
                matched_td.append((code, d, s))
                break
    print(f"[窗] 日历30天窗: {len(matched_cal)} 个 | 交易日30天窗: {len(matched_td)} 个  (payoff应为{TARGET_N})")
    matched = matched_cal
    if len(matched_cal) != TARGET_N and len(matched_td) == TARGET_N:
        matched = matched_td
        print("[窗] 采用交易日窗(与payoff对齐)")

    if not matched:
        print("[失败] 一个都没匹配上, 贴[探针]输出给AI")
        sys.exit(1)

    # ---------- 5. 逐个解剖 ----------
    print()
    print('=' * 100)
    print(f"{'股票':<12}{'SOS日':<12}{'←Spring日':<12}{'隔天':>5}  {'T+1 T+3 T+5 T+10 T+20':<24}{'T+20收益':>9}")
    print('-' * 100)
    win_cnt = {w: 0 for w in WINDOWS}
    cnt = {w: 0 for w in WINDOWS}
    rows = []
    for code, d, s in sorted(matched):
        rec = kl.get(code) or {}
        closes = rec.get('closes', [])
        i = rec.get('idx', {}).get(d)
        marks = []
        for w in WINDOWS:
            if i is None or i + w >= len(closes):
                marks.append(' -- ')
            else:
                cnt[w] += 1
                ok = closes[i + w] > closes[i]
                if ok:
                    win_cnt[w] += 1
                marks.append('  ✓ ' if ok else '  ✗ ')
        if i is not None and i + 20 < len(closes):
            r20 = (closes[i + 20] / closes[i] - 1) * 100
            r20_str = f"{r20:>+8.2f}%"
        else:
            r20 = None
            r20_str = '    --'
        gap_cal = (parse_d(d) - parse_d(s)).days
        name = rec.get('name', '')
        print(f"{code:<12}{d:<12}{s:<12}{gap_cal:>5}  {''.join(marks):<24}{r20_str:>9}  {name}")
        rows.append({'code': code, 'name': name, 'sos_date': d, 'spring_date': s,
                     'gap_cal_days': gap_cal, 'marks': [m.strip() for m in marks],
                     't20_ret': round(r20, 2) if r20 is not None else None})
    print('=' * 100)

    # ---------- 6. 集中度体检 ----------
    cnt_by_stock = Counter(c for c, _, _ in matched)
    cnt_by_month = Counter(d[:7] for _, d, _ in matched)
    n = len(matched)
    print(f"\n[解剖] {n} 个样本来自 {len(cnt_by_stock)} 只股票:")
    for stk, c in cnt_by_stock.most_common():
        share = c / n * 100
        warn = '  ⚠️高度集中!' if share >= 40 else ''
        print(f"   {stk} {kl.get(stk, {}).get('name', '')}: {c} 个 ({share:.0f}%){warn}")
    print(f"[解剖] 月份分布: {dict(sorted(cnt_by_month.items()))}")

    if cnt[20]:
        print(f"[核对] 重建样本T+20胜率: {win_cnt[20]}/{cnt[20]} = {win_cnt[20] / cnt[20] * 100:.1f}%"
              f"  (payoff报告: 10/13 = 76.9%)")

    top_share = cnt_by_stock.most_common(1)[0][1] / n * 100
    if top_share >= 40 or len(cnt_by_stock) <= 3:
        verdict = '⚠️ 高度集中: 76.9%大概率是少数股票的行情, 慎信, 继续攒样本'
    elif top_share <= 25 and len(cnt_by_stock) >= 8:
        verdict = '✅ 分散度良好: 更像真实的信号效应, 值得继续养'
    else:
        verdict = '😐 中等集中: 有一定效应但证据不硬, 继续攒样本'
    print(f"\n[判决] {verdict}")

    # ---------- 7. 落盘 ----------
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump({'version': '0.2',
                   'generated_at': datetime.now(BJ).strftime('%Y-%m-%d %H:%M'),
                   'n_samples': n,
                   'n_stocks': len(cnt_by_stock),
                   'top_stock_share': round(top_share, 1),
                   'verdict': verdict,
                   'samples': rows}, f, ensure_ascii=False, indent=2)
    print(f"✅ 已生成: {OUT_PATH}")
    print("✅ 终态校验通过: SOS解剖报告已落盘")


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print('[崩溃] 意外错误, 请把下面的报错连同[探针]输出一起贴回给AI:')
        traceback.print_exc()
        sys.exit(1)
