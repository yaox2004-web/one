#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法 - 历史回测验证（最终完整版）
=================================================
【无未来函数】
【买入标准】信号确认后 → 等回踩关键位 → 缩量企稳 → T+1开盘买入
【卖出标准】跌破关键位就卖（动态止损），不固定持有N天
【交易成本】买入0.125% + 卖出0.125% = 总共0.25%
【位置分档】低位<30% / 中位30%-70% / 高位>70%
【资料来源】股海明灯《量柱擒涨停》《量线捉涨停》黑马王子著
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

# ============================================================
# 【配置区】所有参数
# ============================================================

DATA_DIR = Path(__file__).parent.parent / "data" / "kline"

MAX_STOCKS = 50

HOLDINGS = [
    ("sh", "600584"),
    ("sz", "002156"),
    ("sh", "603283"),
    ("sz", "300394"),
    ("sh", "601138"),
    ("sh", "601231"),
    ("sz", "300476"),
    ("sh", "603516"),
]

HOLD_PERIODS = [5, 10, 20]

# ============================================================
# 【回踩买入核心参数】
# ============================================================
MAX_WAIT_DAYS = 10
TOUCH_TOLERANCE = 0.02
SHRINK_VOL_RATIO = 0.8
STAY_ABOVE = True

# ============================================================
# 【交易成本】
# ============================================================
COMMISSION_RATE = 0.00125    # 单边佣金+滑点 0.125%
STAMP_TAX = 0.001             # 印花税 0.1%（卖出收）
TOTAL_COST = COMMISSION_RATE * 2 + STAMP_TAX  # 一来一回总共0.35%

# ============================================================
# 【位置分档参数】
# ============================================================
POSITION_LOOKBACK = 120
LOW_PCTL = 0.30
HIGH_PCTL = 0.70

# ============================================================
# 【ATR自适应】
# ============================================================
ATR_ADAPTIVE = True
ATR_PERIOD = 14

YIN_BODY_ATR_MULT = 1.5
YIN_BODY_FALLBACK = 5.0
YIN_LOOKBACK = 60

CHANGYANG_ATR_MULT = 1.5
CHANGYANG_FALLBACK = 5.0

# ============================================================
# 【量柱核心定义】
# ============================================================
BEISHU_RATIO = 1.8
GAOLIANG_LOOKBACK = 20
PINGLIANG_TOLERANCE = 0.15

SMALL_BEISHU_MIN = 1.5
SMALL_BEISHU_MAX = 2.0

# ============================================================
# 【量能分位数】
# ============================================================
VOL_LOOKBACK = 20
VOL_PCTL_HIGH = 0.80
VOL_PCTL_LOW = 0.20
BASE_VOL_PCTL = 0.60

BEISHUO_EXTEND_PCTL = 0.80
BEISHUO_SHRINK_PCTL = 0.20

LONG_YIN_SHORT_VOL_PCTL = 0.30

# ============================================================
# 【涨停板】
# ============================================================
LIMIT_UP_MAIN = 9.8
LIMIT_UP_GEM = 19.8

# ============================================================
# 【王牌柱】
# ============================================================
GENERAL_CONFIRM_DAYS = 3

# ============================================================
# 【峰顶线/谷底线】
# ============================================================
SHORT_WINDOW = 20
CONFIRM_DAYS_SHORT = 2
PEAK_SIDE_SHORT = 2
VOL_PERCENTILE = 0.7

# ============================================================
# 【其他参数】
# ============================================================
BODY_RATIO_THRESHOLD = 0.6
NIUGU_TOUCH_TOLERANCE = 0.01


# ============================================================
# 【ATR计算】
# ============================================================
def calculate_atr(df, period=14):
    if len(df) < period + 1:
        return None, None
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    atr = np.mean(tr[-period:])
    atr_pct = atr / close[-1] * 100
    return atr, atr_pct


def get_atr_threshold(atr_pct, mult, fallback):
    if ATR_ADAPTIVE and atr_pct is not None:
        return atr_pct * mult
    else:
        return fallback


def is_gem_star(code):
    if code.startswith('300') or code.startswith('301') or code.startswith('688'):
        return True
    return False


# ============================================================
# 【量能分位数】
# ============================================================
def get_vol_percentile(df, lookback=20):
    if len(df) < lookback:
        lookback = len(df)
    recent_vols = df.iloc[-lookback:]['volume']
    today_vol = df.iloc[-1]['volume']
    pct = (recent_vols < today_vol).sum() / len(recent_vols)
    return pct


# ============================================================
# 【位置计算】
# ============================================================
def get_position_level(df, end_idx, lookback=POSITION_LOOKBACK):
    if end_idx < lookback:
        lookback = end_idx
    recent_df = df.iloc[end_idx-lookback+1:end_idx+1]
    today_price = df.iloc[end_idx]['close']
    pct = (recent_df['close'] < today_price).sum() / len(recent_df)
    
    if pct < LOW_PCTL:
        return "低位"
    elif pct > HIGH_PCTL:
        return "高位"
    else:
        return "中位"


# ============================================================
# 数据读取
# ============================================================
def load_klines(market, code):
    possible_paths = [
        DATA_DIR / market / f"{code}.json",
        DATA_DIR / market / f"{market}{code}.json",
        DATA_DIR / f"{market}{code}.json",
    ]
    for filepath in possible_paths:
        if filepath.exists():
            with open(filepath, 'r') as f:
                data = json.load(f)
            klines = data.get('klines', [])
            if not klines:
                return None
            ncols = len(klines[0])
            cols = ['date', 'open', 'close', 'high', 'low', 'volume'] if ncols == 6 else ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            df = pd.DataFrame(klines)
            df = df.iloc[:, :ncols]
            df.columns = cols[:ncols]
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
            return df
    return None


# ============================================================
# 【自动扫描所有股票】
# ============================================================
def scan_all_stocks():
    stocks = []
    for market, code in HOLDINGS:
        stocks.append((market, code))
    sh_dir = DATA_DIR / "sh"
    if sh_dir.exists():
        for f in sh_dir.glob("*.json"):
            code = f.stem
            if not any(c == code for _, c in stocks):
                stocks.append(("sh", code))
    sz_dir = DATA_DIR / "sz"
    if sz_dir.exists():
        for f in sz_dir.glob("*.json"):
            code = f.stem
            if not any(c == code for _, c in stocks):
                stocks.append(("sz", code))
    if len(stocks) > MAX_STOCKS:
        stocks = stocks[:MAX_STOCKS]
    return stocks


# ============================================================
# 【核心：回踩买入判断】
# ============================================================
def check_pullback_buy(df, confirm_idx, support_price, max_wait_days=MAX_WAIT_DAYS):
    if support_price is None or support_price <= 0:
        return None
    n = len(df)
    for i in range(confirm_idx + 1, min(confirm_idx + 1 + max_wait_days, n - 2)):
        today = df.iloc[i]
        yesterday = df.iloc[i - 1]
        touch_low = today['low'] <= support_price * (1 + TOUCH_TOLERANCE)
        if STAY_ABOVE:
            stay_above = today['close'] >= support_price * (1 - TOUCH_TOLERANCE)
        else:
            stay_above = True
        shrink_vol = today['volume'] < yesterday['volume'] * SHRINK_VOL_RATIO
        if touch_low and stay_above and shrink_vol:
            buy_idx = i + 1
            if buy_idx < n:
                return buy_idx
    return None


# ============================================================
# 【动态卖出判断】
# ============================================================
def check_dynamic_sell(df, buy_idx, support_price, max_hold_days=60):
    """
    动态止损：买入后盯关键支撑位，跌破就卖
    最多持有max_hold_days天，到期收盘卖
    返回：卖出日索引
    """
    n = len(df)
    sell_idx = min(buy_idx + max_hold_days, n - 1)
    
    # 从买入后第二天开始，每天检查是否跌破支撑位
    for i in range(buy_idx + 1, n):
        today = df.iloc[i]
        # 收盘价跌破支撑位，就卖
        if today['close'] < support_price * (1 - TOUCH_TOLERANCE):
            sell_idx = i
            break
    
    return sell_idx


# ============================================================
# 【信号判断函数】
# ============================================================

def check_bei_liang(df, i):
    if i < 2:
        return False, None
    today_vol = df.iloc[i]['volume']
    yesterday_vol = df.iloc[i-1]['volume']
    if yesterday_vol > 0 and today_vol / yesterday_vol >= BEISHU_RATIO:
        support = df.iloc[i]['open']
        return True, support
    return False, None


def check_gao_liang(df, i):
    if i < GAOLIANG_LOOKBACK:
        return False, None
    recent = df.iloc[i-GAOLIANG_LOOKBACK:i+1]
    today_vol = df.iloc[i]['volume']
    if today_vol == recent['volume'].max():
        support = df.iloc[i]['low']
        return True, support
    return False, None


def check_di_liang(df, i):
    if i < GAOLIANG_LOOKBACK:
        return False, None
    recent = df.iloc[i-GAOLIANG_LOOKBACK:i+1]
    today_vol = df.iloc[i]['volume']
    if today_vol == recent['volume'].min():
        support = df.iloc[i]['low']
        return True, support
    return False, None


def check_ti_liang(df, i):
    if i < 3:
        return False, None
    v1 = df.iloc[i-2]['volume']
    v2 = df.iloc[i-1]['volume']
    v3 = df.iloc[i]['volume']
    if v1 < v2 < v3:
        support = df.iloc[i-2]['open']
        return True, support
    return False, None


def check_suo_liang(df, i):
    if i < 3:
        return False, None
    v1 = df.iloc[i-2]['volume']
    v2 = df.iloc[i-1]['volume']
    v3 = df.iloc[i]['volume']
    if v1 > v2 > v3:
        support = df.iloc[i-2]['open']
        return True, support
    return False, None


def check_ping_liang(df, i):
    if i < 6:
        return False, None
    today_vol = df.iloc[i]['volume']
    recent_5_avg = df.iloc[i-5:i]['volume'].mean()
    if recent_5_avg > 0:
        diff_pct = abs(today_vol - recent_5_avg) / recent_5_avg
        if diff_pct <= PINGLIANG_TOLERANCE:
            support = df.iloc[i]['close']
            return True, support
    return False, None


def check_xiao_bei_yang(df, i):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    body_pct = (today['close'] - today['open']) / today['open'] * 100
    vol_ratio = today['volume'] / yesterday['volume'] if yesterday['volume'] > 0 else 0
    if 0 < body_pct < 3 and SMALL_BEISHU_MIN <= vol_ratio < SMALL_BEISHU_MAX:
        support = today['open']
        return True, support
    return False, None


def check_yang_sheng_jin(df, i):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    if today['close'] > today['open'] and today['volume'] > yesterday['volume'] and today['close'] > yesterday['close']:
        support = today['open']
        return True, support
    return False, None


def check_yin_sheng_chu(df, i):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    if today['close'] < today['open'] and today['volume'] > yesterday['volume'] and today['close'] < yesterday['close']:
        support = today['close']
        return True, support
    return False, None


def check_chang_duan_yin(df, i, atr_pct):
    if i < 6:
        return False, None
    today = df.iloc[i]
    body_pct_down = (today['open'] - today['close']) / today['close'] * 100
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    vol_pctl = get_vol_percentile(df.iloc[:i+1], VOL_LOOKBACK)
    if body_pct_down > changyang_thresh and vol_pctl < LONG_YIN_SHORT_VOL_PCTL:
        support = today['low']
        return True, support
    return False, None


def check_yang_bao_yin(df, i):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    if today['close'] > yesterday['open'] and today['open'] < yesterday['close'] and today['close'] > today['open']:
        support = today['open']
        return True, support
    return False, None


def check_ban_zhang(df, i, code):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    pct = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    limit_up = LIMIT_UP_GEM if is_gem_star(code) else LIMIT_UP_MAIN
    if pct >= limit_up:
        support = today['open']
        return True, support
    return False, None


def check_guo_zuofeng(df, i, peak_20):
    if peak_20 is None:
        return False, None
    today = df.iloc[i]
    if today['close'] > peak_20:
        support = peak_20
        return True, support
    return False, None


def check_jiayin_ciyang(df, i, atr_pct):
    if i < 6:
        return False, None
    today = df.iloc[i]
    recent_5 = df.iloc[i-5:i]
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    for j in range(len(recent_5)-2, 0, -1):
        row = recent_5.iloc[j]
        drop_pct = (row['close'] - row['open']) / row['open'] * 100
        if drop_pct < -changyang_thresh:
            if today['close'] > today['open']:
                yin_body_size = row['open'] - row['close']
                rebound_size = today['close'] - row['close']
                if yin_body_size > 0 and rebound_size / yin_body_size > 0.5:
                    support = row['close']
                    return True, support
            break
    return False, None


def check_changyang_aizhu(df, i, atr_pct):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    chongyang_up_pct = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    vol_pctl = get_vol_percentile(df.iloc[:i+1], VOL_LOOKBACK)
    if chongyang_up_pct > changyang_thresh and vol_pctl < 0.5:
        support = today['open']
        return True, support
    return False, None


def check_beiliang_buchuan(df, i, code):
    if i < 60:
        return False, None
    recent_60 = df.iloc[i-59:i+1]
    for j in range(len(recent_60)-1, 5, -1):
        row = recent_60.iloc[j]
        prev_row = recent_60.iloc[j-1]
        if prev_row['volume'] > 0 and row['volume'] / prev_row['volume'] >= BEISHU_RATIO and row['close'] > row['open']:
            beiliang_bottom = row['open']
            future = recent_60.iloc[j+1:]
            if len(future) > 0 and all(future['low'] >= beiliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                support = beiliang_bottom
                return True, support
            break
    return False, None


def check_gaoliang_bupo(df, i):
    if i < 60:
        return False, None
    recent_60 = df.iloc[i-59:i+1]
    max_vol_idx = recent_60['volume'].idxmax()
    max_vol_row = recent_60.loc[max_vol_idx]
    gaoliang_bottom = max_vol_row['low']
    future = recent_60.iloc[max_vol_idx + 1:]
    if len(future) > 0 and all(future['low'] >= gaoliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
        support = gaoliang_bottom
        return True, support
    return False, None


def check_diliang_qun(df, i):
    if i < 100:
        return False, None
    recent_100 = df.iloc[i-99:i+1]
    vol_low_pctl = recent_100['volume'].quantile(VOL_PCTL_LOW)
    low_vol_count = sum(recent_100['volume'] <= vol_low_pctl)
    if low_vol_count >= 5:
        last_diliang = recent_100[recent_100['volume'] <= vol_low_pctl].iloc[-1]
        support = last_diliang['low']
        return True, support
    return False, None


def check_jiasheng_liangsou(df, i):
    if i < 3:
        return False, None
    recent_3 = df.iloc[i-2:i+1]
    prices_up = all(recent_3.iloc[j]['close'] > recent_3.iloc[j-1]['close'] for j in range(1, len(recent_3)))
    vols_down = all(recent_3.iloc[j]['volume'] < recent_3.iloc[j-1]['volume'] for j in range(1, len(recent_3)))
    if prices_up and vols_down:
        support = recent_3.iloc[0]['open']
        return True, support
    return False, None


def check_beishuo_shensuo(df, i):
    if i < 5:
        return False, None
    recent_5 = df.iloc[i-4:i+1]
    vols_pctl = (recent_5['volume'].rank(pct=True)).values
    for j in range(1, len(vols_pctl)):
        if vols_pctl[j] >= BEISHUO_EXTEND_PCTL and vols_pctl[j-1] <= BEISHUO_SHRINK_PCTL:
            support = recent_5.iloc[j]['open']
            return True, support
    return False, None


def check_huicai_jingzhun(df, i, precise_price):
    if precise_price is None:
        return False, None
    if i < 10:
        return False, None
    recent_10 = df.iloc[i-9:i+1]
    touched = any(abs(row['low'] - precise_price) / precise_price < TOUCH_TOLERANCE for _, row in recent_10.iterrows())
    if touched:
        support = precise_price
        return True, support
    return False, None


# ============================================================
# 【找峰顶线/谷底线】
# ============================================================
def find_fenggu_at(df, end_idx, lookback_days, peak_side, confirm_days, vol_percentile):
    min_required = lookback_days + confirm_days + peak_side
    if end_idx < min_required:
        return None, None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    vol_threshold = recent_df['volume'].quantile(vol_percentile)
    peaks, valleys = [], []
    start = peak_side
    end = len(recent_df) - max(peak_side, confirm_days)
    for i in range(start, end):
        row = recent_df.iloc[i]
        window = recent_df.iloc[i-peak_side:i+peak_side+1]
        is_local_high = row['high'] == window['high'].max()
        is_local_low = row['low'] == window['low'].min()
        has_vol = row['volume'] >= vol_threshold
        if is_local_high and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            if all(future['close'] < row['high']):
                peaks.append({'price': row['high'], 'date': row['date']})
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            if all(future['close'] > row['low']):
                valleys.append({'price': row['low'], 'date': row['date']})
    recent_peak = peaks[-1] if peaks else None
    recent_valley = valleys[-1] if valleys else None
    return (recent_peak['price'] if recent_peak else None,
            recent_valley['price'] if recent_valley else None)


# ============================================================
# 【找精准线】
# ============================================================
def find_precise_at(df, end_idx, lookback_days=120, min_points=3, price_tolerance=1.0):
    if end_idx < lookback_days:
        return None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    prices = recent_df['close'].values
    if len(prices) < min_points:
        return None
    clusters = {}
    used = set()
    for i in range(len(prices)):
        if i in used:
            continue
        cluster = [i]
        for j in range(len(prices)):
            if i == j or j in used:
                continue
            diff_pct = abs(prices[i] - prices[j]) / prices[i] * 100
            if diff_pct <= price_tolerance:
                cluster.append(j)
        if len(cluster) >= min_points:
            avg_price = np.mean([prices[idx] for idx in cluster])
            clusters[len(cluster)] = avg_price
            for idx in cluster:
                used.add(idx)
    if clusters:
        return clusters[max(clusters.keys())]
    return None


# ============================================================
# 【找大阴实顶】
# ============================================================
def find_big_yin_top_at(df, end_idx, lookback_days, yin_body_pct):
    if end_idx < lookback_days:
        return None, None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        if row['close'] >= row['open']:
            continue
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        if body_pct >= yin_body_pct:
            return row['open'], row['date']
    return None, None


# ============================================================
# 【找王牌柱】
# ============================================================
def find_pillars_at(df, end_idx, lookback_days=60):
    if end_idx < lookback_days + GENERAL_CONFIRM_DAYS + 20:
        return "无", None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    marshals = []
    goldens = []
    generals = []
    for i in range(len(recent_df) - GENERAL_CONFIRM_DAYS - 1, 5, -1):
        row = recent_df.iloc[i]
        if row['close'] <= row['open']:
            continue
        if i < 20:
            continue
        vol_window = recent_df.iloc[i-20:i]['volume']
        vol_pctl = (vol_window < row['volume']).sum() / len(vol_window)
        if vol_pctl < BASE_VOL_PCTL:
            continue
        future = recent_df.iloc[i+1:i+1+GENERAL_CONFIRM_DAYS]
        if len(future) < GENERAL_CONFIRM_DAYS:
            continue
        base_open = row['open']
        base_close = row['close']
        future_avg_close = future['close'].mean()
        if future_avg_close < base_open:
            continue
        future_last_vol = future.iloc[-1]['volume']
        base_vol = row['volume']
        if future_last_vol >= base_vol:
            continue
        is_golden = future_avg_close >= base_close
        if i > 0:
            prev_row = recent_df.iloc[i-1]
            is_gap_up = row['open'] > prev_row['high']
        else:
            is_gap_up = False
        if is_golden and is_gap_up:
            marshals.append(row['low'])
        elif is_golden:
            goldens.append(row['low'])
        else:
            generals.append(row['low'])
    if marshals:
        return "元帅柱", marshals[0]
    elif goldens:
        return "黄金柱", goldens[0]
    elif generals:
        return "将军柱", generals[0]
    else:
        return "无", None


# ============================================================
# 【主函数】
# ============================================================
def main():
    print("=" * 70)
    print("四维循环看盘法 - 历史回测验证（最终完整版）")
    print("=" * 70)
    
    all_stocks = scan_all_stocks()
    
    print(f"\n自动扫描到股票数：{len(all_stocks)}只")
    print(f"（最多跑{MAX_STOCKS}只，避免超时）")
    print(f"持有周期：{HOLD_PERIODS}个交易日（固定持有对照组）")
    print(f"回测标准：信号确认后 → 等回踩关键位 → 缩量企稳 → T+1开盘买")
    print(f"交易成本：{TOTAL_COST*100:.2f}%（买入+卖出）")
    print(f"动态止损：跌破关键位就卖，最多持有60天")
    print(f"位置分档：低位<{LOW_PCTL*100:.0f}% / 中位{LOW_PCTL*100:.0f}%-{HIGH_PCTL*100:.0f}% / 高位>{HIGH_PCTL*100:.0f}%\n")
    
    # 结构：{信号名: {位置: {持有天数: [收益列表]}}}
    all_trades = defaultdict(lambda: defaultdict(lambda: {h: [] for h in HOLD_PERIODS}))
    # 动态止损的结果
    dynamic_trades = defaultdict(lambda: defaultdict(list))
    
    for idx, (market, code) in enumerate(all_stocks):
        print(f"  回测中 {idx+1}/{len(all_stocks)}: {market}{code} ...")
        df = load_klines(market, code)
        if df is None:
            continue
        full_code = f"{market}{code}"
        n = len(df)
        start_idx = 120
        
        for i in range(start_idx, n - 60 - MAX_WAIT_DAYS - 2):
            atr_value, atr_pct = calculate_atr(df.iloc[:i+1], ATR_PERIOD)
            yin_body_thresh = get_atr_threshold(atr_pct, YIN_BODY_ATR_MULT, YIN_BODY_FALLBACK)
            
            peak_20, valley_20 = find_fenggu_at(df, i, SHORT_WINDOW, PEAK_SIDE_SHORT, CONFIRM_DAYS_SHORT, VOL_PERCENTILE)
            precise_price = find_precise_at(df, i)
            big_yin_top, big_yin_date = find_big_yin_top_at(df, i, YIN_LOOKBACK, yin_body_thresh)
            pillar_type, golden_line = find_pillars_at(df, i)
            
            position = get_position_level(df, i)
            
            signals_today = []
            
            # 量柱六种
            ok, support = check_bei_liang(df, i)
            if ok:
                signals_today.append(("倍量柱", support))
            ok, support = check_gao_liang(df, i)
            if ok:
                signals_today.append(("高量柱", support))
            ok, support = check_di_liang(df, i)
            if ok:
                signals_today.append(("低量柱（地量）", support))
            ok, support = check_ti_liang(df, i)
            if ok:
                signals_today.append(("梯量柱", support))
            ok, support = check_suo_liang(df, i)
            if ok:
                signals_today.append(("缩量柱", support))
            ok, support = check_ping_liang(df, i)
            if ok:
                signals_today.append(("平量柱", support))
            
            # 形态信号
            ok, support = check_xiao_bei_yang(df, i)
            if ok:
                signals_today.append(("小倍阳（矮将军）", support))
            ok, support = check_yang_sheng_jin(df, i)
            if ok:
                signals_today.append(("阳胜进", support))
            ok, support = check_yin_sheng_chu(df, i)
            if ok:
                signals_today.append(("阴胜出", support))
            ok, support = check_chang_duan_yin(df, i, atr_pct)
            if ok:
                signals_today.append(("长阴短柱", support))
            ok, support = check_yang_bao_yin(df, i)
            if ok:
                signals_today.append(("阳包阴", support))
            ok, support = check_ban_zhang(df, i, full_code)
            if ok:
                signals_today.append(("涨停板", support))
            ok, support = check_guo_zuofeng(df, i, peak_20)
            if ok:
                signals_today.append(("过左峰", support))
            ok, support = check_jiayin_ciyang(df, i, atr_pct)
            if ok:
                signals_today.append(("极阴次阳", support))
            ok, support = check_changyang_aizhu(df, i, atr_pct)
            if ok:
                signals_today.append(("长阳矮柱", support))
            ok, support = check_beiliang_buchuan(df, i, full_code)
            if ok:
                signals_today.append(("倍量不穿", support))
            ok, support = check_gaoliang_bupo(df, i)
            if ok:
                signals_today.append(("高量不破", support))
            ok, support = check_diliang_qun(df, i)
            if ok:
                signals_today.append(("地量群", support))
            ok, support = check_jiasheng_liangsou(df, i)
            if ok:
                signals_today.append(("价升量缩", support))
            ok, support = check_beishuo_shensuo(df, i)
            if ok:
                signals_today.append(("倍量伸缩", support))
            ok, support = check_huicai_jingzhun(df, i, precise_price)
            if ok:
                signals_today.append(("回踩精准线", support))
            
            # 王牌柱
            if pillar_type == "元帅柱":
                signals_today.append(("元帅柱", golden_line))
            elif pillar_type == "黄金柱":
                signals_today.append(("黄金柱", golden_line))
            elif pillar_type == "将军柱":
                signals_today.append(("将军柱", golden_line))
            
            # 量线信号
            if valley_20:
                today = df.iloc[i]
                touched = abs(today['low'] - valley_20) / valley_20 < TOUCH_TOLERANCE
                if touched and today['close'] > valley_20:
                    signals_today.append(("回踩谷底线不破", valley_20))
            
            if big_yin_top:
                today = df.iloc[i]
                if today['close'] > big_yin_top:
                    signals_today.append(("突破大阴实顶", big_yin_top))
            
            # 对每个信号，找回踩买入点
            for signal_name, support_price in signals_today:
                buy_idx = check_pullback_buy(df, i, support_price)
                if buy_idx is None:
                    continue
                
                buy_today = df.iloc[buy_idx]
                buy_yesterday = df.iloc[buy_idx - 1]
                if buy_today['open'] == buy_today['close'] and (buy_today['close'] - buy_yesterday['close']) / buy_yesterday['close'] * 100 > 9.5:
                    continue
                
                bp = df.iloc[buy_idx]['open']
                
                # 1. 固定持有期（对照组）
                for hold_days in HOLD_PERIODS:
                    sell_idx = buy_idx + hold_days
                    if sell_idx >= n:
                        continue
                    sp = df.iloc[sell_idx]['close']
                    if bp <= 0:
                        continue
                    ret = (sp - bp) / bp * 100 - TOTAL_COST * 100  # 扣交易成本
                    all_trades[signal_name][position][hold_days].append(ret)
                
                # 2. 动态止损（按量学官方）
                sell_idx_dynamic = check_dynamic_sell(df, buy_idx, support_price)
                if sell_idx_dynamic < n:
                    sp_dynamic = df.iloc[sell_idx_dynamic]['close']
                    if bp > 0:
                        ret_dynamic = (sp_dynamic - bp) / bp * 100 - TOTAL_COST * 100
                        dynamic_trades[signal_name][position].append(ret_dynamic)
    
    # 输出结果
    print("\n" + "=" * 70)
    print("四维循环看盘法 - 历史回测结果（最终完整版）")
    print("=" * 70)
    print(f"\n总股票数：{len(all_stocks)}只")
    print(f"交易成本：已扣除{TOTAL_COST*100:.2f}%\n")
    
    positions = ["低位", "中位", "高位"]
    
    # 固定持有期结果
    for hold_days in HOLD_PERIODS:
        print(f"\n=== 固定持有{hold_days}天 ===")
        
        for pos in positions:
            print(f"\n--- {pos} ---")
            print(f"{'信号':<20} {'样本数':>8} {'平均收益%':>10} {'中位数%':>10} {'胜率%':>8} {'结论':>10}")
            print("-" * 70)
            
            sorted_signals = sorted(all_trades.keys(), key=lambda x: len(all_trades[x][pos][hold_days]), reverse=True)
            
            for signal_name in sorted_signals:
                returns = all_trades[signal_name][pos][hold_days]
                count = len(returns)
                if count < 5:
                    continue
                avg_ret = np.mean(returns)
                median_ret = np.median(returns)
                win_rate = sum(1 for r in returns if r > 0) / count * 100
                
                if win_rate > 55 and avg_ret > 0:
                    conclusion = "✅ 有效"
                elif win_rate > 50:
                    conclusion = "⚠️ 一般"
                else:
                    conclusion = "❌ 无效"
                
                print(f"{signal_name:<20} {count:>8} {avg_ret:>10.2f} {median_ret:>10.2f} {win_rate:>8.1f} {conclusion:>10}")
    
    # 动态止损结果
    print("\n" + "=" * 70)
    print("\n=== 动态止损版（跌破关键位就卖） ===")
    
    for pos in positions:
        print(f"\n--- {pos} ---")
        print(f"{'信号':<20} {'样本数':>8} {'平均收益%':>10} {'中位数%':>10} {'胜率%':>8} {'结论':>10}")
        print("-" * 70)
        
        sorted_signals = sorted(dynamic_trades.keys(), key=lambda x: len(dynamic_trades[x][pos]), reverse=True)
        
        for signal_name in sorted_signals:
            returns = dynamic_trades[signal_name][pos]
            count = len(returns)
            if count < 5:
                continue
            avg_ret = np.mean(returns)
            median_ret = np.median(returns)
            win_rate = sum(1 for r in returns if r > 0) / count * 100
            
            if win_rate > 55 and avg_ret > 0:
                conclusion = "✅ 有效"
            elif win_rate > 50:
                conclusion = "⚠️ 一般"
            else:
                conclusion = "❌ 无效"
            
            print(f"{signal_name:<20} {count:>8} {avg_ret:>10.2f} {median_ret:>10.2f} {win_rate:>8.1f} {conclusion:>10}")
    
    print("\n" + "=" * 70)
    print("结论说明：")
    print("- ✅ 胜率>55% 且 平均收益>0：信号有效，有统计意义")
    print("- ⚠️ 胜率50%-55%：信号一般，参考价值有限")
    print("- ❌ 胜率<50%：信号无效，甚至反向使用")
    print("=" * 70)
    
    # 保存结果
    output_dir = Path(__file__).parent.parent / "data" / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    summary_file = output_dir / "backtest_4d_final_summary.txt"
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("四维循环看盘法 - 最终完整版历史回测结果\n")
        f.write(f"股票数：{len(all_stocks)}只\n")
        f.write(f"交易成本：已扣除{TOTAL_COST*100:.2f}%\n")
        f.write(f"位置分档：低位<30% / 中位30%-70% / 高位>70%\n\n")
        
        f.write("=== 固定持有期结果 ===\n")
        for hold_days in HOLD_PERIODS:
            f.write(f"\n--- 持有{hold_days}天 ---\n")
            for pos in positions:
                f.write(f"\n{pos}:\n")
                sorted_signals = sorted(all_trades.keys(), key=lambda x: len(all_trades[x][pos][hold_days]), reverse=True)
                for signal_name in sorted_signals:
                    returns = all_trades[signal_name][pos][hold_days]
                    count = len(returns)
                    if count < 5:
                        continue
                    avg_ret = np.mean(returns)
                    median_ret = np.median(returns)
                    win_rate = sum(1 for r in returns if r > 0) / count * 100
                    f.write(f"{signal_name}: 样本{count}个, 平均{avg_ret:.2f}%, 中位{median_ret:.2f}%, 胜率{win_rate:.1f}%\n")
        
        f.write("\n\n=== 动态止损版结果 ===\n")
        for pos in positions:
            f.write(f"\n{pos}:\n")
            sorted_signals = sorted(dynamic_trades.keys(), key=lambda x: len(dynamic_trades[x][pos]), reverse=True)
            for signal_name in sorted_signals:
                returns = dynamic_trades[signal_name][pos]
                count = len(returns)
                if count < 5:
                    continue
                avg_ret = np.mean(returns)
                median_ret = np.median(returns)
                win_rate = sum(1 for r in returns if r > 0) / count * 100
                f.write(f"{signal_name}: 样本{count}个, 平均{avg_ret:.2f}%, 中位{median_ret:.2f}%, 胜率{win_rate:.1f}%\n")
    
    print(f"\n已保存统计结果: {summary_file}")


if __name__ == "__main__":
    main()
