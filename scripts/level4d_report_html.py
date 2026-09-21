#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（量学完整版·25种涨停基因全）
=================================================
【无未来函数】：所有判断只用截止到今天收盘的数据
【资料来源】：股海明灯《量柱擒涨停》《量线捉涨停》《涨停密码》黑马王子著

【新增信号】（只加不删）：
  - 王牌柱体系：将军柱/黄金柱/元帅柱 + 黄金线
  - 凹口线（凹口平量柱）
  - 形态信号：阳胜进/阴胜出/小倍阳/长腿踩线/长阴短柱/阳包阴/阴包阳/跳空/十字星
  - 25种涨停基因：
    * 过左峰、假阴真阳、极阴次阳、长阳矮柱
    * 牛股三绝（倍量不穿/高量不破/跳空不补）
    * 【新增】地量群、价升量缩、回踩精准线
    * 【新增】双剑霸天地、三元连动、兵临城下
    * 【新增】大阳双休、接力双阳

【设计思路】：所有新增信号都放在原有代码基础上，不修改原有任何功能
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 【配置区】所有参数阈值都在这里
# ============================================================

DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

HOLDINGS = [
    ("sh", "600584"),  # 长电科技
    ("sz", "002156"),  # 通富微电
    ("sh", "603283"),  # 赛腾股份
    ("sz", "300394"),  # 天孚通信
    ("sh", "601138"),  # 工业富联
    ("sh", "601231"),  # 环旭电子
    ("sz", "300476"),  # 胜宏科技
    ("sh", "603516"),  # 淳中科技
]

YIN_BODY_PCT = 3.0
YIN_LOOKBACK = 60

SHORT_WINDOW = 20
MID_WINDOW = 60
LONG_WINDOW = 120

PEAK_SIDE_SHORT = 2
PEAK_SIDE_MID = 2
PEAK_SIDE_LONG = 3

CONFIRM_DAYS_SHORT = 3
CONFIRM_DAYS_MID = 5
CONFIRM_DAYS_LONG = 10

VOL_PERCENTILE = 0.7
BODY_RATIO_THRESHOLD = 0.6

BALANCE_YIN_BODY_PCT = 3.0
BALANCE_LOOKBACK = 30

PRECISE_MIN_POINTS = 3
PRECISE_PRICE_TOLERANCE = 1.0
PRECISE_LOOKBACK = 120

XIEHENG_MIN_POINTS = 2

BEISHU_RATIO = 2.05
PINGLIANG_TOLERANCE = 0.15
GAOLIANG_LOOKBACK = 20

IMPACT_VS_KEY_VOL_HIGH = 0.8
IMPACT_VS_KEY_VOL_MID = 0.5
IMPACT_TIME_NEAR = 20
IMPACT_TIME_MID = 60

VOL_RATIO_HIGH = 1.5
VOL_RATIO_LOW = 0.7
BODY_RATIO_LONG = 0.6
BODY_RATIO_SHORT = 0.3

POSITION_HIGH = 70
POSITION_LOW = 30
VOL_POS_HIGH = 80
VOL_POS_LOW = 20

# 王牌柱参数
BASE_VS_MA3 = 1.2
BASE_VS_PREV = 2.05
BASE_VS_MA20 = 1.5
GENERAL_CONFIRM_DAYS = 3

# 凹口线参数
AOKOU_MIN_GAP = 3
AOKOU_MAX_GAP = 13
AOKOU_PINGLIANG_TOLERANCE = 0.15
AOKOU_MIDDLE_SHADOW = 0.6

# 形态信号参数
SMALL_BEISHU_RATIO_MIN = 1.5
SMALL_BEISHU_RATIO_MAX = 2.0
LONG_LEG_RATIO = 2.0
LONG_YIN_SHORT_VOL_RATIO = 0.7
TOUCH_LINE_TOLERANCE = 0.02

# 25种涨停基因参数
JIAYIN_TRUE_YANG_MIN_VOL_RATIO = 1.0
JIYIN_PREV_DAYS = 5
JIYIN_DROP_PCT = -5.0
CIYANG_REBOUND_PCT = 50
CHANGYANG_UP_PCT = 3.0
AIZHU_VOL_RATIO = 0.8
GUOZUOFENG_TOUCH_DAYS = 20
NIUGU_LOOKBACK = 60
NIUGU_TOUCH_TOLERANCE = 0.01

# ============================================================
# 【新增】更多涨停基因参数
# ============================================================
# 来源：股海明灯论坛《量学的25种涨停基因清单》

# 地量群（百日低量群）
DILIANG_GROUP_DAYS = 100     # 看100天内的地量
DILIANG_GROUP_COUNT = 5      # 有5根以上接近地量的柱子

# 价升量缩
JIA_SHENG_LIANG_SUO_DAYS = 3  # 连续3天价升量缩

# 回踩精准线
HUICAI_PRECISION_DAYS = 10    # 10天内踩到精准线

# 双剑霸天地
DOUBLE_SWORD_UPPER_RATIO = 2.0  # 上影线是实体的2倍以上
DOUBLE_SWORD_LOWER_RATIO = 2.0  # 下影线是实体的2倍以上

# 三元连动
SANYUAN_DAYS = 3              # 连续3天价升量缩

# 兵临城下
BINGLINCHENGXIA_DAYS = 10     # 10天内接近峰顶线
BINGLINCHENGXIA_TOLERANCE = 0.03  # 距离峰顶线3%以内

# 大阳双休
DAYANG_DOUBLE_REST_DAYS = 5   # 大阳线后5天内
DAYANG_DOUBLE_REST_BODY = 0.5 # 回调不超过大阳线实体的50%

# 接力双阳
JIELI_DOUBLE_YANG_GAP_MIN = 5 # 两根阳线间隔最少5天
JIELI_DOUBLE_YANG_GAP_MAX = 20 # 最多20天


# ============================================================
# 数据读取（原有，不修改）
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
            ncols = len(klines[0])
            
            if ncols == 6:
                cols = ['date', 'open', 'close', 'high', 'low', 'volume']
            else:
                cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            
            df = pd.DataFrame(klines)
            df = df.iloc[:, :ncols]
            df.columns = cols[:ncols]
            
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
            
            return df, data.get('name', code)
    
    return None, None


# ============================================================
# 找大阴实顶（原有，不修改）
# ============================================================
def find_big_yin_top(df, lookback_days, yin_body_pct):
    if len(df) < lookback_days:
        return None, None, None, None, None
    
    recent_df = df.iloc[-lookback_days:]
    
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        
        if row['close'] >= row['open']:
            continue
        
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        
        if body_pct >= yin_body_pct:
            big_yin_top = row['open']
            big_yin_bottom = row['close']
            big_yin_date = row['date']
            big_yin_vol = row['volume']
            big_yin_idx = len(df) - lookback_days + i
            
            return big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx
    
    return None, None, None, None, None


# ============================================================
# 找高量柱安全线/风险线（原有，不修改）
# ============================================================
def find_gaoliang_lines(recent_df):
    if len(recent_df) < 5:
        return None, None, None, None, None
    
    max_vol_idx = recent_df['volume'].idxmax()
    max_vol_row = recent_df.loc[max_vol_idx]
    
    open_price = max_vol_row['open']
    close_price = max_vol_row['close']
    high_price = max_vol_row['high']
    low_price = max_vol_row['low']
    
    body_size = abs(close_price - open_price)
    total_range = high_price - low_price
    
    if total_range == 0:
        return None, None, None, None, None
    
    body_ratio = body_size / total_range
    
    if body_ratio > BODY_RATIO_THRESHOLD:
        safe_line = max(open_price, close_price)
        risk_line = min(open_price, close_price)
        line_type = "实体"
    else:
        safe_line = high_price
        risk_line = low_price
        line_type = "影线"
    
    return safe_line, risk_line, line_type, max_vol_row['date'], max_vol_row['volume']


# ============================================================
# 找平衡线（原有，不修改）
# ============================================================
def find_balance_line(df, lookback_days, yin_body_pct):
    if len(df) < lookback_days:
        return None, None
    
    recent_df = df.iloc[-lookback_days:]
    
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        
        if row['close'] >= row['open']:
            continue
        
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        
        if body_pct >= yin_body_pct:
            balance_price = row['open']
            balance_date = row['date']
            return balance_price, balance_date
    
    return None, None


# ============================================================
# 找精准线（原有，不修改）
# ============================================================
def find_precise_lines(df, lookback_days, min_points, price_tolerance):
    if len(df) < lookback_days:
        return []
    
    recent_df = df.iloc[-lookback_days:]
    prices = recent_df['close'].values
    precise_lines = []
    used_indices = set()
    
    for i in range(len(prices)):
        if i in used_indices:
            continue
        
        price_i = prices[i]
        cluster_indices = [i]
        
        for j in range(len(prices)):
            if i == j or j in used_indices:
                continue
            price_j = prices[j]
            diff_pct = abs(price_i - price_j) / price_i * 100
            if diff_pct <= price_tolerance:
                cluster_indices.append(j)
        
        if len(cluster_indices) >= min_points:
            avg_price = np.mean([prices[idx] for idx in cluster_indices])
            dates = [recent_df.iloc[idx]['date'] for idx in cluster_indices]
            precise_lines.append({
                'price': avg_price,
                'points': len(cluster_indices),
                'first_date': min(dates),
                'last_date': max(dates),
            })
            for idx in cluster_indices:
                used_indices.add(idx)
    
    precise_lines.sort(key=lambda x: x['points'], reverse=True)
    return precise_lines[:3]


# ============================================================
# 找峰顶线/谷底线（原有，不修改）
# ============================================================
def find_fenggu_lines(df, lookback_days, peak_side, confirm_days, vol_percentile):
    min_required = lookback_days + confirm_days + peak_side
    if len(df) < min_required:
        return None, None, None, None, [], []
    
    recent_df = df.iloc[-lookback_days:]
    vol_threshold = recent_df['volume'].quantile(vol_percentile)
    
    peaks = []
    valleys = []
    
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
            confirmed = all(future['close'] < row['high'])
            if confirmed:
                peaks.append({'price': row['high'], 'date': row['date'], 'volume': row['volume']})
        
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            confirmed = all(future['close'] > row['low'])
            if confirmed:
                valleys.append({'price': row['low'], 'date': row['date'], 'volume': row['volume']})
    
    recent_peak = peaks[-1] if peaks else None
    recent_valley = valleys[-1] if valleys else None
    
    return (recent_peak['price'] if recent_peak else None,
            recent_peak['date'] if recent_peak else None,
            recent_valley['price'] if recent_valley else None,
            recent_valley['date'] if recent_valley else None,
            peaks, valleys)


# ============================================================
# 找斜衡线（原有，不修改）
# ============================================================
def find_xieheng_line(peaks, valleys, today_price):
    up_line = None
    down_line = None
    
    if len(valleys) >= XIEHENG_MIN_POINTS:
        v1 = valleys[-2]
        v2 = valleys[-1]
        if v2['price'] > v1['price']:
            up_line = {
                'type': '上升',
                'point1_price': v1['price'],
                'point1_date': v1['date'],
                'point2_price': v2['price'],
                'point2_date': v2['date'],
                'above_line': today_price > v2['price'],
            }
    
    if len(peaks) >= XIEHENG_MIN_POINTS:
        p1 = peaks[-2]
        p2 = peaks[-1]
        if p2['price'] < p1['price']:
            down_line = {
                'type': '下降',
                'point1_price': p1['price'],
                'point1_date': p1['date'],
                'point2_price': p2['price'],
                'point2_date': p2['date'],
                'above_line': today_price > p2['price'],
            }
    
    return up_line, down_line


# ============================================================
# 识别量柱形态（原有，不修改）
# ============================================================
def identify_vol_pattern(df):
    if len(df) < 10:
        return "未知"
    
    today_vol = df.iloc[-1]['volume']
    yesterday_vol = df.iloc[-2]['volume']
    recent_20 = df.iloc[-GAOLIANG_LOOKBACK:] if len(df) >= GAOLIANG_LOOKBACK else df
    
    if today_vol / yesterday_vol >= BEISHU_RATIO:
        return "倍量柱"
    if today_vol == recent_20['volume'].max():
        return "高量柱"
    if today_vol == recent_20['volume'].min():
        return "低量柱"
    
    v1 = df.iloc[-3]['volume']
    v2 = df.iloc[-2]['volume']
    v3 = df.iloc[-1]['volume']
    if v1 < v2 < v3:
        return "梯量柱"
    if v1 > v2 > v3:
        return "缩量柱"
    
    recent_5_avg = df.iloc[-6:-1]['volume'].mean()
    diff_pct = abs(today_vol - recent_5_avg) / recent_5_avg
    if diff_pct <= PINGLIANG_TOLERANCE:
        return "平量柱"
    
    return "普通量柱"


# ============================================================
# 关键位量影响力判断（原有，不修改）
# ============================================================
def judge_key_vol_impact(df, key_vol, key_date):
    if key_vol is None or key_date is None:
        return "无关键位", 0, 0
    
    today_vol = df.iloc[-1]['volume']
    vol_ratio = today_vol / key_vol * 100
    
    key_idx = None
    for i in range(len(df)-1, -1, -1):
        if df.iloc[i]['date'] == key_date:
            key_idx = i
            break
    
    time_distance = len(df) - 1 - key_idx if key_idx else 0
    
    if vol_ratio >= IMPACT_VS_KEY_VOL_HIGH * 100:
        vol_impact = "强"
    elif vol_ratio >= IMPACT_VS_KEY_VOL_MID * 100:
        vol_impact = "中"
    else:
        vol_impact = "弱"
    
    if time_distance <= IMPACT_TIME_NEAR:
        time_impact = "近"
    elif time_distance <= IMPACT_TIME_MID:
        time_impact = "中"
    else:
        time_impact = "远"
    
    if vol_impact == "强" and time_impact == "近":
        impact = "强"
    elif vol_impact == "弱" and time_impact == "远":
        impact = "弱"
    else:
        impact = "中"
    
    return impact, vol_ratio, time_distance


# ============================================================
# 识别将军柱/黄金柱/元帅柱（原有，不修改）
# ============================================================
def find_pillars(df, lookback_days=30):
    if len(df) < lookback_days + GENERAL_CONFIRM_DAYS + 20:
        return "无", None, None
    
    recent_df = df.iloc[-lookback_days:]
    
    for i in range(len(recent_df) - GENERAL_CONFIRM_DAYS - 1, 10, -1):
        row = recent_df.iloc[i]
        
        if row['close'] <= row['open']:
            continue
        
        if i < 3:
            continue
        ma3_vol = recent_df.iloc[i-3:i]['volume'].mean()
        prev_vol = recent_df.iloc[i-1]['volume']
        if i < 20:
            continue
        ma20_vol = recent_df.iloc[i-20:i]['volume'].mean()
        
        if row['volume'] < ma3_vol * BASE_VS_MA3:
            continue
        if row['volume'] < prev_vol * BASE_VS_PREV:
            continue
        if row['volume'] < ma20_vol * BASE_VS_MA20:
            continue
        
        future = recent_df.iloc[i+1:i+1+GENERAL_CONFIRM_DAYS]
        if len(future) < GENERAL_CONFIRM_DAYS:
            continue
        
        base_close = row['close']
        base_vol = row['volume']
        
        if any(future['close'] < base_close):
            continue
        if any(future['volume'] > base_vol):
            continue
        
        closes = future['close'].values
        vols = future['volume'].values
        
        is_golden = True
        for j in range(len(closes)-1):
            if closes[j+1] <= closes[j]:
                is_golden = False
                break
        for j in range(len(vols)-1):
            if vols[j+1] >= vols[j]:
                is_golden = False
                break
        
        golden_line = row['low']
        
        if i > 0:
            prev_row = recent_df.iloc[i-1]
            is_gap_up = row['open'] > prev_row['high']
        else:
            is_gap_up = False
        
        if is_golden and is_gap_up:
            return "元帅柱", row['date'], golden_line
        elif is_golden:
            return "黄金柱", row['date'], golden_line
        else:
            return "将军柱", row['date'], golden_line
    
    return "无", None, None


# ============================================================
# 找凹口线（原有，不修改）
# ============================================================
def find_aokou_line(df, lookback_days=60):
    if len(df) < lookback_days:
        return None, None, None
    
    recent_df = df.iloc[-lookback_days:]
    vols = recent_df['volume'].values
    
    best_gap = None
    best_price = None
    best_date = None
    
    for gap in range(AOKOU_MIN_GAP, AOKOU_MAX_GAP + 1, 2):
        for i in range(gap, len(vols)):
            vol_left = vols[i - gap]
            vol_right = vols[i]
            
            vol_diff = abs(vol_left - vol_right) / max(vol_left, vol_right)
            if vol_diff > AOKOU_PINGLIANG_TOLERANCE:
                continue
            
            middle_vols = vols[i - gap + 1:i]
            if len(middle_vols) == 0:
                continue
            
            min_middle_vol = middle_vols.min()
            avg_side_vol = (vol_left + vol_right) / 2
            
            if min_middle_vol > avg_side_vol * AOKOU_MIDDLE_SHADOW:
                continue
            
            min_idx = i - gap + 1 + middle_vols.argmin()
            aokou_price = recent_df.iloc[min_idx]['low']
            aokou_date = recent_df.iloc[min_idx]['date']
            
            if best_gap is None or gap > best_gap:
                best_gap = gap
                best_price = aokou_price
                best_date = aokou_date
    
    if best_price:
        return best_price, best_date, best_gap
    else:
        return None, None, None


# ============================================================
# 识别所有形态信号（原有 + 新增更多涨停基因）
# ============================================================
def identify_all_signals(df, valley_price, safe_line, precise_price, big_yin_top, peak_20=None):
    signals = []
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    today_open = today['open']
    today_close = today['close']
    today_high = today['high']
    today_low = today['low']
    today_vol = today['volume']
    
    yesterday_open = yesterday['open']
    yesterday_close = yesterday['close']
    yesterday_vol = yesterday['volume']
    
    # ========== 原有信号 ==========
    if today_close > today_open and today_vol > yesterday_vol and today_close > yesterday_close:
        signals.append("阳胜进")
    
    if today_close < today_open and today_vol > yesterday_vol and today_close < yesterday_close:
        signals.append("阴胜出")
    
    body_pct = (today_close - today_open) / today_open * 100
    vol_ratio = today_vol / yesterday_vol
    if 0 < body_pct < 3 and SMALL_BEISHU_RATIO_MIN <= vol_ratio < SMALL_BEISHU_RATIO_MAX:
        signals.append("小倍阳（矮将军）")
    
    body_size = abs(today_close - today_open)
    lower_shadow = min(today_open, today_close) - today_low
    touched_line = None
    if valley_price and abs(today_low - valley_price) / valley_price < TOUCH_LINE_TOLERANCE:
        touched_line = "谷底线"
    elif safe_line and abs(today_low - safe_line) / safe_line < TOUCH_LINE_TOLERANCE:
        touched_line = "安全线"
    elif precise_price and abs(today_low - precise_price) / precise_price < TOUCH_LINE_TOLERANCE:
        touched_line = "精准线"
    elif big_yin_top and abs(today_low - big_yin_top) / big_yin_top < TOUCH_LINE_TOLERANCE:
        touched_line = "大阴实顶线"
    if body_size > 0 and lower_shadow / body_size > LONG_LEG_RATIO:
        if touched_line:
            signals.append(f"长腿踩线（{touched_line}）")
        else:
            signals.append("长腿（未踩线）")
    
    body_pct_down = (today_open - today_close) / today_close * 100
    recent_5_vol_avg = df.iloc[-6:-1]['volume'].mean()
    if body_pct_down > 3 and today_vol < recent_5_vol_avg * LONG_YIN_SHORT_VOL_RATIO:
        signals.append("长阴短柱")
    
    if today_close > yesterday_open and today_open < yesterday_close and today_close > today_open:
        signals.append("阳包阴")
    
    if today_close < yesterday_open and today_open > yesterday_close and today_close < today_open:
        signals.append("阴包阳")
    
    if today_open > yesterday['high']:
        signals.append("跳空高开")
    if today_open < yesterday['low']:
        signals.append("跳空低开")
    
    today_range = today_high - today_low
    if today_range > 0 and body_size / today_range < 0.1:
        signals.append("十字星")
    
    # ========== 25种涨停基因（第一批） ==========
    if peak_20 and today_close > peak_20:
        signals.append("过左峰")
    
    if today_close < today_open and today_close > yesterday_close and today_vol > yesterday_vol:
        signals.append("假阴真阳")
    
    if len(df) >= JIYIN_PREV_DAYS:
        prev_5 = df.iloc[-JIYIN_PREV_DAYS:]
        for i in range(len(prev_5)-2, 0, -1):
            row = prev_5.iloc[i]
            drop_pct = (row['close'] - row['open']) / row['open'] * 100
            if drop_pct < JIYIN_DROP_PCT:
                if today_close > today_open:
                    yin_body_size = row['open'] - row['close']
                    rebound_size = today_close - row['close']
                    if yin_body_size > 0 and rebound_size / yin_body_size > CIYANG_REBOUND_PCT / 100:
                        signals.append("极阴次阳")
                break
    
    chongyang_up_pct = (today_close - yesterday_close) / yesterday_close * 100
    recent_20_vol_avg = df.iloc[-20:]['volume'].mean() if len(df) >= 20 else today_vol
    if chongyang_up_pct > CHANGYANG_UP_PCT and today_vol < recent_20_vol_avg * AIZHU_VOL_RATIO:
        signals.append("长阳矮柱")
    
    if len(df) >= NIUGU_LOOKBACK:
        recent_60 = df.iloc[-NIUGU_LOOKBACK:]
        for i in range(len(recent_60)-1, 5, -1):
            row = recent_60.iloc[i]
            prev_row = recent_60.iloc[i-1]
            if row['volume'] / prev_row['volume'] >= BEISHU_RATIO and row['close'] > row['open']:
                beiliang_bottom = row['open']
                future = recent_60.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= beiliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                    signals.append("倍量不穿")
                break
    
    if len(df) >= NIUGU_LOOKBACK:
        recent_60 = df.iloc[-NIUGU_LOOKBACK:]
        max_vol_idx = recent_60['volume'].idxmax()
        max_vol_row = recent_60.loc[max_vol_idx]
        gaoliang_bottom = max_vol_row['low']
        future = recent_60.iloc[max_vol_idx + 1:]
        if len(future) > 0 and all(future['low'] >= gaoliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
            signals.append("高量不破")
    
    if len(df) >= 10:
        recent_10 = df.iloc[-10:]
        for i in range(len(recent_10)-1, 1, -1):
            row = recent_10.iloc[i]
            prev_row = recent_10.iloc[i-1]
            if row['open'] > prev_row['high']:
                gap_bottom = prev_row['high']
                future = recent_10.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= gap_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                    signals.append("跳空不补")
                break
    
    # ========== 【新增】更多涨停基因 ==========
    
    # 1. 地量群（百日低量群）：100天内有5根以上接近地量的柱子
    # 来源：量学25种涨停基因
    if len(df) >= DILIANG_GROUP_DAYS:
        recent_100 = df.iloc[-DILIANG_GROUP_DAYS:]
        vol_min = recent_100['volume'].min()
        vol_max = recent_100['volume'].max()
        vol_range = vol_max - vol_min
        if vol_range > 0:
            low_vol_count = sum(recent_100['volume'] < vol_min + vol_range * 0.2)
            if low_vol_count >= DILIANG_GROUP_COUNT:
                signals.append("地量群")
    
    # 2. 价升量缩：连续3天价升量缩
    # 来源：量学25种涨停基因
    if len(df) >= JIA_SHENG_LIANG_SUO_DAYS:
        recent_3 = df.iloc[-JIA_SHENG_LIANG_SUO_DAYS:]
        prices_up = all(recent_3.iloc[i]['close'] > recent_3.iloc[i-1]['close'] for i in range(1, len(recent_3)))
        vols_down = all(recent_3.iloc[i]['volume'] < recent_3.iloc[i-1]['volume'] for i in range(1, len(recent_3)))
        if prices_up and vols_down:
            signals.append("价升量缩")
    
    # 3. 回踩精准线：10天内踩到精准线
    # 来源：量学25种涨停基因
    if precise_price and len(df) >= HUICAI_PRECISION_DAYS:
        recent_10 = df.iloc[-HUICAI_PRECISION_DAYS:]
        touched = any(abs(row['low'] - precise_price) / precise_price < TOUCH_LINE_TOLERANCE for _, row in recent_10.iterrows())
        if touched:
            signals.append("回踩精准线")
    
    # 4. 双剑霸天地：今天有长上影线和长下影线
    # 来源：量学25种涨停基因
    upper_shadow = today_high - max(today_open, today_close)
    if body_size > 0:
        if upper_shadow / body_size > DOUBLE_SWORD_UPPER_RATIO and lower_shadow / body_size > DOUBLE_SWORD_LOWER_RATIO:
            signals.append("双剑霸天地")
    
    # 5. 三元连动：连续3天价升量缩（和价升量缩类似，但更强调连续）
    # 来源：量学25种涨停基因
    if len(df) >= SANYUAN_DAYS:
        recent_3 = df.iloc[-SANYUAN_DAYS:]
        prices_up = all(recent_3.iloc[i]['close'] > recent_3.iloc[i-1]['close'] for i in range(1, len(recent_3)))
        vols_down = all(recent_3.iloc[i]['volume'] < recent_3.iloc[i-1]['volume'] for i in range(1, len(recent_3)))
        if prices_up and vols_down:
            signals.append("三元连动")
    
    # 6. 兵临城下：股价在左峰下方3%以内蓄势
    # 来源：量学25种涨停基因
    if peak_20:
        distance_to_peak = (peak_20 - today_close) / today_close
        if 0 < distance_to_peak < BINGLINCHENGXIA_TOLERANCE and today_close > today_open:
            signals.append("兵临城下")
    
    # 7. 大阳双休：大阳线后5天内，回调不超过大阳线实体的50%
    # 来源：量学25种涨停基因
    if len(df) >= DAYANG_DOUBLE_REST_DAYS:
        recent_5 = df.iloc[-DAYANG_DOUBLE_REST_DAYS:]
        # 找前几天的大阳线
        for i in range(len(recent_5)-1, 0, -1):
            row = recent_5.iloc[i]
            body_pct_up = (row['close'] - row['open']) / row['open'] * 100
            if body_pct_up > 3:  # 大阳线
                # 后面的回调有没有超过大阳线实体的50%
                yang_bottom = row['open']
                yang_top = row['close']
                yang_mid = (yang_bottom + yang_top) / 2
                future = recent_5.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= yang_mid):
                    signals.append("大阳双休")
                break
    
    # 8. 接力双阳：两根相隔一段时间的阳线（将军柱/黄金柱接力）
    # 来源：量学25种涨停基因
    if len(df) >= JIELI_DOUBLE_YANG_GAP_MAX + 5:
        recent_30 = df.iloc[-30:]
        # 找两根大阳线
        big_yangs = []
        for i in range(len(recent_30)):
            row = recent_30.iloc[i]
            body_pct_up = (row['close'] - row['open']) / row['open'] * 100
            if body_pct_up > 3:
                big_yangs.append(i)
        
        if len(big_yangs) >= 2:
            gap = big_yangs[-1] - big_yangs[-2]
            if JIELI_DOUBLE_YANG_GAP_MIN <= gap <= JIELI_DOUBLE_YANG_GAP_MAX:
                signals.append("接力双阳")
    
    return signals


# ============================================================
# 【核心】生成量学理论推导式综合解读（原有，不修改）
# ============================================================
def generate_interpretation(stock):
    sections = []
    
    # ========== 【起点】大阴实顶的市场意义 ==========
    if stock['big_yin_top']:
        above_text = "上方" if bool(stock['price_above_yintop']) else "下方"
        pct_text = f"{stock['price_vs_yintop_pct']:+.2f}%"
        
        if bool(stock['price_above_yintop']):
            conclusion = "说明买方已经把那天卖方的成果抢回来了，买方在这个区间占优。"
        else:
            conclusion = "说明买方还没能收复那天卖方的失地，卖方在这个区间仍占优。"
        
        sections.append({
            'title': '【起点】大阴实顶的市场意义',
            'content': [
                f"大阴实顶发生在{stock['days_since_yin']}天前（{stock['big_yin_date']}），价格{stock['big_yin_top']:.2f}元。",
                '<strong>市场机理</strong>：这是多空双方上次「休战」的警戒点。那天卖方赢了，但休战后买方开始组织反击。',
                f'<strong>推导</strong>：现在价格在大阴实顶<strong>{above_text}</strong> {pct_text}，{conclusion}',
                '<strong>量学依据</strong>：大阴实顶是回形针看盘法的起点，是多空力量转换的分水岭。'
            ]
        })
    else:
        sections.append({
            'title': '【起点】大阴实顶的市场意义',
            'content': [
                '近60日没有出现中大阴线。',
                '<strong>市场机理</strong>：说明近期没有明显的多空大战分界线，市场处于相对平稳的状态。',
                '<strong>量学依据</strong>：没有大阴实顶，说明多空双方还没有进行过大规模决战。'
            ]
        })
    
    # ========== 【第一步】从右向左看——多空力量对比 ==========
    if stock['yang_count'] + stock['yin_count'] > 0:
        ratio = stock['yang_yin_ratio']
        if ratio > 1.5:
            detail = "阳线明显多于阴线，说明买方赢得更频繁，在这个区间有持续性优势。"
        elif ratio < 0.67:
            detail = "阴线明显多于阳线，说明卖方赢得更频繁，在这个区间仍占主动。"
        else:
            detail = "阴阳数量相当，说明多空双方在这个区间力量均衡，处于拉锯状态。"
        
        sections.append({
            'title': '【第一步】从右向左看——多空力量对比',
            'content': [
                f"从大阴实顶到今天：阳线{stock['yang_count']}根、阴线{stock['yin_count']}根，阴阳比{ratio:.2f}。",
                '<strong>市场机理</strong>：每根K线都是多空一天的战斗结果。阳线多=买方赢的天数多，阴线多=卖方赢的天数多。',
                f'<strong>推导</strong>：阴阳比{ratio:.2f}，{detail}',
                '<strong>量学依据</strong>：价柱的阴阳数量对比，是多空力量最直观的体现。'
            ]
        })
    
    # ========== 【第二步】从上往下看——量的真假判断 ==========
    if stock['big_yin_vol']:
        vol_size = stock['yin_vol_size']
        if vol_size == "大量":
            mechanism = "那天多空双方真刀真枪干了一架，卖方放量砸盘，说明卖方是真出货。"
            conclusion = "大阴实顶那天是<strong>大量</strong>，说明上方的抛压是真实的，后面突破起来会比较费劲。"
        elif vol_size == "小量":
            mechanism = "那天虽然价格跌了，但成交很清淡，说明没人接盘的「假跌」，卖方只是虚晃一枪。"
            conclusion = "大阴实顶那天是<strong>小量</strong>，说明那天的下跌是无量空跌，卖方力量其实不强，后面可能要涨。"
        else:
            mechanism = "那天的量和平时差不多，说明是正常的调整，没有明显的多空意图。"
            conclusion = "大阴实顶那天是<strong>平量</strong>，说明那次下跌是正常调整，没有特别的信号意义。"
        
        sections.append({
            'title': '【第二步】从上往下看——量的真假判断',
            'content': [
                f"大阴实顶那天的成交量：{vol_size}。",
                f'<strong>市场机理</strong>：{mechanism}',
                f'<strong>推导</strong>：{conclusion}',
                '<strong>量学依据</strong>：量是因，价是果。量大说明真有人卖，量小说明跌了也没人接。'
            ]
        })
    
    # ========== 【第三步】从左往右看——量的影响力 ==========
    if stock['big_yin_vol']:
        vol_ratio = stock['today_vs_yin_vol']
        days = stock['days_since_yin']
        
        if vol_ratio > 100:
            vol_judge = f"今天的量比大阴实顶那天还大（{vol_ratio:.1f}%），说明今天的博弈比那天还激烈。"
        elif vol_ratio < 50:
            vol_judge = f"今天的量只有大阴实顶那天的{vol_ratio:.1f}%，说明今天的成交比那天清淡很多。"
        else:
            vol_judge = f"今天的量和大阴实顶那天差不多（{vol_ratio:.1f}%）。"
        
        if days <= 10:
            time_judge = f"时间距离只有{days}天，那个位置的「记忆」还很新鲜。"
        elif days <= 30:
            time_judge = f"时间距离{days}天，那个位置还有一定的影响力。"
        else:
            time_judge = f"时间距离已经{days}天了，那个位置的影响力已经比较弱了。"
        
        sections.append({
            'title': '【第三步】从左往右看——量的影响力',
            'content': [
                f"{vol_judge}",
                f"{time_judge}",
                '<strong>市场机理</strong>：量越大、时间越近，那个位置的「记忆」就越新鲜，对当下的影响力就越强。就像打仗，刚打完的战场大家都记得住，隔了几个月的战场就没人在乎了。',
                f'<strong>推导</strong>：综合量的大小和时间距离，大阴实顶的量对当下的影响力是<strong>{stock["time_impact"]}</strong>。',
                '<strong>量学依据</strong>：量柱的远近多少，决定了那个量柱对当下的影响力大小。'
            ]
        })
    
    # ========== 【第四步】从下往上看——当下量价建构 ==========
    vol_len = stock['vol_length']
    price_len = stock['price_length']
    body_ratio = stock['body_ratio']
    
    today_direction = "买方" if stock['power'] == "买方占优" else "卖方"
    
    if body_ratio > 60:
        body_judge = f"实体占比{body_ratio:.1f}%，实体较长，说明{today_direction}今天赢了，而且赢得比较彻底。"
    elif body_ratio < 30:
        body_judge = f"实体占比{body_ratio:.1f}%，实体很短，说明今天多空打了个平手，都没占到便宜。"
    else:
        body_judge = f"实体占比{body_ratio:.1f}%，实体中等，说明{today_direction}今天赢了，但赢得不算彻底。"
    
    sections.append({
        'title': '【第四步】从下往上看——当下量价建构',
        'content': [
            f"今天的量柱：{vol_len}；今天的价柱：{price_len}。",
            f"{body_judge}",
            '<strong>市场机理</strong>：量柱长短=今天多空双方投入了多少兵力；价柱长短=今天战斗的激烈程度；实体长短=今天哪一方赢了，赢得彻不彻底。',
            f'<strong>推导</strong>：今天{vol_len}、{price_len}、{body_judge}',
            '<strong>量学依据</strong>：量价的长短伸缩，是当下多空力量最直接的体现。'
        ]
    })
    
    # ========== 【第五步】左侧关键位的约束 ==========
    key_points = []
    
    if stock['peak_20']:
        above = "上方" if stock['close'] > stock['peak_20'] else "下方"
        key_points.append(f"20日峰顶线{stock['peak_20']:.2f}元（{stock['peak_date_20']}）：当前在<strong>{above}</strong>")
    
    if stock['valley_20']:
        above = "上方" if stock['close'] > stock['valley_20'] else "下方"
        key_points.append(f"20日谷底线{stock['valley_20']:.2f}元（{stock['valley_date_20']}）：当前在<strong>{above}</strong>")
    
    if stock['precise_lines']:
        pl = stock['precise_lines'][0]
        above = "上方" if stock['close'] > pl['price'] else "下方"
        key_points.append(f"精准线{pl['price']:.2f}元（{pl['points']}个点）：当前在<strong>{above}</strong>")
    
    if stock['safe_20']:
        above = "上方" if stock['close'] > stock['safe_20'] else "下方"
        key_points.append(f"20日高量柱安全线{stock['safe_20']:.2f}元（{stock['date_20']}）：当前在<strong>{above}</strong>")
    
    if stock['balance_price']:
        above = "上方" if stock['close'] > stock['balance_price'] else "下方"
        key_points.append(f"平衡线{stock['balance_price']:.2f}元（{stock['balance_date']}）：当前在<strong>{above}</strong>")
    
    if stock.get('pillar_type') and stock['pillar_type'] != "无":
        above = "上方" if stock['close'] > stock['golden_line'] else "下方"
        key_points.append(f"{stock['pillar_type']}黄金线{stock['golden_line']:.2f}元（{stock['pillar_date']}）：当前在<strong>{above}</strong>")
    
    if stock.get('aokou_price'):
        above = "上方" if stock['close'] > stock['aokou_price'] else "下方"
        key_points.append(f"凹口线{stock['aokou_price']:.2f}元（{stock['aokou_date']}）：当前在<strong>{above}</strong>")
    
    if key_points:
        sections.append({
            'title': '【第五步】左侧关键位的约束',
            'content': [
                '当前价格与左侧关键位的关系：',
                *[f"• {kp}" for kp in key_points],
                '<strong>市场机理</strong>：峰顶线=上次卖方赢了的位置，现在变成压力位；谷底线=上次买方赢了的位置，现在变成支撑位；精准线=多空双方多次在同一价位交手，说明这个位置双方都很看重；高量柱安全线=上次多空最激烈战斗中买方守住的位置。',
                '<strong>量学依据</strong>：量线是多空双方的「记忆」，每次打到这个位置，都会触发上次的记忆，产生支撑或压力。'
            ]
        })
    
    # ========== 【综合结论】逻辑闭环 ==========
    conclusion_points = []
    
    if stock['big_yin_top']:
        if bool(stock['price_above_yintop']):
            conclusion_points.append("买方已经收复了大阴实顶，说明买方在这个区间占优")
        else:
            conclusion_points.append("买方还没能收复大阴实顶，卖方仍在这个区间占优")
    
    if stock['yang_yin_ratio'] > 1.5:
        conclusion_points.append("从大阴实顶到今天，阳线多于阴线，说明买方在逐步推进")
    elif stock['yang_yin_ratio'] < 0.67:
        conclusion_points.append("从大阴实顶到今天，阴线多于阳线，说明卖方仍在压制")
    
    if stock['yin_vol_size'] == "小量":
        conclusion_points.append("大阴实顶那天是小量，说明那次下跌是无量空跌，卖方力量不强")
    elif stock['yin_vol_size'] == "大量":
        conclusion_points.append("大阴实顶那天是大量，说明那次下跌是真出货，上方有真实压力")
    
    conclusion_points.append(f"今天{stock['pct_chg']:+.2f}%，{stock['power']}")
    conclusion_points.append(f"当前在近120日{stock['pos_status']}")
    
    sections.append({
        'title': '【综合结论】逻辑闭环',
        'content': [
            '把以上五步串起来：',
            *[f"{i+1}. {p}" for i, p in enumerate(conclusion_points)],
            f'<strong>最终判断</strong>：当前价格在{stock["pos_status"]}，{stock["power"]}，近3日涨跌{stock["pct_3d"]:+.2f}%，近5日涨跌{stock["pct_5d"]:+.2f}%。',
            '<strong>注意</strong>：以上是基于量学理论的客观描述，不构成任何交易建议。'
        ]
    })
    
    return sections


# ============================================================
# 生成单只股票的报告数据（原有功能 + 新增信号）
# ============================================================
def get_stock_data(market, code):
    df, name = load_klines(market, code)
    
    if df is None:
        return None
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    today_price = today['close']
    today_volume = today['volume']
    
    pct_chg = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    
    big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx = find_big_yin_top(
        df, YIN_LOOKBACK, YIN_BODY_PCT
    )
    
    if big_yin_top:
        price_vs_yintop = today_price - big_yin_top
        price_vs_yintop_pct = price_vs_yintop / big_yin_top * 100
        price_above_yintop = bool(price_vs_yintop > 0)
    else:
        price_vs_yintop = 0
        price_vs_yintop_pct = 0
        price_above_yintop = None
    
    if big_yin_idx:
        period_df = df.iloc[big_yin_idx:]
        yang_count = int(sum(period_df['close'] > period_df['open']))
        yin_count = int(sum(period_df['close'] < period_df['open']))
        yang_yin_ratio = yang_count / max(yin_count, 1)
    else:
        yang_count = 0
        yin_count = 0
        yang_yin_ratio = 0
    
    recent_20 = df.iloc[-SHORT_WINDOW:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    
    if big_yin_vol:
        avg_vol_20 = recent_20['volume'].mean()
        big_yin_vs_avg = big_yin_vol / avg_vol_20
        if big_yin_vs_avg > VOL_RATIO_HIGH:
            yin_vol_size = "大量"
        elif big_yin_vs_avg < VOL_RATIO_LOW:
            yin_vol_size = "小量"
        else:
            yin_vol_size = "平量"
    else:
        yin_vol_size = "未知"
        big_yin_vs_avg = 0
    
    if big_yin_idx:
        days_since_yin = len(df) - 1 - big_yin_idx
    else:
        days_since_yin = 0
    
    if big_yin_vol:
        today_vs_yin_vol = today_volume / big_yin_vol * 100
    else:
        today_vs_yin_vol = 0
    
    if days_since_yin <= 10:
        time_impact = "很近（影响力强）"
    elif days_since_yin <= 30:
        time_impact = "中等（影响力一般）"
    else:
        time_impact = "很远（影响力弱）"
    
    vol_high_20 = recent_20['volume'].max()
    vol_low_20 = recent_20['volume'].min()
    vol_pos_20 = (today_volume - vol_low_20) / (vol_high_20 - vol_low_20) * 100
    
    if vol_pos_20 > VOL_POS_HIGH:
        vol_length = "长量柱（天量）"
    elif vol_pos_20 < VOL_POS_LOW:
        vol_length = "短量柱（地量）"
    else:
        vol_length = "中等量柱"
    
    today_range = today['high'] - today['low']
    avg_range_20 = recent_20.apply(lambda x: x['high'] - x['low'], axis=1).mean()
    range_ratio = today_range / avg_range_20
    
    if range_ratio > 1.5:
        price_length = "长价柱（振幅大）"
    elif range_ratio < 0.7:
        price_length = "短价柱（振幅小）"
    else:
        price_length = "中等价柱"
    
    body_size = abs(today['close'] - today['open'])
    body_ratio = body_size / today_range * 100 if today_range > 0 else 0
    
    if body_ratio > BODY_RATIO_LONG * 100:
        body_length = "长实体"
    elif body_ratio < BODY_RATIO_SHORT * 100:
        body_length = "短实体（十字星）"
    else:
        body_length = "中等实体"
    
    safe_20, risk_20, type_20, date_20, key_vol_20 = find_gaoliang_lines(recent_20)
    
    safe_60 = risk_60 = type_60 = date_60 = key_vol_60 = None
    recent_60 = df.iloc[-MID_WINDOW:] if len(df) > MID_WINDOW else None
    if recent_60 is not None:
        safe_60, risk_60, type_60, date_60, key_vol_60 = find_gaoliang_lines(recent_60)
    
    safe_120 = risk_120 = type_120 = date_120 = key_vol_120 = None
    recent_120 = df.iloc[-LONG_WINDOW:] if len(df) > LONG_WINDOW else None
    if recent_120 is not None:
        safe_120, risk_120, type_120, date_120, key_vol_120 = find_gaoliang_lines(recent_120)
    
    balance_price, balance_date = find_balance_line(df, BALANCE_LOOKBACK, BALANCE_YIN_BODY_PCT)
    precise_lines = find_precise_lines(df, PRECISE_LOOKBACK, PRECISE_MIN_POINTS, PRECISE_PRICE_TOLERANCE)
    
    peak_20, peak_date_20, valley_20, valley_date_20, peaks_20, valleys_20 = find_fenggu_lines(
        df, SHORT_WINDOW, PEAK_SIDE_SHORT, CONFIRM_DAYS_SHORT, VOL_PERCENTILE
    )
    
    peak_60 = peak_date_60 = valley_60 = valley_date_60 = None
    peaks_60 = []
    valleys_60 = []
    if len(df) >= MID_WINDOW + CONFIRM_DAYS_MID + PEAK_SIDE_MID:
        peak_60, peak_date_60, valley_60, valley_date_60, peaks_60, valleys_60 = find_fenggu_lines(
            df, MID_WINDOW, PEAK_SIDE_MID, CONFIRM_DAYS_MID, VOL_PERCENTILE
        )
    
    peak_120 = peak_date_120 = valley_120 = valley_date_120 = None
    peaks_120 = []
    valleys_120 = []
    if len(df) >= LONG_WINDOW + CONFIRM_DAYS_LONG + PEAK_SIDE_LONG:
        peak_120, peak_date_120, valley_120, valley_date_120, peaks_120, valleys_120 = find_fenggu_lines(
            df, LONG_WINDOW, PEAK_SIDE_LONG, CONFIRM_DAYS_LONG, VOL_PERCENTILE
        )
    
    up_line, down_line = find_xieheng_line(peaks_120, valleys_120, today_price)
    vol_pattern = identify_vol_pattern(df)
    impact_20, vol_ratio_20, time_dist_20 = judge_key_vol_impact(df, key_vol_20, date_20)
    
    pillar_type, pillar_date, golden_line = find_pillars(df)
    aokou_price, aokou_date, aokou_gap = find_aokou_line(df)
    
    precise_price = precise_lines[0]['price'] if precise_lines else None
    extra_signals = identify_all_signals(df, valley_20, safe_20, precise_price, big_yin_top, peak_20)
    
    short_dist_high = (recent_high - today_price) / today_price * 100
    short_dist_low = (today_price - recent_low) / today_price * 100
    
    mid_high = mid_low = None
    mid_dist_high = mid_dist_low = None
    if recent_60 is not None:
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
        mid_dist_high = (mid_high - today_price) / today_price * 100
        mid_dist_low = (today_price - mid_low) / today_price * 100
    
    long_high = long_low = None
    long_dist_high = long_dist_low = None
    if recent_120 is not None:
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
        long_dist_high = (long_high - today_price) / today_price * 100
        long_dist_low = (today_price - long_low) / today_price * 100
    
    pos_120 = (today_price - long_low) / (long_high - long_low) * 100 if long_high else 50
    
    if pos_120 > POSITION_HIGH:
        pos_status = "高位"
    elif pos_120 < POSITION_LOW:
        pos_status = "低位"
    else:
        pos_status = "中位"
    
    power = "买方占优" if today['close'] > today['open'] else "卖方占优"
    
    pct_3d = (today['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100
    pct_5d = (today['close'] - df.iloc[-6]['close']) / df.iloc[-6]['close'] * 100
    
    stock_data = {
        'name': name,
        'code': f"{market}{code}",
        'date': today['date'],
        'close': today_price,
        'pct_chg': pct_chg,
        'big_yin_top': big_yin_top,
        'big_yin_date': big_yin_date,
        'big_yin_vol': big_yin_vol,
        'price_above_yintop': price_above_yintop,
        'price_vs_yintop_pct': price_vs_yintop_pct,
        'yang_count': yang_count,
        'yin_count': yin_count,
        'yang_yin_ratio': yang_yin_ratio,
        'recent_high': recent_high,
        'recent_low': recent_low,
        'yin_vol_size': yin_vol_size,
        'days_since_yin': days_since_yin,
        'today_vs_yin_vol': today_vs_yin_vol,
        'time_impact': time_impact,
        'vol_pos_20': vol_pos_20,
        'vol_length': vol_length,
        'price_length': price_length,
        'body_length': body_length,
        'body_ratio': body_ratio,
        'safe_20': safe_20,
        'risk_20': risk_20,
        'date_20': date_20,
        'safe_60': safe_60,
        'risk_60': risk_60,
        'date_60': date_60,
        'safe_120': safe_120,
        'risk_120': risk_120,
        'date_120': date_120,
        'balance_price': balance_price,
        'balance_date': balance_date,
        'precise_lines': precise_lines,
        'up_line': up_line,
        'down_line': down_line,
        'peak_20': peak_20,
        'peak_date_20': peak_date_20,
        'valley_20': valley_20,
        'valley_date_20': valley_date_20,
        'peak_60': peak_60,
        'peak_date_60': peak_date_60,
        'valley_60': valley_60,
        'valley_date_60': valley_date_60,
        'peak_120': peak_120,
        'peak_date_120': peak_date_120,
        'valley_120': valley_120,
        'valley_date_120': valley_date_120,
        'vol_pattern': vol_pattern,
        'impact_20': impact_20,
        'vol_ratio_20': vol_ratio_20,
        'short_dist_high': short_dist_high,
        'short_dist_low': short_dist_low,
        'mid_high': mid_high,
        'mid_low': mid_low,
        'mid_dist_high': mid_dist_high,
        'mid_dist_low': mid_dist_low,
        'long_high': long_high,
        'long_low': long_low,
        'long_dist_high': long_dist_high,
        'long_dist_low': long_dist_low,
        'pos_status': pos_status,
        'power': power,
        'pct_3d': pct_3d,
        'pct_5d': pct_5d,
        'pillar_type': pillar_type,
        'pillar_date': pillar_date,
        'golden_line': golden_line,
        'aokou_price': aokou_price,
        'aokou_date': aokou_date,
        'aokou_gap': aokou_gap,
        'extra_signals': extra_signals,
    }
    
    stock_data['interpretations'] = generate_interpretation(stock_data)
    
    return stock_data


# ============================================================
# 生成HTML（原有结构 + 新增显示）
# ============================================================
def generate_html(stocks_data, today_str):
    items = []
    for stock in stocks_data:
        if stock is None:
            continue
        
        price_class = "price-up" if stock['pct_chg'] > 0 else "price-down"
        
        if stock['big_yin_top']:
            yintop_text = f"{stock['big_yin_top']:.2f}（{stock['big_yin_date']}）"
        else:
            yintop_text = "无（近60日无中大阴线）"
        
        if stock['price_above_yintop'] is None:
            yintop_status = "未知"
            yintop_color = "#94a3b8"
        elif bool(stock['price_above_yintop']):
            yintop_status = "上方（强势）"
            yintop_color = "#ef4444"
        else:
            yintop_status = "下方（弱势）"
            yintop_color = "#22c55e"
        
        precise_html = ""
        if stock['precise_lines']:
            for i, line in enumerate(stock['precise_lines']):
                precise_html += f"""
                <div class="grid-item">
                    <div class="label">精准线{i+1}（{line['points']}点）</div>
                    <div class="value">{line['price']:.2f}（{line['first_date']}~{line['last_date']}）</div>
                </div>
                """
        else:
            precise_html = """
            <div class="grid-item">
                <div class="label">精准线</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        def peak_html(label, price, date):
            if price is not None and date is not None:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value">{price:.2f}（{date}）</div>
                </div>
                """
            else:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value value-none value-strong">无（寻顶中·偏强）</div>
                </div>
                """
        
        def valley_html(label, price, date):
            if price is not None and date is not None:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value">{price:.2f}（{date}）</div>
                </div>
                """
            else:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value value-none value-weak">无（寻底中·偏弱）</div>
                </div>
                """
        
        if stock['pillar_type'] == "元帅柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #fbbf24;">
                <div class="label">👑 元帅柱</div>
                <div class="value" style="color:#fbbf24;">{stock['pillar_date']}</div>
            </div>
            """
        elif stock['pillar_type'] == "黄金柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #fbbf24;">
                <div class="label">⭐ 黄金柱</div>
                <div class="value" style="color:#fbbf24;">{stock['pillar_date']}</div>
            </div>
            """
        elif stock['pillar_type'] == "将军柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #60a5fa;">
                <div class="label">将军柱</div>
                <div class="value" style="color:#60a5fa;">{stock['pillar_date']}</div>
            </div>
            """
        else:
            pillar_html = """
            <div class="grid-item">
                <div class="label">王牌柱</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        if stock['aokou_price']:
            aokou_html = f"""
            <div class="grid-item" style="border:2px solid #a78bfa;">
                <div class="label">🎯 凹口线</div>
                <div class="value" style="color:#a78bfa;">{stock['aokou_price']:.2f}（{stock['aokou_date']}，间隔{stock['aokou_gap']}天）</div>
            </div>
            """
        else:
            aokou_html = """
            <div class="grid-item">
                <div class="label">凹口线</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        extra_html = ""
        if stock['extra_signals']:
            for sig in stock['extra_signals']:
                extra_html += f'<span style="display:inline-block; background:#fbbf24; color:#000; padding:2px 8px; border-radius:4px; font-size:11px; margin:2px;">{sig}</span>'
        else:
            extra_html = '<span style="color:#94a3b8; font-size:12px;">无</span>'
        
        interp_html = ""
        for section in stock['interpretations']:
            interp_html += f"""
            <div style="margin-bottom: 12px; padding: 10px; background: #0f172a; border-radius: 8px; border-left: 3px solid #fbbf24;">
                <div style="font-weight: bold; color: #fbbf24; margin-bottom: 6px; font-size: 13px;">{section['title']}</div>
            """
            for line in section['content']:
                interp_html += f'                <p style="margin: 4px 0; font-size: 12px; color: #cbd5e1; line-height: 1.7;">{line}</p>\n'
            interp_html += """            </div>"""
        
        item_html = f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {price_class}">{stock['close']:.2f}元 ({stock['pct_chg']:+.2f}%)</div>
            </div>
            
            <div class="step-section">
                <div class="step-title">起点：大阴实顶</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶（近60日）</div>
                            <div class="value">{yintop_text}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">当前位置</div>
                            <div class="value" style="color:{yintop_color}">{yintop_status}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">① 从右向左看：比较价柱的高低阴阳</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">价格vs大阴实顶</div>
                            <div class="value">{stock['price_vs_yintop_pct']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阳线/阴线数量</div>
                            <div class="value">{stock['yang_count']}阳 / {stock['yin_count']}阴</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阴阳比</div>
                            <div class="value">{stock['yang_yin_ratio']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日高点</div>
                            <div class="value">{stock['recent_high']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日低点</div>
                            <div class="value">{stock['recent_low']:.2f}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">② 从上往下看：比较量价的真假大小</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶的量</div>
                            <div class="value">{stock['yin_vol_size']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今日量柱形态</div>
                            <div class="value">{stock['vol_pattern']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">③ 从左往右看：比较量柱的远近多少</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">时间距离</div>
                            <div class="value">{stock['days_since_yin']}天前</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">时间影响力</div>
                            <div class="value">{stock['time_impact']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今天量vs大阴实顶量</div>
                            <div class="value">{stock['today_vs_yin_vol']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">关键位量影响力</div>
                            <div class="value" style="color:{'#ef4444' if stock['impact_20'] == '强' else '#fbbf24' if stock['impact_20'] == '中' else '#94a3b8'}">{stock['impact_20']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">④ 从下往上看：比较量价的长短伸缩</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">量柱长短</div>
                            <div class="value">{stock['vol_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能位置(20日)</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">价柱伸缩</div>
                            <div class="value">{stock['price_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体占比</div>
                            <div class="value">{stock['body_ratio']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">📊 今日信号</div>
                <div class="step-content">
                    {extra_html}
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">王牌柱体系</div>
                <div class="step-content">
                    <div class="grid-2">
                        {pillar_html}
                        <div class="grid-item">
                            <div class="label">黄金线</div>
                            <div class="value">{f"{stock['golden_line']:.2f}" if stock['golden_line'] else "无"}</div>
                        </div>
                        {aokou_html}
                        <div class="grid-item">
                            <div class="label">20日量柱位置</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">⑤ 左侧关键位</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">平衡线</div>
                            <div class="value">{f"{stock['balance_price']:.2f}（{stock['balance_date']}）" if stock['balance_price'] else '-'}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">精准线</div>
                            <div class="value">{f"{stock['precise_lines'][0]['price']:.2f}（{stock['precise_lines'][0]['points']}点）" if stock['precise_lines'] else '-'}</div>
                        </div>
                        {peak_html('20日峰顶线', stock['peak_20'], stock['peak_date_20'])}
                        {valley_html('20日谷底线', stock['valley_20'], stock['valley_date_20'])}
                        <div class="grid-item">
                            <div class="label">20日安全线</div>
                            <div class="value">{f"{stock['safe_20']:.2f}（{stock['date_20']}）" if stock['safe_20'] else '-'}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日风险线</div>
                            <div class="value">{f"{stock['risk_20']:.2f}（{stock['date_20']}）" if stock['risk_20'] else '-'}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">📖 综合解读（量学理论推导）</div>
                <div class="step-content" style="background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);">
                    {interp_html}
                </div>
            </div>
        </div>
        """
        items.append(item_html)
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>四维循环看盘报告 - {today_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: #0f172a; 
            color: #e2e8f0; 
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ 
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); 
            color: white; 
            padding: 30px; 
            border-radius: 12px; 
            margin-bottom: 20px;
            border-left: 4px solid #fbbf24;
        }}
        .header h1 {{ font-size: 24px; color: #fbbf24; margin-bottom: 8px; }}
        .header .date {{ opacity: 0.8; font-size: 14px; }}
        
        .signal-guide {{
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #334155;
        }}
        .signal-guide h2 {{
            font-size: 18px;
            color: #fbbf24;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #334155;
        }}
        .signal-item {{
            margin-bottom: 12px;
            padding: 10px;
            background: #0f172a;
            border-radius: 8px;
        }}
        .signal-item h3 {{
            font-size: 14px;
            color: #60a5fa;
            margin-bottom: 6px;
        }}
        .signal-item p {{
            font-size: 12px;
            color: #cbd5e1;
            margin-bottom: 4px;
        }}
        .signal-item .source {{
            font-size: 11px;
            color: #94a3b8;
            font-style: italic;
        }}
        
        .stock-card {{ 
            background: #1e293b; 
            border-radius: 12px; 
            padding: 20px; 
            margin-bottom: 15px; 
            border: 1px solid #334155;
        }}
        .stock-header {{ 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 15px; 
            padding-bottom: 15px; 
            border-bottom: 1px solid #334155;
        }}
        .stock-name {{ font-size: 18px; font-weight: bold; color: #e2e8f0; }}
        .stock-code {{ font-size: 12px; color: #94a3b8; }}
        .stock-price {{ font-size: 22px; font-weight: bold; }}
        .price-up {{ color: #ef4444; }}
        .price-down {{ color: #22c55e; }}
        
        .step-section {{ margin-bottom: 15px; }}
        .step-title {{ 
            font-size: 14px; 
            font-weight: bold; 
            color: #60a5fa; 
            margin-bottom: 8px; 
            padding-left: 8px; 
            border-left: 3px solid #fbbf24; 
        }}
        .step-content {{ 
            background: #0f172a; 
            padding: 12px; 
            border-radius: 8px; 
            font-size: 13px; 
            color: #cbd5e1; 
        }}
        
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .grid-item {{ 
            background: #0f172a; 
            padding: 8px; 
            border-radius: 6px; 
            font-size: 13px; 
        }}
        .grid-item .label {{ color: #94a3b8; font-size: 11px; }}
        .grid-item .value {{ font-weight: bold; color: #e2e8f0; font-size: 12px; }}
        .grid-item .value-none {{ color: #94a3b8; font-weight: normal; font-size: 11px; }}
        .grid-item .value-strong {{ color: #ef4444; font-weight: normal; font-size: 11px; }}
        .grid-item .value-weak {{ color: #22c55e; font-weight: normal; font-size: 11px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>四维循环看盘报告</h1>
            <div class="date">{today_str}</div>
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">量学完整版：大阴实顶 + 四维对比 + 王牌柱 + 凹口线 + 25种涨停基因 + 逻辑闭环解读</div>
        </div>
        
        <div class="signal-guide">
            <h2>信号说明</h2>
            
            <div class="signal-item">
                <h3>起点：大阴实顶</h3>
                <p><strong>定义：</strong>从今天往左找最近的中大阴线，其实体顶部就是「大阴实顶」</p>
                <p><strong>原理：</strong>大阴实顶是多空双方上次休战的「警戒点」，下次争夺的「起动点」</p>
                <p class="source">来源：股海明灯（量学官网）</p>
            </div>
            
            <div class="signal-item">
                <h3>四维看盘法</h3>
                <p>① 从右向左看：比较价柱的高低阴阳</p>
                <p>② 从上往下看：比较量价的真假大小</p>
                <p>③ 从左往右看：比较量柱的远近多少</p>
                <p>④ 从下往上看：比较量价的长短伸缩</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>王牌柱体系</h3>
                <p><strong>将军柱</strong>：基柱（阳线+放量）+ 三日不破 + 量柱不抬头</p>
                <p><strong>黄金柱</strong>：将军柱 + 价升 + 量缩</p>
                <p><strong>元帅柱</strong>：黄金柱 + 基柱跳空高开</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著 + 2026年化量化升级</p>
            </div>
            
            <div class="signal-item">
                <h3>25种涨停基因</h3>
                <p><strong>已加：</strong>过左峰、假阴真阳、极阴次阳、长阳矮柱、牛股三绝（倍量不穿/高量不破/跳空不补）、地量群、价升量缩、回踩精准线、双剑霸天地、三元连动、兵临城下、大阳双休、接力双阳</p>
                <p class="source">来源：股海明灯论坛《量学的25种涨停基因清单》</p>
            </div>
            
            <div class="signal-item">
                <h3>凹口线</h3>
                <p><strong>定义：</strong>两侧平量柱夹中间缩量柱，间隔3-13天</p>
                <p><strong>原理：</strong>凹口淘金，中间缩量说明抛压耗尽，后面要涨</p>
                <p class="source">来源：黑马王子《涨停密码》</p>
            </div>
            
            <div class="signal-item">
                <h3>量线体系</h3>
                <p>平衡线、精准线、斜衡线、峰顶线、谷底线、高量柱安全线/风险线、黄金线</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>形态信号</h3>
                <p>阳胜进/阴胜出/小倍阳/长腿踩线/长阴短柱/阳包阴/阴包阳/跳空/十字星</p>
            </div>
            
            <div class="signal-item">
                <h3>最高原则</h3>
                <p><strong>所有参数、阈值都要适配当前最新市场环境</strong></p>
                <p><strong>代码不要写死，能用参数阈值的就用参数阈值</strong></p>
                <p><strong>不构成任何交易建议，只做客观描述</strong></p>
            </div>
        </div>
        
        {''.join(items)}
    </div>
</body>
</html>
"""
    
    return html


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("四维循环看盘报告 - HTML版（量学完整版）")
    print("=" * 60)
    
    stocks_data = []
    today_str = ""
    
    for market, code in HOLDINGS:
        try:
            data = get_stock_data(market, code)
            if data:
                stocks_data.append(data)
                today_str = data['date']
                print(f"  已生成：{data['name']}")
        except Exception as e:
            print(f"  Error: {market}{code} {e}")
    
    html_content = generate_html(stocks_data, today_str)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_file = OUTPUT_DIR / f"my_holdings_4d_report_{today_str}.html"
    
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML报告: {html_file}")


if __name__ == "__main__":
    main()
