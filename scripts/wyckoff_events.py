#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫事件链识别模块 v1.0 (Wyckoff Event Chain Detector)
========================================================
【理论依据】
- 威科夫三大定律: 供需定律 / 因果定律 / 努力与结果定律
- 吸筹事件链: SC(抛售高潮) → AR(自动反弹) → ST(二次测试)
             → Spring(弹簧) → SOS(力量信号) → LPS(最后支撑点)
- 派发事件链: BC(购买高潮) → UTAD(上冲回落) → SOW(弱势信号)
【权威背书】
- 民生证券《威科夫技术分析的概率云表达》: 2010-2024 纯样本外费后年化 25.04%
- 民生证券《威科夫点数图的绘制与应用》: 2010-2024 策略年化 18.1%
- CMT Association (2021): 阶段识别准确率 67%
【与账本联动】
- Spring 事件自动绑定 truth_ledger is_real → "真金弹簧"标记
【输出】
- data/analysis/wyckoff_events.json   每日事件明细
- data/analysis/wyckoff_chain.json    事件链完整度评分
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 【配置区】
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
LEDGER_DIR = Path(__file__).parent.parent / "data" / "analysis" / "truth_ledger"
HS300_PATH = Path(__file__).parent.parent / "data" / "hushen300.json"
OUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

MAX_STOCKS = 308
START_IDX = 120          # 预热期（需要120日历史）

ATR_PERIOD = 14
RANGE_LOOKBACK = 30      # 区间支撑/阻力 = 近30日极值（不含当日）

# --- SC 抛售高潮 ---
SC_VOL_PCTL = 0.85       # 量能处于近20日85分位以上
SC_SPREAD_MULT = 2.0     # 振幅 ≥ 2×ATR%
SC_SPREAD_MIN = 4.0      # 振幅绝对下限 %
SC_CLOSE_ZONE = 0.60     # 收盘位于当日振幅下60%区域

# --- AR 自动反弹 ---
AR_MAX_GAP = 10         # SC后10日内
AR_RALLY_MULT = 2.5     # 自SC低点反弹 ≥ 2.5×ATR%
AR_RALLY_MIN = 5.0      # 绝对下限 %

# --- ST 二次测试 ---
ST_MAX_GAP = 40         # SC后40日内
ST_TOL = 0.03           # 回踩至SC低点±3%
ST_VOL_SHRINK = 0.8     # 量 ≤ SC量×0.8

# --- Spring 弹簧 ---
SPRING_BREAK_TOL = 0.01  # 最低价跌破支撑1%以上
SPRING_VOL_PCTL = 0.50   # 当日量能分位≥0.5

# --- UT 上冲回落(危险信号) ---
UT_BREAK_TOL = 0.01
UT_VOL_PCTL = 0.70

# --- SOS 力量信号 ---
SOS_BODY_MULT = 1.5     # 阳线实体 ≥ 1.5×ATR%
SOS_VOL_PCTL = 0.80     # 量能80分位以上
SOS_CLOSE_ZONE = 0.75   # 收盘位于振幅上25%

# --- LPS 最后支撑点 ---
LPS_MAX_GAP = 15        # SOS后15日内
LPS_TOL = 0.02          # 回踩突破位±2%
LPS_VOL_SHRINK = 0.85   # 量较昨日缩15%以上

# --- 事件链 ---
CHAIN_WINDOW = 120       # 链检测回看窗口
CHAIN_RECENT_DAYS = 15   # 链末事件新近度
CHAIN_WEIGHTS = {"SC": 1, "AR": 1, "ST": 1, "Spring": 2, "SOS": 2, "LPS": 2,
                 "BC": 1, "UTAD": 2, "SOW": 2}
ACC_ORDER = ["SC", "AR", "ST", "Spring", "SOS", "LPS"]
DIS_ORDER = ["BC", "UTAD", "SOW"]

# ============================================================
# 【工具函数】(与 backtest_4d.py 同口径)
# ============================================================
def calculate_atr(df, period=14):
    if len(df) < period + 1:
        return None, None
    high, low, close = df['high'].values, df['low'].values, df['close'].values
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    atr = np.mean(tr[-period:])
    return atr, atr / close[-1] * 100


def get_vol_percentile(df, lookback=20):
    if len(df) < lookback:
        lookback = len(df)
    recent_vols = df.iloc[-lookback:]['volume']
    return (recent_vols < df.iloc[-1]['volume']).sum() / len(recent_vols)


def get_stock_trend(df, i, ma_period=20):
    if i < ma_period:
        return "未知"
    ma = df.iloc[i - ma_period + 1:i + 1]['close'].mean()
    return "上升趋势" if df.iloc[i]['close'] > ma else "下降趋势"


def get_position_level(df, i, lookback=120):
    if i < lookback:
        lookback = i
    recent_df = df.iloc[i - lookback + 1:i + 1]
    pct = (recent_df['close'] < df.iloc[i]['close']).sum() / len(recent_df)
    if pct < 0.30:
        return "低位"
    elif pct > 0.70:
        return "高位"
    return "中位"


def find_range(df, i, lookback=RANGE_LOOKBACK):
    """区间支撑/阻力 = 近N日极值（不含当日）"""
    if i < lookback + 1:
        return None, None
    win = df.iloc[i - lookback:i]  # 不含当日
    return float(win['low'].min()), float(win['high'].max())


def load_klines(market, code):
    for filepath in [DATA_DIR / market / f"{code}.json",
                     DATA_DIR / market / f"{market}{code}.json",
                     DATA_DIR / f"{market}{code}.json"]:
        if filepath.exists():
            with open(filepath, 'r') as f:
                data = json.load(f)
            klines = data.get('klines', [])
            if not klines:
                return None
            ncols = len(klines[0])
            cols = ['date', 'open', 'close', 'high', 'low', 'volume'] if ncols == 6 \
                else ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            df = pd.DataFrame(klines).iloc[:, :ncols]
            df.columns = cols[:ncols]
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
    return None


# ============================================================
# 【账本联动】(与 backtest_4d.py 同口径, ver>=2 才采信)
# ============================================================
_ledger_cache = None

def _load_ledger():
    global _ledger_cache
    if _ledger_cache is not None:
        return _ledger_cache
    _ledger_cache = {}
    if not LEDGER_DIR.exists():
        return _ledger_cache
    for f in sorted(LEDGER_DIR.glob("*.json")):
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                monthly = json.load(fp)
            for code, dates in monthly.items():
                if code not in _ledger_cache:
                    _ledger_cache[code] = {}
                _ledger_cache[code].update({str(d)[:10]: v for d, v in dates.items()})
        except Exception:
            pass
    return _ledger_cache


def is_real_money(market, code, trade_date):
    trade_date = str(trade_date)[:10]
    ledger = _load_ledger()
    entry = ledger.get(f"{market}{code}", {}).get(trade_date)
    if entry is None:
        return None, 0
    if entry.get("ver", 1) < 2:
        return None, 0
    return entry.get("is_real"), entry.get("quant_pct", 0)


# ============================================================
# 【事件检测器】
# ============================================================
def detect_sc(df, i, atr_pct):
    """SC 抛售高潮: 下降趋势背景 + 巨量宽幅阴线 + 收盘脱离最低"""
    if i < 25 or get_stock_trend(df, i) != "下降趋势":
        return False
    today = df.iloc[i]
    spread_pct = (today['high'] - today['low']) / today['close'] * 100
    wide = spread_pct >= max((atr_pct or 2.0) * SC_SPREAD_MULT, SC_SPREAD_MIN)
    vp = get_vol_percentile(df.iloc[max(0, i - 19):i + 1], 20)
    heavy = vp >= SC_VOL_PCTL
    rng_today = today['high'] - today['low']
    lower_zone = (today['close'] - today['low']) / (rng_today + 1e-9) <= SC_CLOSE_ZONE
    return wide and heavy and lower_zone


def detect_bc(df, i, atr_pct):
    """BC 购买高潮: 上升趋势背景 + 巨量宽幅阳线 + 收盘脱离最高"""
    if i < 25 or get_stock_trend(df, i) != "上升趋势":
        return False
    today = df.iloc[i]
    spread_pct = (today['high'] - today['low']) / today['close'] * 100
    wide = spread_pct >= max((atr_pct or 2.0) * SC_SPREAD_MULT, SC_SPREAD_MIN)
    vp = get_vol_percentile(df.iloc[max(0, i - 19):i + 1], 20)
    heavy = vp >= SC_VOL_PCTL
    rng_today = today['high'] - today['low']
    upper_zone = (today['high'] - today['close']) / (rng_today + 1e-9) <= SC_CLOSE_ZONE
    return wide and heavy and upper_zone


def detect_ar(df, i, atr_pct, sc_event):
    """AR 自动反弹: SC后N日内自低点显著回升"""
    if sc_event is None or not (sc_event['idx'] < i <= sc_event['idx'] + AR_MAX_GAP):
        return False
    if sc_event.get('ar_done'):
        return False
    sc_low = sc_event['level']
    rally = (df.iloc[i]['high'] - sc_low) / sc_low * 100
    return rally >= max((atr_pct or 2.0) * AR_RALLY_MULT, AR_RALLY_MIN)


def detect_st(df, i, sc_event):
    """ST 二次测试: 回到SC低点附近 + 量明显小于SC"""
    if sc_event is None or not (sc_event['idx'] < i <= sc_event['idx'] + ST_MAX_GAP):
        return False
    if sc_event.get('st_done'):
        return False
    sc_low = sc_event['level']
    near = abs(df.iloc[i]['low'] - sc_low) / sc_low <= ST_TOL
    shrink = df.iloc[i]['volume'] <= sc_event['vol'] * ST_VOL_SHRINK
    return near and shrink


def detect_spring(df, i, support):
    """Spring 弹簧: 跌破区间支撑后当日收回 + 量能不萎缩"""
    if support is None or support <= 0:
        return False
    today = df.iloc[i]
    broke = today['low'] <= support * (1 - SPRING_BREAK_TOL)
    recovered = today['close'] > support
    vp = get_vol_percentile(df.iloc[max(0, i - 19):i + 1], 20)
    return broke and recovered and vp >= SPRING_VOL_PCTL


def detect_ut(df, i, resistance):
    """UT 上冲回落(危险): 冲破阻力后收回 + 放量"""
    if resistance is None or resistance <= 0:
        return False
    today = df.iloc[i]
    broke = today['high'] >= resistance * (1 + UT_BREAK_TOL)
    failed = today['close'] < resistance
    vp = get_vol_percentile(df.iloc[max(0, i - 19):i + 1], 20)
    return broke and failed and vp >= UT_VOL_PCTL


def detect_sos(df, i, atr_pct, resistance):
    """SOS 力量信号: 宽幅放量阳线突破区间阻力 + 收盘强势"""
    if resistance is None or resistance <= 0:
        return False
    today = df.iloc[i]
    body_pct = (today['close'] - today['open']) / today['open'] * 100
    wide_body = body_pct >= max((atr_pct or 2.0) * SOS_BODY_MULT, 3.0)
    breakout = today['close'] > resistance
    vp = get_vol_percentile(df.iloc[max(0, i - 19):i + 1], 20)
    heavy = vp >= SOS_VOL_PCTL
    rng_today = today['high'] - today['low']
    strong_close = (today['close'] - today['low']) / (rng_today + 1e-9) >= SOS_CLOSE_ZONE
    return wide_body and breakout and heavy and strong_close


def detect_sow(df, i, atr_pct, support):
    """SOW 弱势信号: 宽幅放量阴线跌破区间支撑"""
    if support is None or support <= 0:
        return False
    today = df.iloc[i]
    body_pct = (today['open'] - today['close']) / today['open'] * 100
    wide_body = body_pct >= max((atr_pct or 2.0) * SOS_BODY_MULT, 3.0)
    breakdown = today['close'] < support
    vp = get_vol_percentile(df.iloc[max(0, i - 19):i + 1], 20)
    heavy = vp >= SOS_VOL_PCTL
    return wide_body and breakdown and heavy


def detect_lps(df, i, sos_event):
    """LPS 最后支撑点: SOS后回踩突破位 + 缩量企稳不破"""
    if sos_event is None or not (sos_event['idx'] < i <= sos_event['idx'] + LPS_MAX_GAP):
        return False
    if sos_event.get('lps_done'):
        return False
    level = sos_event['level']
    today, yesterday = df.iloc[i], df.iloc[i - 1]
    touch = today['low'] <= level * (1 + LPS_TOL)
    hold = today['close'] >= level * (1 - LPS_TOL)
    shrink = today['volume'] <= yesterday['volume'] * LPS_VOL_SHRINK
    return touch and hold and shrink


# ============================================================
# 【事件链评分】
# ============================================================
def greedy_chain(events_hist, order, window_start):
    """从每个可能起点贪心匹配有序事件链, 取最高分"""
    best = []
    for start_k in range(len(order)):
        chain, pos = [], window_start - 1
        for name in order[start_k:]:
            cands = [e for e in events_hist if e['name'] == name and e['idx'] > pos]
            if not cands:
                break
            first = min(cands, key=lambda e: e['idx'])
            chain.append(first)
            pos = first['idx']
        if chain and len(chain) > len(best):
            best = chain
    score = sum(CHAIN_WEIGHTS[e['name']] for e in best)
    return best, score


# ============================================================
# 【主流程: 单只股票事件扫描】
# ============================================================
def scan_stock(df):
    events_out = {}
    chain_out = {}
    n = len(df)
    events_hist = []
    sc_event = None
    sos_event = None

    for i in range(min(START_IDX, n), n):
        _, atr_pct = calculate_atr(df.iloc[max(0, i - ATR_PERIOD):i + 1], ATR_PERIOD)
        support, resistance = find_range(df, i)
        today = df.iloc[i]

        day_events = []

        # ---- 吸筹链事件 ----
        if detect_sc(df, i, atr_pct):
            sc_event = {'name': 'SC', 'idx': i, 'level': float(today['low']), 'vol': float(today['volume'])}
            events_hist.append(sc_event)
            day_events.append('SC')
        if detect_ar(df, i, atr_pct, sc_event):
            sc_event['ar_done'] = True
            events_hist.append({'name': 'AR', 'idx': i, 'level': float(today['high'])})
            day_events.append('AR')
        if detect_st(df, i, sc_event):
            sc_event['st_done'] = True
            events_hist.append({'name': 'ST', 'idx': i, 'level': float(today['low'])})
            day_events.append('ST')
        spring_flag = False
        if detect_spring(df, i, support):
            events_hist.append({'name': 'Spring', 'idx': i, 'level': float(support)})
            day_events.append('Spring')
            spring_flag = True
        if detect_sos(df, i, atr_pct, resistance):
            sos_event = {'name': 'SOS', 'idx': i, 'level': float(resistance)}
            events_hist.append(sos_event)
            day_events.append('SOS')
        if detect_lps(df, i, sos_event):
            sos_event['lps_done'] = True
            events_hist.append({'name': 'LPS', 'idx': i, 'level': float(sos_event['level'])})
            day_events.append('LPS')

        # ---- 派发链事件 ----
        if detect_bc(df, i, atr_pct):
            events_hist.append({'name': 'BC', 'idx': i, 'level': float(today['high'])})
            day_events.append('BC')
        if detect_ut(df, i, resistance):
            events_hist.append({'name': 'UTAD', 'idx': i, 'level': float(resistance)})
            day_events.append('UTAD')
        if detect_sow(df, i, atr_pct, support):
            events_hist.append({'name': 'SOW', 'idx': i, 'level': float(support)})
            day_events.append('SOW')

        # ---- 记录当日事件 ----
        if day_events:
            events_out[today['date']] = {'events': day_events}

        # ---- 事件链评分 ----
        window_start = max(0, i - CHAIN_WINDOW)
        recent_hist = [e for e in events_hist if e['idx'] >= window_start]
        acc_chain, acc_score = greedy_chain(recent_hist, ACC_ORDER, window_start)
        dis_chain, dis_score = greedy_chain(recent_hist, DIS_ORDER, window_start)
        if acc_score >= 2 or dis_score >= 2:
            best_type = "吸筹" if acc_score >= dis_score else "派发"
            best_chain = acc_chain if acc_score >= dis_score else dis_chain
            recency = (i - best_chain[-1]['idx']) <= CHAIN_RECENT_DAYS
            chain_out[today['date']] = {
                'score': max(acc_score, dis_score),
                'type': best_type,
                'chain': [e['name'] for e in best_chain],
                'chain_idx': [e['idx'] for e in best_chain],
                'recency': recency,
                'position': get_position_level(df, i),
                'trend': get_stock_trend(df, i),
            }
    return events_out, chain_out


# ============================================================
# 【主函数】
# ============================================================
def scan_all_stocks():
    stocks = []
    try:
        from config import HOLDINGS_TUPLE
        stocks = list(HOLDINGS_TUPLE)
    except Exception:
        HOLDINGS = [("sh", "600584"), ("sz", "002156"), ("sh", "603283"), ("sz", "300394"),
                    ("sh", "601138"), ("sh", "601231"), ("sz", "300476"), ("sh", "603516")]
        stocks = list(HOLDINGS)
    if HS300_PATH.exists():
        try:
            with open(HS300_PATH, 'r', encoding='utf-8') as f:
                for code in json.load(f).get('codes', []):
                    stocks.append((code[:2], code[2:]))
        except Exception:
            pass
    for sub in ['sh', 'sz']:
        d = DATA_DIR / sub
        if d.exists():
            for f in d.glob("*.json"):
                code = f.stem
                if code == "sh000001" or code.startswith("sz399"):
                    continue
                pure = code[2:] if code.startswith(('sh', 'sz')) else code
                stocks.append((sub, pure))
    seen, uniq = set(), []
    for m, c in stocks:
        if (m, c) not in seen:
            seen.add((m, c))
            uniq.append((m, c))
    return uniq[:MAX_STOCKS]


def main():
    print("=" * 70)
    print("威科夫事件链识别模块 v1.0")
    print("SC → AR → ST → Spring → SOS → LPS (吸筹) / BC → UTAD → SOW (派发)")
    print("=" * 70)

    all_stocks = scan_all_stocks()
    print(f"\n扫描股票数: {len(all_stocks)}\n")

    ledger = _load_ledger()
    if ledger:
        print(f"[账本] 已加载 {len(ledger)} 只股票")

    all_events, all_chains = {}, {}
    stat_event_count = {}
    for idx, (market, code) in enumerate(all_stocks):
        df = load_klines(market, code)
        if df is None:
            continue
        events_out, chain_out = scan_stock(df)
        full_code = f"{market}{code}"

        # 账本绑定: 给Spring日打上真金/量化标记
        for d, rec in events_out.items():
            if 'Spring' in rec['events']:
                real, quant_pct = is_real_money(market, code, d)
                rec['spring_real'] = real
                rec['quant_pct'] = quant_pct
                if real is True:
                    rec['events'].append('真金弹簧')
            for ev in rec['events']:
                stat_event_count[ev] = stat_event_count.get(ev, 0) + 1

        if events_out:
            all_events[full_code] = events_out
        if chain_out:
            all_chains[full_code] = chain_out
        print(f"  {idx+1}/{len(all_stocks)} {full_code}: "
              f"事件日 {len(events_out)}, 链日 {len(chain_out)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "wyckoff_events.json", 'w', encoding='utf-8') as f:
        json.dump(all_events, f, ensure_ascii=False)
    with open(OUT_DIR / "wyckoff_chain.json", 'w', encoding='utf-8') as f:
        json.dump(all_chains, f, ensure_ascii=False)

    print("\n" + "=" * 70)
    print("事件统计:")
    for name, cnt in sorted(stat_event_count.items(), key=lambda x: -x[1]):
        print(f"  {name}: {cnt}")
    print("=" * 70)

    full_chains = 0
    for code, chains in all_chains.items():
        for d, rec in chains.items():
            if rec['score'] >= 9:
                full_chains += 1
    print(f"\n完整吸筹链(score>=9): {full_chains} 个")
    print(f"\n✅ 已生成:")
    print(f"   {OUT_DIR / 'wyckoff_events.json'}")
    print(f"   {OUT_DIR / 'wyckoff_chain.json'}")


if __name__ == "__main__":
    main()
